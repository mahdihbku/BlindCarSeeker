#!/usr/bin/env python
from openalpr import Alpr
import time
import argparse
import pickle
import numpy as np
import socket
import ec_elgamal
from multiprocessing import Pool

parser = argparse.ArgumentParser()
parser.add_argument('--cars_file',		type=str, help="Path to file containing list of cars' plates.",	default=""	)
parser.add_argument('--cars_folder',	type=str, help="Path to folder containing pictures of cars.",	default=""			)
parser.add_argument('--imgDim',			type=int, help="Default image dimension.",						default=96				)
parser.add_argument('--serverPort',		type=int, help="Port of the server.",							default=6546			)
parser.add_argument('--serverIP',		type=str, help="IP of the server.",								default='127.0.0.1'		)
parser.add_argument('--CPUs',			type=int, help="Number of parallel CPUs to be used.",			default=4				)
parser.add_argument('--sensitivity',	type=int, help="Non-matching characters in the plate (0,1,2).",	default=2				)
parser.add_argument('--generateKeys',	action='store_true', help="Generate new server keys."									)
parser.add_argument('--verbose',		action='store_true', help="Output more details."										)
args = parser.parse_args()

server_ip 		= args.serverIP
server_port		= args.serverPort
nbr_of_CPUs		= args.CPUs
verbose			= args.verbose
cars_file		= args.cars_file
cars_folder		= args.cars_folder
sensitivity 	= args.sensitivity
pub_key_file	= "ec_pub.txt"
priv_key_file	= "ec_priv.txt"

def send_pub_key(connection):
	f = open(pub_key_file, 'r')
	pub_key = f.read()
	send_msg(connection, pub_key)
	if verbose:	print("sendPubKey: Public key sent")
	f.close()

def send_DB_files(connection):
	f = open(str(B_file+".npy"), "rb")
	B = f.read()
	send_msg(connection, B)
	if verbose:	print("sendDBfiles: B sent")
	f.close()
	f = open(str(C_file+".npy"), "rb")
	C = f.read()
	send_msg(connection, C)
	if verbose:	print("sendDBfiles: C sent")
	f.close()

def wait_for_clients():
	sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	server_address = (server_ip, server_port)
	sock.bind(server_address)
	sock.listen(10)
	while True:
		# Wait for a connection
		print("waitForClients: Waiting for a connection...")
		connection, client_address = sock.accept()
		try:
			while True:
				data = recvall(connection, 11)
				print("waitForClients: Received: {}".format(data))
				if data:
					if (data == "GET pub_key"):
						send_pub_key(connection)
					if (data == "GET DBfiles"):
						send_DB_files(connection)
					if (data == "new_scores "):
						get_scores(connection)
				else:
					print("waitForClients: No more data from client {}".format(client_address))
					break
		finally:
			connection.close()
			print("waitForClients: Connection closed with client {}".format(client_address))

def get_scores(connection):
	try:
		ec_elgamal.prepare(pub_key_file, priv_key_file)
		data = recv_msg(connection)
		enc_D = pickle.loads(data)

		start_dec = time.time()
		D = [ec_elgamal.dec_zero_nonzero(encrypted_score) for encrypted_score in enc_D]	#if decrypted_score == 0 return 0, else return 1
		end_dec = time.time()
		if verbose:	print("getScores: dec_time for {} suspects: {} ms.".format(len(D), (end_dec-start_dec)*1000))
		if verbose:	print(D)

		results_file = open("final_results.txt", "a+")
		results_file.write("Online:dec_time= {}\n".format((end_dec-start_dec)*1000))
		results_file.close()
		## stopped here......................................
		# i=0
		# while (i<len(D) and len(D[i])<200):		# TODO: uncomment !!
		# 	i+=1									# TODO: uncomment !!
		if (0 in D):	# SUSPECT DETECTED!!!
			print("getScores: SUSPECT DETECTED! id={} name={}".format(i, suspects_names[i]))
			message = "GET image  "
			connection.sendall(message)
			data = recv_msg(connection)
			now = datetime.datetime.now()
			image_name = "suspect"+str(now.strftime("%Y-%m-%d-%H-%M")+".png")
			frame = pickle.loads(data)
			cv2.imwrite(image_name, frame)
			print("getScores: Suspect's image saved in {}".format(image_name))
		else:
			message = "No match"
			connection.sendall(message)
	except:
		print 'getScores: Error'

def encode_plate_number(detected_plate):
	# stopped here: in: unicode u'786P0J', out: encoded plate number (ascii-26 of each char)

def generate_DB_files():
	start_norm = time.time()
	ec_elgamal.prepare(pub_key_file, priv_key_file)
	if (cars_folder != ""):
		for root, dirs, files in os.walk(args.suspectsDir):
			for img in files:
				alpr = Alpr("us", "/etc/openalpr/openalpr.conf", "/usr/share/openalpr/runtime_data")
				results = alpr.recognize_file(img)
	else if (cars_file != "") :

	else :
		print("generate_DB_files: ERROR! No source file/directory specified")

	suspects_reps = []
	suspects_names[:] = []
	if verbose:	print("generate_DB_files: Detecting and normalizing faces...")
	for root, dirs, files in os.walk(args.suspectsDir):
		for img in files:
			imgrep = getRep(os.path.join(root, img))
			if imgrep == '': continue
			suspects_reps.append(normalizeRep(imgrep))
			suspects_names.append(os.path.join(root, img))
	end_norm = time.time()
	if verbose:	print("generate_DB_files: Suspects in dir {} have been normalized in {}".format(args.suspectsDir, (end_norm-start_norm)*1000))

	start_enc = time.time()
	if verbose:	print("generate_DB_files: Generating matrix B...")
	pool = Pool(processes=nbr_of_CPUs)
	B = pool.map(encryptForB, (suspects_reps[int(i*len(suspects_reps)/nbr_of_CPUs):int((i+1)*len(suspects_reps)/nbr_of_CPUs)] for i in range(nbr_of_CPUs)))
	B = [ent for sublist in B for ent in sublist]
	if verbose:	print("generate_DB_files: B generated")
	if verbose:	print("generate_DB_files: Generating matrix C...")
	C = pool.map(encryptForC, (suspects_reps[int(i*len(suspects_reps)/nbr_of_CPUs):int((i+1)*len(suspects_reps)/nbr_of_CPUs)] for i in range(nbr_of_CPUs)))
	pool.close()
	C = [ent for sublist in C for ent in sublist]
	if verbose:	print("generate_DB_files: C generated")
	end_enc = time.time()
	print("generate_DB_files: DB files generated in: {} ms.".format((end_enc-start_enc)*1000))

	results_file = open("final_results.txt", "a+")
	results_file.write("Offline:M= {} CPUs_srvr= {} ident+norm= {} BCgen= {} storage(B+C+keys)= {} off_comm= {} onl_comm= {}\n".format(len(suspects_reps), nbr_of_CPUs, end_norm-start_norm, end_enc-start_enc, 2*len(suspects_reps)*128*512*1.00/1024/1024, 2*len(suspects_reps)*128*512*1.00/1024/1024, len(suspects_reps)*512*1.00/1024))
	results_file.close()

	np.save(B_file, B)
	np.save(C_file, C)

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

if __name__ == '__main__':
	if args.generateKeys :
		ec_elgamal.generate_keys(pub_key_file, priv_key_file)
	generate_DB_files()
	wait_for_clients()