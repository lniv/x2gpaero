#!/usr/bin/python3
"""
move aprs data onto glideport.aero

starting from BB's (shell) code, and using that + aprs.fi api as guide.

TODO:
1 if using aprs.fi (not default), not sure how often we can actually read data from aprs.fi - will need to talk to him(?) and see about rates etc (or go to ARPS-IS)
2. match the callsign, with or without dashes? not clear that it's worth it; ultimately one should know what he's transmitting.

NOTE: it's problematic having a canned example here, for two reasons:
1. ultimately we will be pushing to a live website, which i don't want to contaminate.
2. the real packets must have some not so public info - IMEI values.
"""

# TODO : change the overall average to some sort of box filter to give a better idea of real time conditions; maybe also keep the overall average.
# since timing is unpredictable, running a filter is hard, but keeping a fifo with the last few numbers of packets and the time stamps should allow us to do this easily (though it's a bit more expensive computation wise.

from __future__ import print_function

import os
import time
import logging
import socket
import requests
import json
import tempfile
from collections import deque
import argparse
import aprslib

_DEBUG = False
_LOG_ALL = False
_UPLOAD = False # set to False for debugging, so it doesn't actually interact with glideport.aero, but one can see what would have been uploaded etc

_USABLE_KEYWORDS = ['verbose', 'wait_between_checks', 'max_wait_between_checks', 'max_consecutive_data_loss', 'socket_timeout', 'print_info_every_x_seconds', 'print_stats_every_x_seconds', 'print_monitor_every_x_seconds', 'min_packet_dt', 'N_last_packets', 'socket_timeout', 'delay']

def config_file_reader(filename):
	"""
	read a simple config file
	i'd prefer to keep to json, as we're using it for other things
	"""
	with open(filename, 'r') as f:
		config = json.load(f)
	return config


