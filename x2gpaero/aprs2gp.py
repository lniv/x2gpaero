#!/usr/bin/env python
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


from __future__ import print_function

import os
import time
import logging
import subprocess
import socket
import requests
import json
import tempfile
import inspect
from collections import deque, defaultdict
from functools import wraps
from queue import Queue
from threading import Thread
from numpy.random import uniform
import argparse
import aprslib
from requests.exceptions import ConnectTimeout

_DEBUG = False
_LOG_ALL = False
_UPLOAD = True # set to False for debugging, so it doesn't actually interact with glideport.aero, but one can see what would have been uploaded etc

_USABLE_KEYWORDS = ['verbose', 'wait_between_checks', 'max_wait_between_checks', 'max_consecutive_data_loss', 'socket_timeout', 'print_info_every_x_seconds', 'print_stats_every_x_seconds', 'print_monitor_every_x_seconds', 'calculate_mean_window_sec', 'min_packet_dt', 'N_last_packets', 'socket_timeout', 'delay', 'max_packets', 'glideport_timeout_sec']


def config_file_reader(filename):
	"""
	read a simple config file
	i'd prefer to keep to json, as we're using it for other things
	"""
	with open(filename, 'r') as f:
		config = json.load(f)
	return config


def create_attr_from_args(func):
	'''
	decorator that create instance attributes from a method's arguments.
	typically applied to the creator method, to reduce boilerplate.
	e.g.

	class M(object):

		create_attr_from_args
		def __init__(self, a, b, c, d = 4, e = 5):
			pass

	a = M(1,2,3, e = 17, d = 5)

	will result in
	a.__dict__ == {'a': 1, 'b': 2, 'c': 3, 'e': 17, 'd': 5}

	'''
	@wraps(func)
	def wrapper(self, *args, **kwargs):
		funcspec = inspect.getfullargspec(func)
		# ignore self, update kwargs with the default values
		for arg_name, def_value in zip(funcspec.args[len(args) + 1:], funcspec.defaults):
			kwargs[arg_name] = kwargs.get(arg_name, def_value)
		for k, v in list(zip(funcspec.args[1:], list(args))) + list(kwargs.items()):
			setattr(self, k, v)
		val = func(self, *args, **kwargs)
		return val

	return wrapper


def upload_packet_to_gpaero(logger, json_dict, glideport_timeout_sec):
	"""
	Uses the push method
	there are other methods meant for higher frequency fixes - GlideTrak protocol.
	i may branch these later to use those, or refactor the code a bit, or not bother - i suspect that as long as we're closer to a spot / inreach in terms of fix frequency, it all works well.
	"""
	if not _UPLOAD:
		logger.info('would upload, but skipping %s', json_dict)
		return
	logger.info('Uploading %s', json_dict)
	# from BB's code
	#curl -H "Accept: application/json" -H "Content-Type: application/json" -d @json_file http://glideport.aero/spot/ir_push.php
	# Note that the user has to have added  ir_push:IMEI (With the/ a(?) correct IMEI)
	r = requests.post('http://glideport.aero/spot/ir_push.php', json=json_dict, timeout = glideport_timeout_sec)
	r.raise_for_status()
	logger.info('Received %s', r.text)


