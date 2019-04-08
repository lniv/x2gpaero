#!/usr/bin/python
"""
move aprs data onto glideport.aero

starting from BB's (shell) code, and using that + aprs.fi api as guide.

TODO:
1 if using aprs.fi (not default), not sure how often we can actually read data from aprs.fi - will need to talk to him(?) and see about rates etc (or go to ARPS-IS)
2 add installation instructions - here or in a github md file

NOTE: it's problematic having a canned example here, for two reasons:
1. ultimately we will be pushing to a live website, which i don't want to contaminate.
2. the real packets must have some not so public info - IMEI values.
"""

import os
import time
import socket
import requests
import json
import tempfile
import argparse
import aprslib

_DEBUG = True

_USABLE_KEYWORDS = ['verbose', 'wait_between_checks', 'delay']

def config_file_reader(filename):
	"""
	read a simple config file
	i'd prefer to keep to json, as we're using it for other things
	"""
	with open(filename, 'rb') as f:
		config = json.load(f)
	return config
	

class APRSBase(object):
	
	def __init__(self, ids_to_be_tracked, **kwargs):
		"""
		ids : a dictionary of callsign : IMEI items.
		aprs_api_key : said key for a valid aprs.fi user id
		"""
		self.ids_to_be_tracked = ids_to_be_tracked
		print 'Will track'
		for aprs_id, IMEI in self.ids_to_be_tracked.items():
			print '{:} : {:}'.format(aprs_id, IMEI) 
		self.N_id_groups = len(self.ids_to_be_tracked.keys()) / 20 + 1
		self.verbose = kwargs.get('verbose', False)
		self.reset(**kwargs)
	
	def reset(self, **kwargs):
		# monitor will reassert thes, but just in case
		self.start_time = 0
		self.last_print = 0
		
		self.locations = []
		self.log_filename = os.path.join(tempfile.gettempdir(), time.strftime('aprs2gpaero_log_%Y_%m_%d_%H_%M_%S.jsons'))
		print 'Logging to ', self.log_filename
		self.default_wait_between_checks = kwargs.get('wait_between_checks', 1.0)
		self.wait_between_checks = self.default_wait_between_checks
	
	def get_loc(self):
		raise NotImplementedError
	
	def cleanup(self):
		"""
		any actions deemed prudent when stopping monitoring
		"""
		pass
	
	def monitor(self):
		"""
		monitor the service every N seconds.
		if failing, increase timeout (and notify user).
		reset when successful.
		abort on ctrl-c
		"""
		
		self.start_time = time.time()
		self.last_print = self.start_time
		while True:
			now = time.time()
			# usually i would employ nan, but i don't want to force numpy.
			if now - self.last_print > getattr(self, 'print_monitor_every_x_seconds', 2**64 -1):
				self.last_print = now
				print 'monitor dt = {:0.1f} sec'.format(time.time() - self.start_time)
			try:
				self.get_loc()
				self.send_locations()
				time.sleep(self.wait_between_checks)
				# reset wait if successful.
				self.wait_between_checks = self.default_wait_between_checks
			except KeyboardInterrupt:
				print 'stopping upon request'
				self.cleanup()
				break
			except Exception as e:
				print 'Problem monitoring due to {:}, increasing wait time by x2'.format(e)
				self.wait_between_checks *= 2
	
	def upload_packet_to_gpaero(self, json_s):
		"""
		not implemented yet; will do so later.
		for now, just print it
		"""
		print 'would have uploaded ', json_s
	
	def send_locations(self):
		"""
		take locations
		convert ids to IMEI
		create json for uploading to gpaero
		save json to local log file
		send to gpaero.
		clear the locations once uploaded
		
		sample json file : 
		{"Version": "2.0", "Events": [{
		"imei": "VK6FLYR",
		"timeStamp": 1554359951000,
		"point": {
			"latitude": -32.067333,
			"longitude": 115.827333,
			"altitude": 23.1648
			}
			}
		]
		}


		"""
		if (_DEBUG or self.verbose) and len(self.locations) > 0:
			print 'sending {:0d} locations'.format(len(self.locations))
		with open(self.log_filename, 'ab') as log_f:
			for entry in self.locations:
				try:
					json_s = json.dumps({'Version' : 2.0,
						'Events' : [{'imei' : self.ids_to_be_tracked[entry['srccall']],
									'timeStamp' : int( 1000 * entry['time']),  #  seems BB's code converts to integer in msec, so copying that.
									'point' : {'latitude' : entry['lat'], 'longitude' : entry['lng'], 'altitude' : entry['altitude']},},]
						})
					log_f.write(json_s + '\n')
					self.upload_packet_to_gpaero(json_s)
				except Exception as e:
					print 'failed due to ', e, ' raw:\n', entry
		self.locations = []
		

