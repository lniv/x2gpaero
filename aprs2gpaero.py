"""
move aprs data onto glideport.aero

starting from BB's (shell) code, and using that + aprs.fi api as guide.

TODO:
1 this should probably read a config file with the user callsigns : IEMI pairs, maybe other info (aprs api keys
2 needs a loop for pushing data
3 not sure how often we can actually read data from aprs.fi - will need to talk to him(?) and see about rates etc (or go to ARPS-IS)
4 add installation instructions - here or in a github md file
"""

import requests
import json


class APRSIS2GP(object):
	"""
	get the aprs packets directly from aprs-is
	"""
	
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
	
		

class APRSFI2GP(APRSIS2GP):
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