class APRSBase(object):
	
	def __init__(self, ids_to_be_tracked, **kwargs):
		"""
		ids : a dictionary of callsign : IMEI items.
		"""
		self.ids_to_be_tracked = ids_to_be_tracked
		self.N_id_groups = len(self.ids_to_be_tracked.keys()) / 20 + 1
		self.verbose = kwargs.get('verbose', False)
		self.print_stats_every_x_seconds = kwargs.get('print_stats_every_x_seconds', 600.0)
		self.print_monitor_every_x_seconds = kwargs.get('print_monitor_every_x_seconds', 2**64 -1)
		self.max_wait_between_checks = kwargs.get('max_wait_between_checks', 1800.0)
		self.reset(**kwargs)
		logging.info('kwargs = {:}'.format(kwargs))
		for aprs_id, IMEI in self.ids_to_be_tracked.items():
			logging.info('Tracking {:} : {:}'.format(aprs_id, IMEI))
		
	
	def reset(self, **kwargs):
		# monitor will reassert thes, but just in case
		self.start_time = 0
		self.last_print = 0
		self.last_stats_print = 0
		
		self.locations = []
		self.log_filename = os.path.join(tempfile.gettempdir(), time.strftime('{:}_log_%Y_%m_%d_%H_%M_%S.jsons'.format(self.__class__.__name__)))
		logging.basicConfig(filename= self.log_filename,
							level= logging.DEBUG if _DEBUG else logging.INFO,
							format='%(asctime)s %(levelname)-8s %(message)s',
							datefmt='%Y_%m_%d_%H_%M_%S')
		logging.getLogger().addHandler(logging.StreamHandler())
		logging.info('Logging to ' + self.log_filename)
		
		self.default_wait_between_checks = kwargs.get('wait_between_checks', 1.0)
		self.wait_between_checks = self.default_wait_between_checks
		self.recent_packets = {k : deque([], maxlen = kwargs.get('N_last_packets', 5)) for k in self.ids_to_be_tracked}
		# accept new packet only after min_packet_dt seconds since last valid one.
		self.min_packet_dt = kwargs.get('min_packet_dt', 10.0)
		self.last_packet_time = {k : 0.0 for k in self.ids_to_be_tracked}
		self.packet_stats = {k : {'good' : 0, 'rate_limit' : 0, 'duplicate' : 0} for k in self.ids_to_be_tracked}
	
	def get_loc(self):
		raise NotImplementedError

	def log_stats(self):
		'''
		pretty print some overall statistics
		'''
		logging.info('packet stats : %s' % self.packet_stats)

	def cleanup(self, **kwargs):
		"""
		any actions deemed prudent when stopping monitoring
		"""
		self.log_stats()
	
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
			try:
				self.get_loc()
				self.send_locations()
				time.sleep(self.wait_between_checks)
				# reset wait if successful.
				self.wait_between_checks = self.default_wait_between_checks
			except KeyboardInterrupt:
				logging.info('stopping upon request')
				logging.info('Logged to ' + self.log_filename)
				self.cleanup()
				break
			except Exception as e:
				if self.wait_between_checks > self.max_wait_between_checks:
					# NOTE: might be better to terminate here, and e.g. let a cron job restart us?
					self.wait_between_checks = self.max_wait_between_checks
					logging.warning('Problem monitoring due to {:}, wait time capped at {:} sec'.format(e, self.max_wait_between_checks))
				else:
					self.wait_between_checks *= 2
					logging.warning('Problem monitoring due to {:}, increasing wait time by x2 to {:0.1f} sec'.format(e, self.wait_between_checks))
			# logging various stats etc, catch everything
			try:
				now = time.time() # some time has passed, best get a correct time stamp
				if now - self.last_stats_print > self.print_stats_every_x_seconds:
					self.last_stats_print = now
					self.log_stats()
				if now - self.last_print > self.print_monitor_every_x_seconds:
					self.last_print = now
					logging.info('monitor dt = {:0.1f} sec'.format(time.time() - self.start_time))
			except Exception as e:
				logging.error('Failed to log misc info due to %s', e)
	
	def upload_packet_to_gpaero(self, json_dict):
		"""
		Uses the push method
		there are other methods meant for higher frequency fixes - GlideTrak protocol.
		i may branch these later to use those, or refactor the code a bit, or not bother - i suspect that as long as we're closer to a spot / inreach in terms of fix frequency, it all works well.
		"""
		if not _UPLOAD:
			logging.info('would upload, but skipping {:}'.format(json_dict))
			return
		
		logging.info('Uploading {:}'.format(json_dict))
		# from BB's code
		#curl -H "Accept: application/json" -H "Content-Type: application/json" -d @json_file http://glideport.aero/spot/ir_push.php
		# Note that the user has to have added  ir_push:IMEI (With the/ a(?) correct IMEI)
		
		r = requests.post('http://glideport.aero/spot/ir_push.php', json=json_dict)
		r.raise_for_status()
		logging.info('Received {:}'.format(r.text))
	
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
			logging.debug('sending {:0d} locations'.format(len(self.locations)))
		
		for entry in self.locations:
			try:
				json_dict = {'Version' : 2.0,
					'Events' : [{'imei' : self.ids_to_be_tracked[entry['srccall']],
								'timeStamp' : int( 1000 * entry['time']),  #  seems BB's code converts to integer in msec, so copying that.
								'point' : {'latitude' : entry['lat'], 'longitude' : entry['lng'], 'altitude' : entry['altitude']},},]
					}
				self.upload_packet_to_gpaero(json_dict)
			except Exception as e:
				logging.warning('send_locations failed due to {:} raw : {:}'.format(e, entry))
		self.locations = []
		