class APRSIS2GP(APRSBase):
	"""
	get the aprs packets directly from aprs-is
	"""
	
	def __init__(self, ids_to_be_tracked, callsign, **kwargs):
		"""
		ids : a dictionary of callsign : IMEI items.
		aprs_api_key : said key for a valid aprs.fi user id
		"""
		super(APRSIS2GP, self).__init__(ids_to_be_tracked, **kwargs)
		self.callsign = callsign
		print 'Using callsign ', callsign
		self.prepare_connection(**kwargs)
	
	def prepare_connection(self, **kwargs):
		self.AIS = aprslib.IS(self.callsign)#, host='noam.aprs2.net', port=14580)
		self.delay_before_check = kwargs.get('delay', 0.5)
		
	def filter_callsigns(self, packet, packet_i = -1):
		if self.verbose:
			print 'raw packet : ', packet
		if len(packet) == 0:
			return
		try:
			ppac = aprslib.parse(packet)
			if _DEBUG:
				with open(os.path.join(tempfile.gettempdir(), 'aprs2gpaero_all_packet.log'), 'a') as f:
					# termination chosen so that i can use the file for debugging 
					f.write(packet+'\r\n')
			if self.verbose:
				print 'parsed :\n', ppac
			# the form below is useful for debuggging, but in reality we need exact matches since we need to translate to IMEI values.
			if any([ppac['from'].startswith(x) for x in self.ids_to_be_tracked.keys()]):
				print 'Adding packet : ', ppac
				self.locations.append({'srccall' : ppac['from'],
							'lng' : ppac['longitude'],
							'lat' : ppac['latitude'],
							'altitude' : ppac.get('altitude', 0),  # exception, mostly for debugging, but i'm willing to accept trackers configured without altitude.
							'time' : time.time()})  # note that packets don't have time stamps - aprs.fi adds them on the receiver side, so we have to do the same.
				if _DEBUG:
					print 'after adding\n', self.locations
			elif self.verbose:
				print 'from {:}, skip'.format(ppac['from'])
		except Exception as e: #(aprslib.UnknownFormat, aprslib.ParseError:) as e:
			if self.verbose:
				print 'filter_callsigns - i = {:0d} failed due to %s raw packet *%s*' % (packet_i, e, packet)
		
	def get_loc(self):
		self.AIS.connect()
		# necessary
		time.sleep(self.delay_before_check)
		print 'connected'
		self.AIS.consumer(self.filter_callsigns, raw=True, blocking=False)
		print 'found\n', self.locations
		self.AIS.close()
		print 'closed'
		

