# BlindCarSeeker
Privacy-preserving car license-plates matcher

## Installation
Requires [OpenAlpr](http://doc.openalpr.com/api.html#commercial-sdk)
```bash
swig -python ec_elgamal.i
gcc -c ec_elgamal.c ec_elgamal_wrap.c -lcrypto -I/usr/include/python2.7 -fPIC
gcc -shared ec_elgamal.o ec_elgamal_wrap.o -lcrypto -o _ec_elgamal.so
python setup.py build_ext --inplace

# for testing:
python
```
```python
import ec_elgamal
ec_elgamal.test()
quit()
```
## Usage
Server:
```bash
./server.py --cars_file cars/1500plates --verbose --cpus 16 --server_ip 10.40.21.38 --server_port 1234 [--load]
./server.py -h # for help
```
Camera:
```bash
./camera.py --one_image 6.jpg --cpus 4 --sensitivity 0 --verbose --server_ip 10.40.21.38 --server_port 1234 [--load]
./client.py -h # for help
```