class APRSIS2GP(APRSBase):
	"""
	get the aprs packets directly from aprs-is
	"""

	def packet_parser(self, packet):
		"""
		minimal wrapper in this case, but expect to be overwritten for e.g. ogn parsing
		"""
		return aprslib.parse(packet)
	
	def __init__(self, ids_to_be_tracked, callsign, **kwargs):
		"""
		ids : a dictionary of callsign : IMEI items.
		aprs_api_key : said key for a valid aprs.fi user id
		"""
		super(APRSIS2GP, self).__init__(ids_to_be_tracked, **kwargs)
		self.callsign = callsign
		logging.info('Using callsign ' +  self.callsign)
		self.prepare_connection(**kwargs)
	
	def prepare_connection(self, **kwargs):
		self.AIS = aprslib.IS(self.callsign)#, host='noam.aprs2.net', port=14580)
		self.delay_before_check = kwargs.get('delay', 0.5)
		
	def filter_callsigns(self, packet, packet_i = -1):
		if self.verbose:
			logging.debug('raw packet : %s' % packet)
		if len(packet) == 0:
			return
		try:
			ppac = self.packet_parser(packet)
			if ppac is None:
				return
			if _DEBUG or _LOG_ALL:
				with open(os.path.join(tempfile.gettempdir(), 'aprs2gpaero_all_packet.log'), 'a') as f:
					# termination chosen so that i can use the file for debugging 
					f.write(packet+'\r\n')
			if self.verbose:
				logging.debug('parsed :\n%s' % ppac)
			# the form below is useful for debuggging, but in reality we need exact matches since we need to translate to IMEI values.
			if any([ppac['from'].startswith(x) for x in self.ids_to_be_tracked.keys()]):
				# we should drop duplicate packets, or those that are too frequent to be real.
				# ideally, the packets should have a time stamp; tinytrak has this, and likely others, but it's optional.
				# check if we've seen this packet recently, and if so, drop it
				# however, we can't look at the raw packet, since we could have gotten it from a different source, which is what we're trying to deduplicate.
				# i can't gaurantee that we had an independent time stamp, so we'll just use the location information;
				# this of couse is not guaranteed unitque, but i'm willing to accept the potential loss if one of the last few packets match exactly.
				short_packet_data = '{:} {:} {:}'.format(ppac['longitude'], ppac['latitude'], ppac.get('altitude', 0))
				# get timestamp from packet, if included - not common. (actually, not common for aprs, is common for flarm / ogn)
				timestamp = ppac.get('timestamp', time.time())
				if short_packet_data in self.recent_packets.get(ppac['from'], []):
					self.packet_stats[ppac['from']]['duplicate'] += 1
					logging.warning('Dropping duplicate of recent packet - %s' % packet)
				elif timestamp - self.last_packet_time.get(ppac['from'], 0) < self.min_packet_dt:
					logging.warning('Got new packet too soon - %0.1f sec after last one, < %0.1f sec : %s' % (timestamp - self.last_packet_time.get(ppac['from'], 0), self.min_packet_dt, packet))
					self.packet_stats[ppac['from']]['rate_limit'] += 1
				else:
					self.packet_stats[ppac['from']]['good'] += 1
					# only count valid packet for rate limiting.
					self.last_packet_time[ppac['from']] = timestamp
					logging.info('Adding packet : {:}'.format(ppac))
					self.locations.append({'srccall' : ppac['from'],
								'lng' : ppac['longitude'],
								'lat' : ppac['latitude'],
								'altitude' : ppac.get('altitude', 0),  # exception, mostly for debugging, but i'm willing to accept trackers configured without altitude.
								'time' : timestamp}) 
					if _DEBUG or self.verbose:
						logging.debug('after adding\n%s' % self.locations)
				# adding this packet to the recent ones held for the id, regardless of validity
				self.recent_packets[ppac['from']].append(short_packet_data)
				
			elif self.verbose:
				logging.debug('from %s, skip' %ppac['from'])
		# we may want to define an explicit list of exceptions, so e.g. the ogn child can have a different one.
		except Exception as e: #(aprslib.UnknownFormat, aprslib.ParseError:) as e:
			logging.debug('filter_callsigns - i = {:0d} failed due to {:} raw packet *{:}*'.format(packet_i, e, packet))
		
	def get_loc(self):
		self.AIS.connect()
		# necessary
		time.sleep(self.delay_before_check)
		logging.debug('connected')
		self.AIS.consumer(self.filter_callsigns, raw=True, blocking=False)
		logging.info('found\n{:}'.format(self.locations))
		self.AIS.close()
		logging.debug('closed')
		

