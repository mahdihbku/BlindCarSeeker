#!/usr/bin/env python
from openalpr import Alpr
import cv2
import time
import argparse
import os
import pickle
import sys
import numpy as np
import socket
import ec_elgamal
import os
import struct
import random
from multiprocessing import Pool
from random import randint
import itertools

parser = argparse.ArgumentParser()
#Capturing options in order:
parser.add_argument('--pi_camera',		action='store_true',		help='Execute client.py from Raspberry Pi.'						)
parser.add_argument('--one_image',		type=str,	default="",		help="Send the scores for one image."							)
parser.add_argument('--video',			type=str,	default="",		help="Detect faces from a video sequence."						)
parser.add_argument('--capture_device',	type=int,	default=0,		help='Capture device. 0 for latop webcam and 1 for usb webcam.'	)
#Other parameters:
parser.add_argument('--img_dim',		type=int,	default=96,		help="Default image dimension."									)
parser.add_argument('--server_port',	type=int,	default=6546,	help="Port of the server.",										)
parser.add_argument('--server_ip',		type=str,	default='127.0.0.1', help="IP of the server.",									)
parser.add_argument('--cpus',			type=int,	default=4,		help="Number of parallel CPUs to be used.",						)
parser.add_argument('--sensitivity',	type=int,	default=2,		help="Non-matching characters in the plate (0,1,2).",			)
parser.add_argument('--verbose',		action='store_true',		help="Output more details."										)
parser.add_argument('--load', 			action='store_true',		help="Load from stored encrypted DB."							)
args = parser.parse_args()

plate_size		= 8		# N: the max number of chars in the plate
pub_key_file 	= "rec_pub.txt"
DB_file 		= "rec_DB.data"
ext_DB_file		= "ext_DB.data"
Y_file			= "Y.data"
rand_nbrs_bitlen= 256
ec_elgamal_ct_size	 = 130

# Temporary global variables
Y	= []
DB	= []
ext_DB = []
encoded_plate = ""
server_plates_count = 0

def connect_to_server():
	sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	server_address = (args.server_ip, args.server_port)
	if args.verbose:	print("connectToServer: Connecting to {}:{}...".format(args.server_ip, args.server_port))
	sock.connect(server_address)
	if args.verbose:	print("connectToServer: Connected")
	return sock

def get_pub_key(sock):
	try:
		if args.verbose:	print("getPubKey: Getting the server's key...")
		message = 'GET pub_key'
		sock.sendall(message)
		pub_key = recv_msg(sock)
		f = open(pub_key_file, "w")
		f.write(pub_key)
		f.close()
		if args.verbose:	print("getPubKey: Key received")
	except:
		print("getPubKey: Error")

def get_DB_file(sock):
	try:
		if args.verbose:	print("get_DB_file: Getting Encrypted DB...")
		message = "GET DBfiles"
		sock.sendall(message)
		DB = recv_msg(sock)
		f = open(DB_file, 'w')
		f.write(DB)
		f.close()
		if args.verbose:	print("get_DB_file: Encrypted DB received")
	except:
		print("getBCfiles: Error")

def send_msg(sock, msg):
	msg = struct.pack('>I', len(msg)) + msg
	sock.sendall(msg)

def recv_msg(sock):
	raw_msglen = recv_all(sock, 4)
	if not raw_msglen:
		return None
	msglen = struct.unpack('>I', raw_msglen)[0]
	return recv_all(sock, msglen)

def recv_all(sock, n):
	data = b''
	while len(data) < n:
		packet = sock.recv(n - len(data))
		if not packet:
			return None
		data += packet
	return data

def encrypt_for_Y(list):
	return [[ec_elgamal.encrypt_ec("-"+str(g*10**(k*2))) for k in range (8)] for g in list]

