#!/usr/bin/env python
from openalpr import Alpr
import time
import argparse
import pickle
import numpy as np
import socket
import ec_elgamal
import os
import struct
import datetime
import cv2
from multiprocessing import Pool

parser = argparse.ArgumentParser()
parser.add_argument('--cars_file',		type=str,	default="",		help="Path to file containing list of cars' plates."	)
parser.add_argument('--cars_folder',	type=str,	default="",		help="Path to folder containing pictures of cars."		)
parser.add_argument('--img_dim',		type=int,	default=96,		help="Default image dimension."							)
parser.add_argument('--server_port',	type=int,	default=6546,	help="Port of the server."								)
parser.add_argument('--server_ip',		type=str,	default='127.0.0.1',	help="IP of the server."						)
parser.add_argument('--cpus',			type=int,	default=16,		help="Number of parallel CPUs to be used."				)
parser.add_argument('--generate_keys',	action='store_true', 		help="Generate new server keys."						)
parser.add_argument('--verbose',		action='store_true', 		help="Output more details."								)
parser.add_argument('--load', 			action='store_true', 		help="Load from stored encrypted DB."					)
args = parser.parse_args()

pub_key_file	= "ec_pub.txt"
priv_key_file	= "ec_priv.txt"
plate_size		= 8					# max number of chars in the plate
DB_file 		= 'DB.data'

def send_pub_key(connection):
	f = open(pub_key_file, 'r')
	send_msg(connection, f.read())
	f.close()
	if args.verbose:	print("sendPubKey: Public key sent")

def send_enc_DB(connection):
	f = open(str(DB_file+".npy"), "rb")
	send_msg(connection, f.read())
	f.close()
	if args.verbose:	print("sendDBfiles: Encrypted DB sent")

def wait_for_clients():
	sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	server_address = (args.server_ip, args.server_port)
	sock.bind(server_address)
	sock.listen(10)
	while True:
		# Wait for a connection
		print("waitForClients: Waiting for a connection...")
		connection, client_address = sock.accept()
		try:
			while True:
				data = recv_all(connection, 11)
				print("waitForClients: Received: {}".format(data))
				if data:
					if (data == "GET pub_key"):	send_pub_key(connection)
					if (data == "GET DBfiles"):	send_enc_DB(connection)
					if (data == "new_scores "):	get_scores(connection)
				else:
					print("waitForClients: No more data from client {}".format(client_address))
					break
		finally:
			connection.close()
			print("waitForClients: Connection closed with client {}".format(client_address))

def decrypt_scores(list):
	return [ec_elgamal.dec_zero_nonzero(encrypted_score) for encrypted_score in list]

def get_scores(connection):
	try:
		ec_elgamal.prepare(pub_key_file, priv_key_file)
		data = recv_msg(connection)
		enc_D = pickle.loads(data)

		start_dec = time.time()
		if (len(enc_D) > args.cpus*10):
			pool = Pool(processes=args.cpus)
			D = pool.map(decrypt_scores, (enc_D[int(i*len(enc_D)/args.cpus):int((i+1)*len(enc_D)/args.cpus)] for i in range(args.cpus)))
			D = [ent for sublist in D for ent in sublist]
		else:
			D = [ec_elgamal.dec_zero_nonzero(encrypted_score) for encrypted_score in enc_D]	#if decrypted_score == 0 return 0, else return 1
		end_dec = time.time()
		if args.verbose:	print("getScores: dec_time of {} ciphertexts: {} ms.".format(len(D), (end_dec-start_dec)*1000))
		# if args.verbose:	print(D)

		results_file = open("server_results.txt", "a+")
		results_file.write("Online:dec_time_of {} ciphertexts: {}\n".format(len(D), (end_dec-start_dec)*1000))
		results_file.close()
		if (0 in D):	# SUSPECT DETECTED!!!
			# detected_id = D.index(0)
			print("getScores: Plate number detected!")
			message = "GET image  "
			connection.sendall(message)
			data = recv_msg(connection)
			now = datetime.datetime.now()
			image_name = "detected-"+str(now.strftime("%Y-%m-%d-%H-%M")+".png")
			frame = pickle.loads(data)
			cv2.imwrite(image_name, frame)
			print("getScores: Detected car image saved in {}".format(image_name))
		else:
			message = "No match   "
			connection.sendall(message)
	except Exception, e:
		print "getScores: Error! "+str(e)