def packet_uploader(packets_queue, glideport_timeout_sec, print_every_n_sec, base_timeout_delay = 0.05):
	'''
	an uploader that is meant to run in a separate thread, consuming packets that are to be sent to glideport.aero
	will stop only when we consume a packet of 'stop'.
	Args:
		packets_queue: a queue.Queue FIFO
		glideport_timeout_sec: pass to uploader, handle exeeption
		print_every_n_sec: print stats this often.
		base_timeout_delay: the delay on the first timeout
	'''

	def print_imei_upload_stats(packets_stats, prefix = 'upload_stats'):
		logger.info(f'{prefix} queue N = {packets_queue.qsize():0d}')
		for imei, v in packets_stats.items():
			logger.info(f'{prefix} of {imei} : {v}')

	logger = logging.getLogger('Uploader')
	logger.info('entering loop')
	packets_stats = defaultdict(lambda : dict({'success' : 0, 'failed' : 0, 'timedout' : 0}))
	upload_delay = base_timeout_delay
	last_print_t = time.time()
	while True:
		packet_to_upload = packets_queue.get()
		if packet_to_upload == 'stop':
			logger.info('got a stop request')
			break
		# any normal packet will have this structure, and we can get an imei for our stats.
		# defactor assuming here i'm getting packets for a single IMEI, but i did write both sides...
		try:
			imei = packet_to_upload['Events'][0]['imei']
		except KeyError:
			logger.warning('could not get IMEI from packet : *%s*, badly formed? skipping', packet_to_upload)
			continue
		if time.time() - last_print_t > print_every_n_sec:
			last_print_t = time.time()
			print_imei_upload_stats(packets_stats)
		try:
			upload_packet_to_gpaero(logger, packet_to_upload, glideport_timeout_sec)
			packets_stats[imei]['success'] += 1
			upload_delay = base_timeout_delay
		except ConnectTimeout:
			# i expect this is a global failure of the server we're talking to, not of a specific packet, so we just have to wait.
			logger.warning('timed out on connection, shoving packet back to end of queue (N = %0d), and waiting %0.2f sec', packets_queue.qsize() + 1, upload_delay)
			time.sleep(upload_delay)
			upload_delay *= uniform(low=1.0, high=2.0)  # some randomness
			packets_queue.put(packet_to_upload)
			packets_stats[imei]['timedout'] += 1
		except Exception as e:
			logger.warning('failed to upload due to *%s*,dropping packet %s', e, packet_to_upload)
			packets_stats[imei]['failed'] += 1
	logger.info('exited upload loop')
	print_imei_upload_stats(packets_stats, prefix = 'final upload_stats')