def generate_local_files():
	start_gen_Y = time.time()
	ec_elgamal.prepare_for_enc(pub_key_file)
	if args.verbose:	print("generate_local_files: Generating local Y...")
	pool = Pool(processes=args.cpus)
	Y_values = range(100)
	Y = pool.map(encrypt_for_Y, (Y_values[int(i*100/args.cpus):int((i+1)*100/args.cpus)] for i in range(args.cpus)))
	Y = [ent for sublist in Y for ent in sublist]
	np.save(Y_file, Y)
	del Y
	pool.close()
	end_gen_Y = time.time()
	if args.verbose:	print("generate_local_files: Y generated in: {} ms".format((end_gen_Y-start_gen_Y)*1000))
	results_file = open("camera_results.txt","a+")
	results_file.write("Offile:CPUs_camera= {} Y_gen= {} Y_size= {} ".format(args.cpus,(end_gen_Y-start_gen_Y)*1000,100*8*128*1.00/1024))
	results_file.close()

def encode_plate_number(detected_plate):
	encoded_plate = []
	for char in detected_plate:
		if char not in ['\n','\t',' ']:
			encoded_plate.append(str(ord(char)-26))	# max ascii code 126
	for i in range(len(encoded_plate), plate_size):
		encoded_plate.append('99')
	return "".join(encoded_plate)

def sendScores(connection, scores):
	try:
		message = "new_scores "
		connection.sendall(message)
		send_msg(connection, scores)
	except:
		print ("sendScores: Error")

def frame_processor(frame):	# TODO check if add8 is better than 8xadd2 !!!
	global encoded_plate
	global server_plates_count
	alpr = Alpr("us", "/etc/openalpr/openalpr.conf", "/usr/share/openalpr/runtime_data")
	server_plates_count = len(DB)
	recog_start_time = time.time()
	results = alpr.recognize_ndarray(frame)
	plate = results.values()[5][0].values()[0] if results.values()[5] != [] else []
	if plate == []:
		if args.verbose:	print("frame_processor: No plate number in frame")
		return 0
	encoded_plate = encode_plate_number(plate)
	recog_end_time = time.time()
	print("frame_processor: Detected plate= {}".format(plate)) #TODO to delete
	if args.verbose:	print("frame_processor: Plate recognition = {} ms".format((recog_end_time-recog_start_time)*1000))

	start_enc = time.time()
	dist_comp_start = time.time()
	pool = Pool(processes=args.cpus)
	server_plates_list = range(server_plates_count)
	encrypted_scores = pool.map(process_plates, (server_plates_list[int(i*server_plates_count/args.cpus):int((i+1)*server_plates_count/args.cpus)] for i in range(args.cpus)))
	encrypted_scores = [ent for sublist in encrypted_scores for ent in sublist]
	dist_comp_end = time.time()
	if args.verbose:	print("frame_processor: Computing distances = {} ms".format((dist_comp_end-dist_comp_start)*1000))
	
	dist_obf_start = time.time()
	pool = Pool(processes=args.cpus)
	obfs_scores = pool.map(obfuscate_scores, (encrypted_scores[int(i*len(encrypted_scores)/args.cpus):int((i+1)*len(encrypted_scores)/args.cpus)] for i in range(args.cpus)))
	obfs_scores = [ent for sublist in obfs_scores for ent in sublist]
	dist_obf_end = time.time()

	if args.sensitivity >= 3:
		print("frame_processor: Computing scores is not allowed for sensitivity greater than 2. Sending for 2 only!")
	end_enc = time.time()

	if args.verbose:	print("frame_processor: Obfuscating distances = {} ms".format((dist_obf_end-dist_obf_start)*1000))
	if args.verbose:	print("frame_processor: Encryption time: {} ms".format((end_enc-start_enc)*1000))
	if args.verbose:	print("frame_processor: Time(plate_recog + scores_comp + scores_obfs) for {} suspects: {} ms"\
		.format(server_plates_count, (end_enc-recog_start_time)*1000))

	results_file = open("camera_results.txt","a+")
	results_file.write("Online:M= {} CPUs_camera= {} plate_recog= {} dist_comp= {} dist_obf= {} enc_time= {} total_time= {} sensitivity= {} onl_comm= {}\n"\
		.format(server_plates_count,args.cpus,(recog_end_time-recog_start_time)*1000,(dist_comp_end-dist_comp_start)*1000,(dist_obf_end-dist_obf_start)*1000,(end_enc-start_enc)*1000,(end_enc-recog_start_time)*1000,args.sensitivity,len(encrypted_scores)*128*1.00/1024))
	results_file.close()

	D = pickle.dumps(obfs_scores)
	sendScores(sock, D)
	print("frame_processor: The encrypted scores have been sent to the server")
	data = sock.recv(11)
	if (data == "GET image  "):
		# sending the car's image
		image = pickle.dumps(frame)
		send_msg(sock, image)
		print("frame_processor: Car plate detected! Image has been sent")
		end_rtt_time = time.time()
		if args.verbose:	print("frame_processor: Suspect detected: total rtt: {} ms".format((end_rtt_time-recog_start_time)*1000))
		
		results_file = open("camera_results.txt","a+")
		results_file.write("Online:RTT= {}\n".format(end_rtt_time-recog_start_time))
		results_file.close()

