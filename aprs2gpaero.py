"""
move aprs data onto glideport.aero

starting from BB's (shell) code, and using that + aprs.fi api as guide.

TODO:
1 this should probably read a config file with the user callsigns : IEMI pairs, maybe other info (aprs.fi api keys, if we use that)
2 needs a loop for pushing data
3 not sure how often we can actually read data from aprs.fi - will need to talk to him(?) and see about rates etc (or go to ARPS-IS)
4 add installation instructions - here or in a github md file

NOTE: it's problematic having a canned example here, for two reasons:
1. ultimately we will be pushing to a live website, which i don't want to contaminate.
2. the real packets must have some not so public info - IEMI values.
"""

import time
import requests
import json
import aprslib


class APRSBase(object):
	
	def __init__(self, ids_to_be_tracked):
		"""
		ids : a dictionary of callsign : IMEI items.
		aprs_api_key : said key for a valid aprs.fi user id
		"""
		self.ids_to_be_tracked = ids_to_be_tracked
		self.N_id_groups = len(self.ids_to_be_tracked.keys()) / 20 + 1
		self.reset()
	
	def reset(self):
		self.locations = []
	
	def get_loc(self):
		raise NotImplementedError
	
	def create_gpaero_packets(self):
		"""
		take locations, convert ids to IMEI, create json for uploading to gpaero
		should clear the locations once uploaded. (but maybe not this function?)
		
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
		for entry in self.locations:
			try:
				d = {'Version' : 2.0,
					'Events' : [{'imei' : self.ids_to_be_tracked[entry['srccall']],
								'timeStamp' : entry['time'],  # maybe status_lasttime, or lasttime - not sure what's better
								'point' : {'latitude' : entry['lat'], 'longitude' : entry['lng'], 'altitude' : entry['altitude']},},]
					}
				print json.dumps(d)
			except Exception as e:
				print 'failed due to ', e, ' raw:\n', entry
	

class APRSIS2GP(APRSBase):
	"""
	get the aprs packets directly from aprs-is
	"""
	
	def __init__(self, ids_to_be_tracked, callsign, **kwargs):
		"""
		ids : a dictionary of callsign : IMEI items.
		aprs_api_key : said key for a valid aprs.fi user id
		"""
		super(APRSIS2GP, self).__init__(ids_to_be_tracked)
		self.AIS = aprslib.IS(callsign)#, host='noam.aprs2.net', port=14580)
		self.delay_before_check = kwargs.get('delay', 0.5)
		self.verbose = kwargs.get('verbose', False)
		
	def filter_callsigns(self, packet):
		if self.verbose:
			print packet
		try:
			ppac = aprslib.parse(packet)
			print 'parsed :\n', ppac
			if ppac['from'] in self.ids_to_be_tracked.keys():
				self.locations.append({'srccall' : ppac['from'],
							'long' : ppac['longitude'],
							'lat' : ppac['latitude'],
							'altitude' : ppac['altitude'],
							'timeStamp' : ppac['timestamp']})
			elif self.verbose:
				print 'from {:}, skip'.format(ppac['from'])
		except Exception as e:
			print 'filter_callsigns failed to parse packet due to %s' % e
		
	def get_loc(self):
		self.AIS.connect()
		# necessary
		time.sleep(self.delay_before_check)
		print 'connected'
		self.AIS.consumer(self.filter_callsigns, raw=True, blocking=False)
		print 'found\n', self.locations
		self.AIS.close()
		print 'closed'
	
		

class APRSFI2GP(APRSBase):
	"""
	get data from aprs.fi, send to gpaero.
	NOTE: very useful for initial coding and personal experimentation, but the legality of using the aprs.fi api beyond that has to be checked on a case by case basis.
	"""
	
	def __init__(self, ids_to_be_tracked, aprs_api_key):
		"""
		ids : a dictionary of callsign : IMEI items.
		aprs_api_key : said key for a valid aprs.fi user id
		"""
		super(APRSFI2GP, self).__init__(ids_to_be_tracked)
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