class APRSBase(object):
	
	'''
	base class for handling packets from aprs(like source) to glideport.aero
	Args:
		ids_to_be_tracked: dictionary of id's to IMEI
		verbose: controls logging verbosity [False]
		print_stats_every_x_seconds: period for logging / prints packet statistics [600]
		print_monitor_every_x_seconds: period for a simple heartbeat, defaults to effectively off [2**64 -1]
		max_wait_between_checks: never wait more than this before trying to get data again [1800.0]
		N_last_packets: length of buffer kept for packet deduplication [5]
		wait_between_checks: nominal time to wait after getting and processing one set of packets [1.0]
		min_packet_dt: [10.0]
		max_packets: limit to number of packets retained for transmission to glideport [5000]
		glideport_timeout_sec: timeout limit when uploading [5.0]
	'''

	@create_attr_from_args
	def __init__(self, ids_to_be_tracked, verbose = False, print_stats_every_x_seconds = 600, print_monitor_every_x_seconds = 2**64 -1, max_wait_between_checks = 1800.0, N_last_packets = 5, wait_between_checks = 1.0, min_packet_dt = 10.0, max_packets = 5000, glideport_timeout_sec = 5.0, **kwargs):
		"""
		ids : a dictionary of callsign : IMEI items.
		"""
		self.N_id_groups = len(self.ids_to_be_tracked.keys()) / 20 + 1
		self.default_wait_between_checks = self.wait_between_checks
		self.setup_loggers()
		try:
			self.logger.info('git branch %s', subprocess.check_output(['git', 'branch', '-v']).decode('utf-8').split('\n')[0] )
			git_diff = subprocess.check_output(['git',  'diff']).decode('utf-8')
			if len(git_diff) > 0:
				self.logger.info('git diff\n%s\n*', git_diff)
			else:
				self.logger.info('git repository is clean')
		except subprocess.CalledProcessError:
			self.logger.warning('cannot log git status')
		self.reset()
		self.packets_queue = Queue(maxsize = self.max_packets)
		self.logger.info('kwargs = %s', kwargs)
		for aprs_id, IMEI in self.ids_to_be_tracked.items():
			self.logger.info('Tracking %s : %s', aprs_id, IMEI)

	def setup_loggers(self):
		'''
		setup up loggers the way i want them - mostly so they time stamp all, and log to file and console
		'''
		# put the root logger into a clean state.
		rlogger = logging.getLogger()
		while len(rlogger.handlers) > 0:
			handler = rlogger.handlers[0]
			rlogger.removeHandler(handler)
			handler.close()

		rlogger.setLevel(logging.DEBUG if self.verbose else logging.INFO)

		self.log_filename = os.path.join(tempfile.gettempdir(), time.strftime('{:}_%Y_%m_%d_%H_%M_%S.log'.format(self.__class__.__name__)))
		fh = logging.FileHandler(self.log_filename)
		sh = logging.StreamHandler()
		for handle in (fh, sh):
			# set up message and time formatting
			handle.setFormatter(logging.Formatter('%(asctime)s %(name)s %(levelname)-8s %(message)s', '%Y_%m_%d_%H_%M_%S'))
			rlogger.addHandler(handle)
		self.logger = logging.getLogger('X2GP')
		self.logger.info('Logging to %s', self.log_filename)

	def reset(self):
		# monitor will reassert thes, but just in case
		self.start_time = 0
		self.last_print = 0
		self.last_stats_print = 0
		
		self.locations = deque(maxlen = self.max_packets)
		self.wait_between_checks = self.default_wait_between_checks
		self.recent_packets = {k : deque([], maxlen = self.N_last_packets) for k in self.ids_to_be_tracked}
		# accept new packet only after min_packet_dt seconds since last valid one.
		self.last_packet_time = {k : 0.0 for k in self.ids_to_be_tracked}
		self.packet_stats = {k : {'good' : 0, 'rate_limit' : 0, 'duplicate' : 0} for k in self.ids_to_be_tracked}

	def get_loc(self):
		raise NotImplementedError

	def shift_time_based_on_local_dst(self, timestamp, latitude, longitude):
		'''
		shift a time stamp based on local daylight saving time.
		stub meant to be overloaded if needed - as is apparently the case for OGN.
		Args:
			timestamp: seconds since epoch
			latitude: position, degrees
			longitude: degrees
		Returns:
			shifted timestamp, as needed.
		'''
		return timestamp

	def log_stats(self, prefix = 'packet_stats'):
		'''
		pretty print some overall statistics
		'''
		for owner_id, v in self.packet_stats.items():
			self.logger.info(f'{prefix} {owner_id}: {v}')

	def cleanup(self, **kwargs):
		"""
		any actions deemed prudent when stopping monitoring
		"""
		self.log_stats(prefix = 'final packet stats')
		self.packets_queue.put('stop')
		if hasattr(self, 'upload_thread'):
			self.logger.info('joining upload thread')
			self.upload_thread.join(timeout = 10.0) # this really shouldn't take long, but give it a bit of time just in case.

	def monitor(self):
		"""
		monitor the service every N seconds.
		if failing, increase timeout (and notify user).
		reset when successful.
		abort on ctrl-c
		"""
		
		self.start_time = time.time()
		self.last_print = self.start_time
		# start the upload thread
		self.upload_thread = Thread(target = packet_uploader, daemon = True, args =(self.packets_queue, self.glideport_timeout_sec, self.print_stats_every_x_seconds))
		self.upload_thread.start()
		while True:
			now = time.time()
			try:
				self.get_loc()
				self.send_locations()
				time.sleep(self.wait_between_checks)
				# reset wait if successful.
				self.wait_between_checks = self.default_wait_between_checks
				if not self.upload_thread.is_alive():
					self.logger.warning('found upload thread to be dead, aborting!')
					break
			except KeyboardInterrupt:
				self.logger.info('stopping upon request')
				self.logger.info('Logged to %s', self.log_filename)
				break
			except Exception as e:
				if self.wait_between_checks > self.max_wait_between_checks:
					# NOTE: might be better to terminate here, and e.g. let a cron job restart us?
					self.wait_between_checks = self.max_wait_between_checks
					self.logger.warning('Problem monitoring due to %s, wait time capped at %0.1f sec', e, self.max_wait_between_checks)
				else:
					self.wait_between_checks *= 2
					self.logger.warning('Problem monitoring due to %s, increasing wait time by x2 to %0.1f sec', e, self.wait_between_checks)
			# self.logger various stats etc, catch everything
			try:
				now = time.time() # some time has passed, best get a correct time stamp
				if now - self.last_stats_print > self.print_stats_every_x_seconds:
					self.last_stats_print = now
					self.log_stats()
				if now - self.last_print > self.print_monitor_every_x_seconds:
					self.last_print = now
					self.logger.info('monitor dt = %0.1f sec', time.time() - self.start_time)
			except Exception as e:
				self.logger.error('Failed to log misc info due to %s', e)
		self.cleanup()
	
	def send_locations(self):
		"""
		take locations
		convert ids to IMEI
		create json for uploading to gpaero
		save json to local log file
		put on the queue for uploading by second thread.
		
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
		if len(self.locations) == 0:
			return
		else:
			self.logger.debug('sending %0d locations', len(self.locations))

		failed_packets = []
		N_packets_to_upload = len(self.locations)
		entry_i = 0
		# could revert to a for loop, but keep it.
		while len(self.locations) > 0:
			entry_i += 1
			try:
				entry = self.locations.popleft()
				json_dict = {'Version' : 2.0,
					'Events' : [{'imei' : self.ids_to_be_tracked[entry['srccall']],
								'timeStamp' : int( 1000 * entry['time']),  #  seems BB's code converts to integer in msec, so copying that.
								'point' : {'latitude' : entry['lat'], 'longitude' : entry['lng'], 'altitude' : entry['altitude']},},]
					}
				self.packets_queue.put(json_dict)
			except Exception as e:
				self.logger.warning('send_locations failed at packet %0d/%0d due to *%s* raw : %s', entry_i +1, N_packets_to_upload, e, entry)
				failed_packets.append(entry)
		self.locations.extend(failed_packets)
		if len(self.locations) > 0:
			self.logger.info('Have %0d packets left after sending locations', len(self.locations))


class APRSIS2GP(APRSBase):
	"""
	get the aprs packets directly from aprs-is
	"""

	def packet_parser(self, packet):
		"""
		minimal wrapper in this case, but expect to be overwritten for e.g. ogn parsing
		"""
		return aprslib.parse(packet)

	def packet_post_id_filter(self, ppac):
		'''
		can be used to filter packets that are already in our id database, based on parsed charactristics
		Args:
			ppac: a parsed packet (dictionary)
		Returns:
			packet, potentially modified OR None (in which case we'll drop the packet).

		for base class, this is a null operation.
		'''
		return ppac

	def __init__(self, ids_to_be_tracked, callsign, **kwargs):
		"""
		ids : a dictionary of callsign : IMEI items.
		aprs_api_key : said key for a valid aprs.fi user id
		"""
		super(APRSIS2GP, self).__init__(ids_to_be_tracked, **kwargs)
		self.callsign = callsign
		self.logger.info('Using callsign %s', self.callsign)
		self.prepare_connection(**kwargs)
	
	def prepare_connection(self, **kwargs):
		self.AIS = aprslib.IS(self.callsign)#, host='noam.aprs2.net', port=14580)
		self.delay_before_check = kwargs.get('delay', 0.5)
		
	def filter_callsigns(self, packet, packet_i = -1):
		self.logger.debug('raw packet : %s', packet)
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
			self.logger.debug('parsed :\n%s', ppac)
			# the form below is useful for debuggging, but in reality we need exact matches since we need to translate to IMEI values.
			if any([ppac['from'].startswith(x) for x in self.ids_to_be_tracked.keys()]):
				# drop undesirable packets (for any reason) before they affect stats.
				ppac = self.packet_post_id_filter(ppac)
				if ppac is None:
					return
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
					self.logger.warning('Dropping duplicate of recent packet - %s', packet)
				elif timestamp - self.last_packet_time.get(ppac['from'], 0) < self.min_packet_dt:
					self.logger.warning('Got new packet too soon - %0.1f sec after last one, < %0.1f sec : %s', timestamp - self.last_packet_time.get(ppac['from'], 0), self.min_packet_dt, packet)
					self.packet_stats[ppac['from']]['rate_limit'] += 1
				else:
					self.packet_stats[ppac['from']]['good'] += 1
					self.last_packet_time[ppac['from']] = timestamp
					# i seem to have an issue with OGN and daylight saving time.
					# however, the place to fix it is post filtering / selection, so it's here - the default fix method is a passthrough.
					# shift timestamp \after\ i save the recent packet time - so i only change what's uploaded, not the local time stamping.
					timestamp= self.shift_time_based_on_local_dst(timestamp, ppac['latitude'], ppac['longitude'])
					self.logger.info('Adding packet : %s', ppac)
					self.locations.append({'srccall' : ppac['from'],
								'lng' : ppac['longitude'],
								'lat' : ppac['latitude'],
								'altitude' : ppac.get('altitude', 0),  # exception, mostly for debugging, but i'm willing to accept trackers configured without altitude.
								'time' : timestamp}) 
					if _DEBUG or self.verbose:
						self.logger.debug('after adding\n%s', self.locations)
				# adding this packet to the recent ones held for the id, regardless of validity
				self.recent_packets[ppac['from']].append(short_packet_data)

			self.logger.debug('from %s, skip', ppac['from'])
		# we may want to define an explicit list of exceptions, so e.g. the ogn child can have a different one.
		except Exception as e: #(aprslib.UnknownFormat, aprslib.ParseError:) as e:
			self.logger.debug('filter_callsigns - i = %0d failed due to %s raw packet *%s*', packet_i, e, packet)
		
	def get_loc(self):
		self.AIS.connect()
		# necessary
		time.sleep(self.delay_before_check)
		self.logger.debug('connected')
		self.AIS.consumer(self.filter_callsigns, raw=True, blocking=False)
		self.logger.info('found\n%s', self.locations)
		self.AIS.close()
		self.logger.debug('closed')
		

class APRSIS2GPRAW(APRSIS2GP):
	"""
	get the aprs packets directly from aprs-is, using raw sockets and the general port.
	this is ugly and lousy, but for some reason i'm having issues connecting to the 14580 port.
	the warnings about the traffic flooding the isp are a bit funny though, straight out of a 2400 baud era (if you were rich).
	we're going to just take all of the data, and filter it by callsigns.
	i'm testing this on a reasonably modern i7 laptop, but i really can't imagine that parsing ~100 mesages / sec (what i get in testing) is an issue on any reasonable hw these days (and it doesn't seem to be on a raspberry pi zero w)
	Args:
		ids_to_be_tracked : a dictionary of callsign : IMEI items.
		callsign : for self.logger into the APRS-IS server; but note that no password is used or needed since we're reading only, so it really could be anything valid.
		addr: server address ['45.63.21.153']
		port: server port [10152]
		print_info_every_x_seconds: period over which to print a bit more detailed recent count etc info [1.0]
		calculate_mean_window_sec: winodw over which we calculate recent rate [60]
		max_consecutive_data_loss: reset connections if we got no packets this many times [3]
	"""

	version = 0.01
	sock_block_len = 2**14
	
	def __init__(self, ids_to_be_tracked, callsign, addr = '45.63.21.153', port = 10152, print_info_every_x_seconds = 1.0, calculate_mean_window_sec = 60, max_consecutive_data_loss = 3, **kwargs):
		self.addr = addr
		self.port = port
		self.print_info_every_x_seconds = print_info_every_x_seconds
		self.calculate_mean_window_sec = calculate_mean_window_sec
		self.max_consecutive_data_loss =  max_consecutive_data_loss
		super(APRSIS2GPRAW, self).__init__(ids_to_be_tracked, callsign, **kwargs)
		self.logger.info('Connecting to %s:%s', self.addr, self.port)

	def reset(self):
		super().reset()
		self._buffer = ''
		self._total_N_packets = 0
		self._packet_count_bubffer = deque([], maxlen = 1000) # use to calculate mean rates; should be deep enough that we exclude based on age, but limit to avoid memory issues.
		self.data_loss_counter = 0

	def prepare_connection(self, **kwargs):
		self.raw_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		self.raw_socket.connect((self.addr, self.port))
		self.raw_socket.setblocking(True)
		self.raw_socket.settimeout(2)
		time.sleep(0.1)
		self.logger.info('server greeting : *%s*', self.raw_socket.recv(10000).decode('utf-8'))
		time.sleep(0.1)
		# casualty of 2 to 3 conversion; this is no longer ok (whether it ever was a good idea is another question)
		#self.raw_socket.sendall(b'user {:} pass -1 vers {:} {:}\n\r'.format(self.callsign, self.__class__.__name__, self.version))
		self.raw_socket.sendall(bytearray('user {:} pass -1 vers {:} {:}\n\r'.format(self.callsign, self.__class__.__name__, self.version),encoding="utf-8", errors="strict"))
		self.logger.info('ack : *%s*', self.raw_socket.recv(10000).decode('utf-8').split('\r\n')[0])
		self.raw_socket.settimeout(kwargs.get('socket_timeout', self.wait_between_checks * 2))  # fudge factor.
	
	def cleanup(self, **kwargs):
		super(APRSIS2GPRAW, self).cleanup(**kwargs)
		self.close_connection()
	
	def close_connection(self):
		self.logger.info('closing socket')
		self.raw_socket.close()
		
	def get_loc(self):
		try:
			# we're going to drop stuff with non utf-8 chars later, but we shouldn't drop other legit packets.
			pre_data = (self._buffer + self.raw_socket.recv(self.sock_block_len).decode('utf-8', errors = 'ignore')).split('\r\n')
			# if last line is an exact packet, this wil shift its processing one cycle later; seems acceptable.
			self._buffer = pre_data[-1]
			data = pre_data[:-1]
			now = time.time()
			# add the recent count, then filter
			self._packet_count_bubffer.append((len(data), time.time()))
			while time.time() - self._packet_count_bubffer[0][1] > self.calculate_mean_window_sec:
				self._packet_count_bubffer.popleft()
			self.logger.debug('%0d packets in mean rate calculation buffer', len(self._packet_count_bubffer))
			self._total_N_packets += len(data)
			if now - self.last_print > self.print_info_every_x_seconds:
				self.last_print = now
				self.logger.info('Got %0d packets, overall mean rate %0.2f packets / sec over %0d sec, over last %0.1f sec mean rate = %0.2f packets / sec', len(data), self._total_N_packets / (time.time() - self.start_time), time.time() - self.start_time, self.calculate_mean_window_sec, sum([x[0] for x in self._packet_count_bubffer]) /  (self._packet_count_bubffer[-1][1] - self._packet_count_bubffer[0][1]))
			for packet_i, packet in enumerate(data):
				self.filter_callsigns(packet, packet_i = packet_i)
			if len(data) < 2: # 1?
				self.data_loss_counter += 1
				self.logger.warning('Got no data for last %0d cycles', self.data_loss_counter)
				if self.data_loss_counter >= self.max_consecutive_data_loss:
					self.logger.error('got too little data for too many consecutive cycles (> %0d), resetting socket', self.max_consecutive_data_loss)
					self.close_connection()
					time.sleep(1.0)
					self.prepare_connection()
			else:
				self.data_loss_counter = 0
		except socket.error as e:
			self.logger.error('Socket exception %s, resetting connection', e)
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
				self.logger.debug(callsign_group)
				res = requests.get('https://api.aprs.fi/api/get?name={:}&what=loc&apikey={:}&format=json'.format(callsign_group, self.aprs_api_key))
				self.logger.debug(res.url)
				res.raise_for_status()
				self.logger.debug('got\n*%s*', res.json())
				self.locations.extend(res.json()['entries'])
			except Exception as e:
				self.logger.debug('get_loc - failed due to *%s*', e)


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