class APRSIS2GPRAW(APRSIS2GP):
	"""
	get the aprs packets directly from aprs-is, using raw sockets and the general port.
	this is ugly and lousy, but for some reason i'm having issues connecting to the 14580 port.
	the warnings about the traffic flooding the isp are a bit funny though, straight out of a 2400 baud era (if you were rich).
	we're going to just take all of the data, and filter it by callsigns.
	i'm testing this on a reasonably modern i7 laptop, but i really can't imagine that parsing ~100 mesages / sec (what i get in testing) is an issue on any reasonable hw these days.
	"""
	
	version = 0.01
	sock_block_len = 2**14
	
	def __init__(self, ids_to_be_tracked, callsign, addr = '45.63.21.153', port = 10152, print_info_every_x_seconds = 1.0, **kwargs):
		"""
		ids_to_be_tracked : a dictionary of callsign : IMEI items.
		callsign : for logging into the APRS-IS server; but note that no password is used or needed since we're reading only, so it really could be anything valid.
		"""
		self.addr = addr
		self.port = port
		self.print_info_every_x_seconds = print_info_every_x_seconds
		self._buffer = ''
		self.max_consecutive_data_loss =  kwargs.get('max_consecutive_data_loss', 3)
		self._total_N_packets = 0
		self.data_loss_counter = 0
		super(APRSIS2GPRAW, self).__init__(ids_to_be_tracked, callsign, **kwargs)
		logging.info('Connecting to {:}:{:}'.format(self.addr, self.port))
		
	def prepare_connection(self, **kwargs):
		self.raw_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		self.raw_socket.connect((self.addr, self.port))
		self.raw_socket.setblocking(True)
		self.raw_socket.settimeout(2)
		time.sleep(0.1)
		logging.info('server greeting : *{:}*'.format(self.raw_socket.recv(10000).decode('utf-8')))
		time.sleep(0.1)
		# casualty of 2 to 3 conversion; this is no longer ok (whether it ever was a good idea is another question)
		#self.raw_socket.sendall(b'user {:} pass -1 vers {:} {:}\n\r'.format(self.callsign, self.__class__.__name__, self.version))
		self.raw_socket.sendall(bytearray('user {:} pass -1 vers {:} {:}\n\r'.format(self.callsign, self.__class__.__name__, self.version),encoding="utf-8", errors="strict"))
		logging.info('ack : *{:}*'.format(self.raw_socket.recv(10000).decode('utf-8').split('\r\n')[0]))
		self.raw_socket.settimeout(kwargs.get('socket_timeout', self.wait_between_checks * 2))  # fudge factor.
	
	def cleanup(self, **kwargs):
		super(APRSIS2GPRAW, self).cleanup(**kwargs)
		self.close_connection()
	
	def close_connection(self):
		logging.info('closing socket')
		self.raw_socket.close()
		
	def get_loc(self):
		try:
			# we're going to drop stuff with non utf-8 chars later, but we shouldn't drop other legit packets.
			pre_data = (self._buffer + self.raw_socket.recv(self.sock_block_len).decode('utf-8', errors = 'ignore')).split('\r\n')
			# if last line is an exact packet, this wil shift its processing one cycle later; seems acceptable.
			self._buffer = pre_data[-1]
			data = pre_data[:-1]
			now = time.time()
			self._total_N_packets += len(data)
			if now - self.last_print > self.print_info_every_x_seconds:
				self.last_print = now
				# TODO drop the dt?
				logging.info('dt = {:0.1f} sec, N_packets {:0d}, mean rate {:0.2f} packets / sec'.format(now - self.start_time, len(data), self._total_N_packets / (time.time() - self.start_time)))
			for packet_i, packet in enumerate(data):
				self.filter_callsigns(packet, packet_i = packet_i)
			if len(data) < 2: # 1?
				self.data_loss_counter += 1
				logging.warning('Got no data for last {:0d} cycles'.format(self.data_loss_counter))
				if self.data_loss_counter >= self.max_consecutive_data_loss:
					logging.error('got too little data for too many consecutive cycles (> {:0d}), resetting socket'.format(self.max_consecutive_data_loss))
					self.close_connection()
					time.sleep(1.0)
					self.prepare_connection()
			else:
				self.data_loss_counter = 0
		except socket.error as e:
			logging.error('Socket exception {:}, resetting connection'.format(e))
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
	However, i've ended up forcing other sources to the slightly odd dictionary keys e.g. lng that its API uses; too bad.
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
				logging.debug(callsign_group)
				res = requests.get('https://api.aprs.fi/api/get?name={:}&what=loc&apikey={:}&format=json'.format(callsign_group, self.aprs_api_key))
				logging.debug(res.url)
				res.raise_for_status()
				logging.debug('got\n*%s*' % res.json())
				self.locations.extend(res.json()['entries'])
			except Exception as e:
				logging.debug('get_loc - failed due to %s' % e)


def main():
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

if __name__ == '__main__':
	main()