def encode_plate_number(plate_nbr):
	encoded_plate = []
	for char in plate_nbr:
		if char not in ['\n','\t','']:
			encoded_plate.append(str(ord(char)-26))	# max ascii code 126
	for i in range(len(encoded_plate), plate_size):
		encoded_plate.append('99')
	return "".join(encoded_plate)

def generate_DB_files():	#TODO checking
	start_recognition = time.time()
	ec_elgamal.prepare(pub_key_file, priv_key_file)
	plates = []
	if (args.cars_folder != ""):
		alpr = Alpr("us", "/etc/openalpr/openalpr.conf", "/usr/share/openalpr/runtime_data")
		start_recognition = time.time()	# do not include initialization time
		for root, dirs, files in os.walk(args.cars_folder):
			for img in files:
				results = alpr.recognize_file(os.path.join(root, img))
				if results.values()[5] != []:
					plates.append(results.values()[5][0].values()[0]) # get the result with the best confidence
	elif (args.cars_file != "") :
		if not os.path.isfile(args.cars_file):
			print("generate_DB_files: ERROR! File {} does not exist!".format(args.cars_file))
		with open(args.cars_file) as fp:
			for line in fp:
				plates.append(line)
	else :
		print("generate_DB_files: ERROR! No source file/directory specified")
		exit(0)
	if plates == []:
		print("generate_DB_files: No plates have been detected. Exiting...")
		exit(0)
	encoded_plates = [encode_plate_number(plate) for plate in plates]
	end_recognition = time.time()
	if args.verbose:	print("generate_DB_files: Plates generated in {} ms".format((end_recognition-start_recognition)*1000))
	start_enc = time.time()
	if args.verbose:	print("generate_DB_files: Generating encrypted DB...")
	pool = Pool(processes=args.cpus)
	DB = pool.map(encrypt_for_DB, (encoded_plates[int(i*len(encoded_plates)/args.cpus):int((i+1)*len(encoded_plates)/args.cpus)] for i in range(args.cpus)))
	DB = [ent for sublist in DB for ent in sublist]
	end_enc = time.time()
	if args.verbose:	print("generate_DB_files: Encrypted DB generated in: {} ms, nbr of plates: {}".format((end_enc-start_enc)*1000, len(DB)))
	np.save(DB_file, DB)
	del DB
	results_file = open("server_results.txt", "a+")
	results_file.write("Offline:M= {} CPUs_srvr= {} recog= {} DB_gen= {} storage/off_comm= {}\n"\
		.format(len(encoded_plates), args.cpus, (end_recognition-start_recognition)*1000, (end_enc-start_enc)*1000, plate_size*len(encoded_plates)*128*1.00/1024))
	results_file.close()

def encrypt_for_DB(list):
	# list = [[p11p12p13..p1N],[p21p22p23..p2N],..,[pM1pM2pM3..pMN]]
	enc_plates = []
	for plate in list:
		enc_plate = []
		for i in range(0, plate_size*2, 2):
			enc_plate.append(ec_elgamal.encrypt_ec(str(int(plate[i:i+2])*10**i)))
		enc_plates.append(enc_plate)
	return enc_plates
	# enc_plates = [Enc(p11),Enc(p12),..,Enc(p1N),Enc(p21),Enc(p22),..,Enc(p2N),Enc(pM1),Enc(pM2),..,Enc(pMN)]

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

if __name__ == '__main__':
	if args.generate_keys :
		ec_elgamal.generate_keys(pub_key_file, priv_key_file)
	if args.generate_keys or not args.load:
		generate_DB_files()
	wait_for_clients()