class APRSIS2GPRAW(APRSIS2GP):
	"""
	get the aprs packets directly from aprs-is, using raw sockets and the general port.
	this is ugly and lousy, but for some reason i'm having issues connecting to the 14580 port.
	the warnings about the traffic flooding the isp are a bit funny though, straight out of a 2400 baud era (if you were rich).
	we're going to just take all of the data, and filter it by callsigns.
	i'm testing this on a reasonably modern i7 laptop, but i really can't imagine that parsing ~100 mesages / sec (what i get in testing) is an issue on any reasonable hw these days.
	"""
	
	version = 0.01
	
	def __init__(self, ids_to_be_tracked, callsign, addr = '45.63.21.153', port = 10152, **kwargs):
		"""
		ids_to_be_tracked : a dictionary of callsign : IMEI items.
		callsign : for logging into the APRS-IS server; but note that no password is used or needed since we're reading only, so it really could be anything valid.
		"""
		self.addr = addr
		self.port = port
		self._buffer = ''
		if _DEBUG:
			self._total_N_packets = 0
		super(APRSIS2GPRAW, self).__init__(ids_to_be_tracked, callsign, **kwargs)
		
	def prepare_connection(self, **kwargs):
		self.raw_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		self.raw_socket.connect((self.addr, self.port))
		self.raw_socket.setblocking(True)
		self.raw_socket.settimeout(2)
		time.sleep(0.1)
		print 'server greeting : ', self.raw_socket.recv(10000)
		time.sleep(0.1)
		self.raw_socket.sendall(b'user {:} pass -1 vers {:} {:}\n\r'.format(self.callsign, self.__class__.__name__, self.version))
		print 'ack : ', self.raw_socket.recv(10000).split('\r\n')[0]
		self.raw_socket.setblocking(False)
	
	def cleanup(self, **kwargs):
		self.close_connection()
	
	def close_connection(self):
		print 'closing socket'
		self.raw_socket.close()
		
	def get_loc(self):
		try:
			pre_data = (self._buffer + self.raw_socket.recv(2**14)).split('\r\n')
			# if last line is an exact packet, this wil shift its processing one cycle later; seems acceptable.
			self._buffer = pre_data[-1]
			data = pre_data[:-1]
			if _DEBUG:
				now = time.time()
				self._total_N_packets += len(data)
				if now - self.last_print > getattr(self, 'print_info_every_x_seconds', 1):
					self.last_print = now
					print 'dt = {:0.1f} sec, N_packets {:0d}, mean rate {:0.2f} packets / sec'.format(now - self.start_time, len(data), self._total_N_packets / (time.time() - self.start_time))
			for packet_i, packet in enumerate(data):
				self.filter_callsigns(packet, packet_i = packet_i)
			if len(data) < 2: # 1?
				print 'got too little data N = {:0d}, resetting socket'.format(len(data))
				self.close_connection()
				time.sleep(0.5)
				self.prepare_connection()
		except socket.error:
			print 'Socket exception, resetting connection'
			# we could try closing it, but i'm not sure there's much point - let GC handle that.
			self.prepare_connection()
			

class APRSIS2GPRAWDEBUG(APRSIS2GPRAW):
	"""
	read data from a file in order to debug stuff.
	file is one that was recorded in aprs2gpaero_all_packet.log
	not meant to be too flexible.
	"""
	
	class FakeSocket(object):
		
		def __init__(self):
			self.f = open(os.path.join(tempfile.gettempdir(), 'aprs2gpaero_all_packet.log'), 'r')
			
		def close(self):
			self.f.close()
			
		def recv(self, N, **kwargs):
			return self.f.read(N)
	
	def prepare_connection(self, **kwargs):
		self.raw_socket = self.FakeSocket()
	
	


class APRSFI2GP(APRSBase):
	"""
	get data from aprs.fi, send to gpaero.
	NOTE: very useful for initial coding and personal experimentation, but the legality of using the aprs.fi api beyond that has to be checked on a case by case basis.
	However, i've ended up forcing other sources to the slightly odd dictionary keys e.g. lng ; too bad.
	"""
	
	def __init__(self, ids_to_be_tracked, aprs_api_key, **kwargs):
		"""
		ids : a dictionary of callsign : IMEI items.
		aprs_api_key : said key for a valid aprs.fi user id
		"""
		super(APRSFI2GP, self).__init__(ids_to_be_tracked, **kwargs)
		self.aprs_api_key = aprs_api_key
	
	def get_loc(self):
		"""
		get locations for all callsigns
		"""
		
		# NOTE : must split to 20's per aprs api.
		for group_i in range(self.N_id_groups):
			try:
				callsign_group = ','.join(self.ids_to_be_tracked.keys()[group_i : group_i + 20])
				print callsign_group
				res = requests.get('https://api.aprs.fi/api/get?name={:}&what=loc&apikey={:}&format=json'.format(callsign_group, self.aprs_api_key))
				print res.url
				res.raise_for_status()
				print 'got\n', res.json()
				self.locations.extend(res.json()['entries'])
			except Exception as e:
				print 'failed due to ', e
				

if __name__ == '__main__':
	parser = argparse.ArgumentParser(description= '''
send aprs location packets for specific users to gpaero
command line execution uses local filtering from full APRS-IS feed
other options available in module.
''', formatter_class= argparse.RawTextHelpFormatter)
	parser.add_argument('config', type = str, default = '',
			help= '''
json config file - must have 
callsign - string
ids - a dictionary of 'from' aprs packet : IMEI identifiers
optional {:}'''.format(_USABLE_KEYWORDS))
	args = parser.parse_args()
	
	config = config_file_reader(args.config)
	ids_to_be_tracked = config.pop('ids')
	callsign = config.pop('callsign')
	
	c = APRSIS2GPRAW(ids_to_be_tracked, callsign, **config)
	c.monitor()
