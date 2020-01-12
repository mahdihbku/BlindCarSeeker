#!/usr/bin/env python
from openalpr import Alpr
from picamera.array import PiRGBArray
from picamera import PiCamera
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
from multiprocessing import Pool
from random import randint

parser = argparse.ArgumentParser()
parser.add_argument('--img_dim',		type=int,	default=96,		help="Default image dimension."									)
parser.add_argument('--server_port',	type=int,	default=6546,	help="Port of the server.",										)
parser.add_argument('--server_ip',		type=str,	default='127.0.0.1', help="IP of the server.",									)
parser.add_argument('--cpus',			type=int,	default=4,		help="Number of parallel CPUs to be used.",						)
parser.add_argument('--sensitivity',	type=int,	default=2,		help="Non-matching characters in the plate (0,1,2).",			)
parser.add_argument('--capture_device',	type=int,	default=0,		help='Capture device. 0 for latop webcam and 1 for usb webcam'	)
parser.add_argument('--PiCamera',		action='store_true',		help='Execute client.py from Raspberry Pi.'						)
parser.add_argument('--generate_keys',	action='store_true',		help="Generate new server keys."								)
parser.add_argument('--verbose',		action='store_true',		help="Output more details."										)
parser.add_argument('--load', 			action='store_true',		help="Load from stored encrypted DB."							)
args = parser.parse_args()

elgamal_ct_size = 130
DB_file 		= "rec_DB.data"
pub_key_file 	= "rec_pub.txt"
rand_nbrs_file	= "rand_num.data"
rand_nbrs_min_bitlen = 128
rand_nbrs_max_bitlen = 128

# Temporary global variables
# DB = []
# G = []

def connect_to_server():
	sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	server_address = (server_ip, server_port)
	if verbose:	print("connectToServer: Connecting to {}:{}...".format(server_ip, server_port))
	sock.connect(server_address)
	if verbose:	print("connectToServer: Connected")
	return sock

def get_pub_key(sock):
	try:
		if verbose:	print("getPubKey: Getting the server's key...")
		message = 'GET pub_key'
		sock.sendall(message)
		pub_key = recv_msg(sock)
		f = open(pub_key_file, "w")
		f.write(pub_key)
		f.close()
		if verbose:	print("getPubKey: Key received")
	except:
		print("getPubKey: Error")

def get_DB_file(sock):
	try:
		if verbose:	print("getBCfiles: Getting Encrypted DB...")
		message = "GET DBfiles"
		sock.sendall(message)
		DB = recv_msg(sock)
		f = open(DB_file, 'w')
		f.write(DB)
		f.close()
		if verbose:	print("getBCfiles: Encrypted DB received")
	except:
		print("getBCfiles: Error")

def fill_rand_numbers_file():
	if verbose:	print("fill_rand_numbers_file: Generating the random-numbers file...")
	DB = np.load(DB_file)
	plates_count = len(DB)
	ec_elgamal.prepare_for_enc(pub_key_file)
	f = open(rand_nbrs_file, "wb")
	for i in range(plates_count):
		rand1 = random.getrandbits(randint(rand_nbrs_min_bitlen, rand_nbrs_max_bitlen))
		rand2 = random.getrandbits(randint(rand_nbrs_min_bitlen, rand_nbrs_max_bitlen))
		if (rand1 < rand2):
			rand1, rand2 = rand2, rand1		# always rand1 > rand2
		f.write(str(rand1)+'\n')
		f.write(ec_elgamal.encrypt_ec(str(rand2)))
	f.close()
	if verbose:	print("fill_rand_numbers_file: Random-numbers file generated")

def send_msg(sock, msg):
	msg = struct.pack('>I', len(msg)) + msg
	sock.sendall(msg)

def recv_msg(sock):
	raw_msglen = recvall(sock, 4)
	if not raw_msglen:
		return None
	msglen = struct.unpack('>I', raw_msglen)[0]
	return recvall(sock, msglen)

def recvall(sock, n):
	data = b''
	while len(data) < n:
		packet = sock.recv(n - len(data))
		if not packet:
			return None
		data += packet
	return data

def encrypt_for_G(list):
	return [[ec_elgamal.encrypt_ec(str(g*10**(k*2))) for k in range (8)] for g in list]

def generate_local_files():
	start_gen_G = time.time()
	ec_elgamal.prepare_for_enc(pub_key_file)
	if verbose:	print("generate_local_files: Generating local G...")
	pool = Pool(processes=nbr_of_CPUs)
	G_values = range(100)
	G = pool.map(encrypt_for_G, (G_values[int(i*100/nbr_of_CPUs):int((i+1)*100/nbr_of_CPUs)] for i in range(nbr_of_CPUs)))
	G = [ent for sublist in G for ent in sublist]
	np.save(G_file, G)
	del G
	pool.close()
	end_gen_G = time.time()
	if verbose:	print("generate_local_files: G generated in: {} ms".format((end_gen_G-start_gen_G)*1000))
	# results_file = open("camera_results.txt","a+")
	# storage = ec_elgamal_ct_size*(128*suspects_count*256/G_portion+128*suspects_count+256+suspects_count)+256*suspects_count if G_portion>0 else ec_elgamal_ct_size*(128*suspects_count+128*suspects_count+256+suspects_count)+256*suspects_count
	# storage = storage*1.00/1024/1024
	# results_file.write("Offile:M= {} CPUs_camera= {} F_G_gen= {} G_portion= {} storage((GorC)+B+F+rand)= {}\n".format(suspects_count,nbr_of_CPUs,end_gen_files-start_gen_files,G_portion,storage))
	# results_file.close()

def encode_plate_number(detected_plate):
	encoded_plate = []
	for char in detected_plate:
		if char not in ['\n', '\t']:
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

if __name__ == '__main__':
	sock = connectToServer()
	if not load:
		# Offline phase___________________________________________
		get_pub_key(sock)
		if verbose:	print("main: pub_key received and saved in {}".format(pub_key_file))
		get_DB_file(sock)
		if verbose:	print("main: Encrypted DB received and saved in {}, {}".format(DB_file))
		generate_local_files()
		if verbose:	print("main: Local files have been generated")
		fill_rand_numbers_file()
		if verbose:	print("main: random files file {} has been filled".format(rand_numbers_file))

	# Online phase____________________________________________
	ec_elgamal.prepare_for_enc(pub_key_file)
	DB = np.load(DB_file)
	G = np.load(str(G_file+".npy"))
	plates_count = len(DB)

	#stopped here: -read plate nbr from cli or from camera? -when computing the scores we have to consider the sensitivity. based on it we have to figure out how to compute it!!