def precompute_extended_DB():	# TODO to parallelize
	start_gen_ext_DB = time.time()
	DB = np.load(DB_file)
	plates_count = len(DB)
	if args.verbose:	print("precompute_extended_DB: Number of plates in the server's list: {}".format(plates_count))
	if args.verbose:	print("precompute_extended_DB: Generating the extended DB...")
	global ext_DB
	if args.sensitivity == 0:
		for server_plate in range(plates_count):
			db_element = DB[server_plate][0]
			for i in range(1, 8):
				db_element = ec_elgamal.add2(db_element, DB[server_plate][i])
			ext_DB.append(db_element)
	if args.sensitivity == 1:
		for excluded_position in range(8):
			starting_position = 0 if excluded_position != 0 else 1
			for server_plate in range(plates_count):
				db_element = DB[server_plate][starting_position]
				for i in [x for x in range(1, 8) if x != excluded_position]:
					db_element = ec_elgamal.add2(db_element, DB[server_plate][i])
				ext_DB.append(db_element)
	elif args.sensitivity == 2:
		excluded_positions_range = [(f,s) for f in range(8) for s in range(f, 8) if f != s]
		for excluded_2_positions in excluded_positions_range:
			starting_position = 0 if 0 not in excluded_2_positions else 1 if 1 not in excluded_2_positions else 2
			for server_plate in range(plates_count):
				db_element = DB[server_plate][starting_position]
				for i in [x for x in range(1, 8) if x not in excluded_2_positions]:
					db_element = ec_elgamal.add2(db_element, DB[server_plate][i])
				ext_DB.append(db_element)
	np.save(ext_DB_file, ext_DB)
	del ext_DB
	end_gen_ext_DB = time.time()
	if args.verbose:	print("precompute_extended_DB: extended DB generated in: {} ms".format((end_gen_ext_DB-start_gen_ext_DB)*1000))
	results_file = open("camera_results.txt","a+")
	storage = 128*plates_count if args.sensitivity == 0 else 128*plates_count*8 if args.sensitivity == 1 else 128*plates_count*28
	results_file.write("Offile:CPUs_camera= {} ext_DB_gen= {} ext_DB_size= {}\n".format(1,(end_gen_ext_DB-start_gen_ext_DB)*1000,storage*1.0/1024))
	results_file.close()

