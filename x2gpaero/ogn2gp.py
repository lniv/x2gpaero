#!/usr/bin/python3
"""
handle ogn to gpaero; it's really aprs as well, so it makes some sense 
for it to live in the same rpository.
i'm splitting the file for now mostly for convenience; logically it's a bit murky.
"""

import argparse
from x2gpaero.aprs2gp import APRSIS2GPRAW, config_file_reader, _USABLE_KEYWORDS
from ogn.parser import parse as ogn_parse
from ogn.parser import ParseError as OGNParseError
from ogn.client import settings as ogn_settings


class OGN2GPAero(APRSIS2GPRAW):
	"""
	take full OGN feed, filter client side and push appropriate to gpaero.
	this may not be the best use, and i'll have to see whether the approach is even accpetable for ogn
	however, this is direclty working for the aprs case, so it makes the easiest starting point.
	"""

	sock_block_len = 2**14
	
	def packet_parser(self, packet):
		"""
		convert the dictionary of an ogn packet to one conforming to what we expect from an aprs one.
		in practice, handles addresses and time stamps.
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

	def __init__(self,
			ids_to_be_tracked,
			callsign = 'N0CALL',
			addr = ogn_settings.APRS_SERVER_HOST,
			port = ogn_settings.APRS_SERVER_PORT_FULL_FEED, **kwargs):
		super(OGN2GPAero, self).__init__(ids_to_be_tracked, callsign, addr = addr, port = port, **kwargs)


def main():
	parser = argparse.ArgumentParser(description= '''
send OGN location packets for specific users to gpaero
''', formatter_class= argparse.RawTextHelpFormatter)
	parser.add_argument('config', type = str, default = '',
			help= '''
json config file - must have 
ids - a dictionary of 'address' (usualll S-mode code) : IMEI identifier
optional {:}'''.format(_USABLE_KEYWORDS))
	args = parser.parse_args()
	config = config_file_reader(args.config)
	ids_to_be_tracked = config.pop('ids')
	c = OGN2GPAero(ids_to_be_tracked, **config)
	c.monitor()

if __name__ == '__main__':
	main()
