#!/usr/bin/env python
"""
handle ogn to gpaero; it's really aprs as well, so it makes some sense 
for it to live in the same rpository.
i'm splitting the file for now mostly for convenience; logically it's a bit murky.

june 29th test - works, but seems we have a 1h offset (too early vs aprs, garmin traces); i'm guessing DST somehow, so applying an adhoc fix.
TODO: see about pushing climb rate data; it's displayed in the gauges, so it would be nice to bea able to fill it.
"""

import argparse
from datetime import datetime
from timezonefinder import TimezoneFinderL
from pytz import timezone
from x2gpaero.aprs2gp import APRSIS2GPRAW, config_file_reader, _USABLE_KEYWORDS
from ogn.parser import parse as ogn_parse
from ogn.parser import ParseError as OGNParseError
from ogn.client import settings as ogn_settings


# default list of receivers that we don't want to forward ; in general, these are sources that already should be reporting to glideport.aero themselves, such as inreach. These will be forced to lower case when comparing.
RX_NAMES_TO_REJECT = ('inreach', 'spot', 'adsb')

# default address type we're accepting - anything else will be rejected.
ADDRESS_TYPES_ACCEPTED = (1, 2, 3) # see http://wiki.glidernet.org/wiki:ogn-flavoured-aprs ; lower two bits encode address type, 00 is unknown.

_OGN_USABLE_KEYWORDS = _USABLE_KEYWORDS + ['rx_names_to_reject', 'address_types_accepted']

class OGN2GPAero(APRSIS2GPRAW):
	"""
	take full OGN feed, filter client side and push appropriate to gpaero.
	this may not be the best use, and i'll have to see whether the approach is even accpetable for ogn
	however, this is direclty working for the aprs case, so it makes the easiest starting point.
	"""

	sock_block_len = 2**14

	# i don't want to pay the startup time; i could have one per trace, but it's annoying, and loading all to memory should mean that we've predone the optimization.
	tf = TimezoneFinderL(in_memory=True)

	def shift_time_based_on_local_dst(self, timestamp, latitude, longitude):
		'''
		shift a given time stamp by a daylight saving's time amount if needed.
		Args:
			timestamp: i.e. integer number of seconds, typically time since epoch
			latitude: latitude of point of interest, degrees
			longitude: longitude of point of interest, degrees
		Returns:
			timestamp shifted by appropriate dst amount, typically zero or one hour.
		'''
		tz = timezone(self.tf.timezone_at(lat = latitude, lng = longitude))
		return timestamp + tz.dst(datetime.utcfromtimestamp(timestamp)).total_seconds()

	def packet_parser(self, packet):
		"""
		convert the dictionary of an ogn packet to one conforming to what we expect from an aprs one.
		in practice, handles addresses and time stamps.
		also, rejects packets whose address type is not on the approved list, or whose receiver name matches a list of receiver non grata
		"""
		d = ogn_parse(packet)
		# FLARM (and i guess other non aprs) packets use an address field in the same manner an aprs uses the from field.
		#print('packet type = %s %s ' % (d['aprs_type'], d))
		if not d.get('aprs_type', None) == 'position':
			return None
		if not 'from' in d:
			if 'address' in d:
				d['from'] = d['address']  # mode S transponder address usually.
			else:
				return None
		if 'timestamp' in d:
			d['timestamp'] = d['timestamp'].timestamp()
		return d

	def packet_post_id_filter(self, parsed_packet):
		'''
		filter a packet that already is matched to an id based based receiver or address type
		Args:
			parsed_packet : OGN parsed packet (dictionary)
		Returns:
			parsed_packet if good, otherwise None
		'''
		# NOTE: may turn these to debug messages in the future.
		if not parsed_packet['address_type'] in self.address_types_accepted:
			self.logger.info('address type %s not in %s, discarding packet %s', address_type, self.address_types_accepted, parsed_packet)
			return None
		lower_case_rx_name = parsed_packet['receiver_name'].lower()
		if any([lower_case_rx_name.find(nongood_rx_name) >= 0 for nongood_rx_name in self.rx_names_to_reject]):
			self.logger.info('receiver is one of %s; discarding packet %s', self.rx_names_to_reject, parsed_packet)
			return None
		return parsed_packet

	def __init__(self,
			ids_to_be_tracked,
			rx_names_to_reject = RX_NAMES_TO_REJECT,
			address_types_accepted = ADDRESS_TYPES_ACCEPTED,
			callsign = 'N0CALL',
			addr = ogn_settings.APRS_SERVER_HOST,
			port = ogn_settings.APRS_SERVER_PORT_FULL_FEED, **kwargs):
		self.rx_names_to_reject = [x.lower() for x in rx_names_to_reject]
		self.address_types_accepted = address_types_accepted
		super(OGN2GPAero, self).__init__(ids_to_be_tracked, callsign, addr = addr, port = port, **kwargs)
		self.logger.info(f'Will reject {self.rx_names_to_reject} and accept address types {self.address_types_accepted}')


def main():
	parser = argparse.ArgumentParser(description= '''
send OGN location packets for specific users to gpaero
''', formatter_class= argparse.RawTextHelpFormatter)
	parser.add_argument('config', type = str, default = '',
			help= '''
json config file - must have 
ids - a dictionary of 'address' (usually S-mode code) : IMEI identifier
optional {:}'''.format(_OGN_USABLE_KEYWORDS))
	args = parser.parse_args()
	config = config_file_reader(args.config)
	ids_to_be_tracked = config.pop('ids')
	c = OGN2GPAero(ids_to_be_tracked, **config)
	c.monitor()

if __name__ == '__main__':
	main()
