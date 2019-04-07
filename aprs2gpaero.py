"""
move aprs data onto glideport.aero

starting from BB's (shell) code, and using that + aprs.fi api as guide.

TODO:
1 this should probably read a config file with the user callsigns : IEMI pairs, maybe other info (aprs.fi api keys, if we use that)
2 not sure how often we can actually read data from aprs.fi - will need to talk to him(?) and see about rates etc (or go to ARPS-IS)
3 add installation instructions - here or in a github md file

NOTE: it's problematic having a canned example here, for two reasons:
1. ultimately we will be pushing to a live website, which i don't want to contaminate.
2. the real packets must have some not so public info - IEMI values.
"""

import os
import time
import socket
import requests
import json
import tempfile
import aprslib


class APRSBase(object):
	
	def __init__(self, ids_to_be_tracked, **kwargs):
		"""
		ids : a dictionary of callsign : IMEI items.
		aprs_api_key : said key for a valid aprs.fi user id
		"""
		self.ids_to_be_tracked = ids_to_be_tracked
		self.N_id_groups = len(self.ids_to_be_tracked.keys()) / 20 + 1
		self.verbose = kwargs.get('verbose', False)
		self.reset(**kwargs)
	
	def reset(self, **kwargs):
		self.locations = []
		self.log_filename = os.path.join(tempfile.gettempdir(), time.strftime('aprs2gpaero_log_%Y_%m_%d_%H_%M_%S.jsons'))
		self.default_wait_between_checks = kwargs.get('wait_between_checks', 1.0)
		self.wait_between_checks = self.default_wait_between_checks
		self.start_time = time.time()
	
	def get_loc(self):
		raise NotImplementedError
	
	def monitor(self):
		"""
		monitor the service every N seconds.
		if failing, increase timeout (and notify user).
		reset when successful.
		abort on ctrl-c
		"""
		while True:
			print 'monitor dt = {:0.1f} sec'.format(time.time() - self.start_time)
			try:
				self.get_loc()
				self.send_locations()
				time.sleep(self.wait_between_checks)
				# reset wait if successful.
				self.wait_between_checks = self.default_wait_between_checks
			except KeyboardInterrupt:
				print 'stopping upon request'
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
		if True or self.verbose:
			print 'sending {:0d} locations'.format(len(self.locations))
		with open(self.log_filename, 'ab') as log_f:
			for entry in self.locations:
				try:
					json_s = json.dumps({'Version' : 2.0,
						'Events' : [{'imei' : self.ids_to_be_tracked[entry['srccall']],
									'timeStamp' : entry['time'],  # maybe status_lasttime, or lasttime - not sure what's better
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
		self.prepare_connection(**kwargs)
	
	def prepare_connection(self, **kwargs):
		self.AIS = aprslib.IS(self.callsign)#, host='noam.aprs2.net', port=14580)
		self.delay_before_check = kwargs.get('delay', 0.5)
		
	def filter_callsigns(self, packet):
		if self.verbose:
			print 'raw packet : ', packet
		if len(packet) == 0:
			return
		try:
			ppac = aprslib.parse(packet)
			if self.verbose:
				print 'parsed :\n', ppac
			# the form below is useful for debuggging, but in reality we need exact matches since we need to translate to IEMI values.
			if any([ppac['from'].startswith(x) for x in self.ids_to_be_tracked.keys()]):
				self.locations.append({'srccall' : ppac['from'],
							'long' : ppac['longitude'],
							'lat' : ppac['latitude'],
							'altitude' : ppac['altitude'],
							'timeStamp' : ppac['timestamp']})
			elif self.verbose:
				print 'from {:}, skip'.format(ppac['from'])
		except Exception as e:
			if self.verbose:
				print 'filter_callsigns failed to parse packet due to %s raw packet *%s*' % (e, packet)
		
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
	
	def close_connection(self):
		print 'closing socket'
		self.raw_socket.close()
		
	def get_loc(self):
		try:
			 data = self.raw_socket.recv(2**14).split('\r\n')
			 for packet in data:
				 self.filter_callsigns(packet)
		except socket.error:
			# we could try closing it, but i'm not sure there's much point - let GC handle that.
			self.prepare_connection()


class APRSFI2GP(APRSBase):
	"""
	get data from aprs.fi, send to gpaero.
	NOTE: very useful for initial coding and personal experimentation, but the legality of using the aprs.fi api beyond that has to be checked on a case by case basis.
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