def process_plates(list):	# sublist of [0..server_plates_count]
	encrypted_scores = []
	if args.sensitivity == 0:
		enc_plate = Y[int(encoded_plate[0:2])][0]	#enc_plate=Enc(q1q2..q8)
		for i in range(1, 8):
			enc_plate = ec_elgamal.add2(enc_plate, Y[int(encoded_plate[i*2:i*2+2])][i])
		for server_plate in list:
			encrypted_scores.append(ec_elgamal.add2(enc_plate, ext_DB[server_plate]))
	elif args.sensitivity == 1:
		for excluded_position in range(8):
			starting_position = 0 if excluded_position != 0 else 1
			enc_plate = Y[int(encoded_plate[starting_position*2:starting_position*2+2])][starting_position]
			for i in [x for x in range(1, 8) if x != excluded_position]:
				enc_plate = ec_elgamal.add2(enc_plate, Y[int(encoded_plate[i*2:i*2+2])][i])
			for server_plate in list:
				encrypted_scores.append(ec_elgamal.add2(enc_plate, ext_DB[excluded_position*server_plates_count+server_plate]))
	elif args.sensitivity == 2:
		excluded_positions_range = [(f,s) for f in range(8) for s in range(f, 8) if f != s]
		for index, excluded_2_positions in enumerate(excluded_positions_range):
			starting_position = 0 if 0 not in excluded_2_positions else 1 if 1 not in excluded_2_positions else 2
			enc_plate = Y[int(encoded_plate[starting_position*2:starting_position*2+2])][starting_position]
			for i in [x for x in range(1, 8) if x not in excluded_2_positions]:
				enc_plate = ec_elgamal.add2(enc_plate, Y[int(encoded_plate[i*2:i*2+2])][i])
			for server_plate in list:
				encrypted_scores.append(ec_elgamal.add2(enc_plate, ext_DB[index*server_plates_count+server_plate]))
	return encrypted_scores

def obfuscate_scores(list):
	return [ec_elgamal.mult(str(random.getrandbits(rand_nbrs_bitlen)), score) for score in list]

if __name__ == '__main__':
	sock = connect_to_server()
	if not args.load:
		# Offline phase_______________________________________
		get_pub_key(sock)
		if args.verbose:	print("main: pub_key received and saved in {}".format(pub_key_file))
		get_DB_file(sock)
		if args.verbose:	print("main: Encrypted DB received and saved in {}".format(DB_file))
		generate_local_files()
		if args.verbose:	print("main: Local files have been generated")
		precompute_extended_DB()
		if args.verbose:	print("main: Extended DB has been generated")

	# Online phase____________________________________________
	ec_elgamal.prepare_for_enc(pub_key_file)
	DB = np.load(DB_file)
	Y = np.load(str(Y_file+".npy"))
	ext_DB = np.load(str(ext_DB_file+".npy"))
	plates_count = len(DB)

	if args.pi_camera:
		#TODO need to implement using detected plates, mutex... like in BlindGuardian
		from picamera.array import PiRGBArray
		from picamera import PiCamera
		camera = PiCamera()
		camera.resolution = (args.width, args.height)
		camera.framerate = 5
		time.sleep(0.1)
		rawCapture = PiRGBArray(camera, size=(args.width, args.height))
		for lframe in camera.capture_continuous(rawCapture, format="bgr", use_video_port=True):
			frame = lframe.array
			# ret, enc = cv2.imencode("*.bmp", frame)
			rawCapture.truncate(0)
			frame_processor(frame)
			if cv2.waitKey(1) & 0xFF == ord('q'):
				break

	elif args.one_image != "":
		frame = cv2.imread(args.one_image)
		if frame is None:
			raise Exception("main: Unable to load image: {}".format(args.one_image))
		# = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
		print("main: Processing image: {}".format(args.one_image)) #TODO to remove
		frame_processor(frame)

	else:	#from PC captureDevice(0 or 1)
		video_source = args.video if args.video != "" else args.capture_device	#read video from file or webcam
		video_capture = cv2.VideoCapture(video_source)
		video_capture.set(3, args.width)
		video_capture.set(4, args.height)
		for ret, frame in video_capture.read():
			# ret, enc = cv2.imencode("*.bmp", frame)
			frame_processor(frame)
			if cv2.waitKey(1) & 0xFF == ord('q'):
				break

	sys.exit(0)