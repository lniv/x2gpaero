"""
handle ogn to gpaero; it's really aprs as well, so it makes some sense 
for it to live in the same rpository.
i'm splitting the file for now mostly for convenience; logically it's a bit murky.
"""

from aprs2gpaero import APRSIS2GPRAW, config_file_reader, _USABLE_KEYWORDS
from ogn.parser import parse as ogn_parse
from ogn.parser import ParseError as OGNParseError
from ogn.client import settings as ogn_settings

class OGN2GPAero(APRSIS2GPRAW):
	"""
	take full OGN feed, filter client side and push appropriate to gpaero.
	this may not be the best use, and i'll have to see whether the approach is even accpetable for ogn
	however, this is direclty working for the aprs case, so it makes the easiest starting point.
	"""

	packet_parser = ogn_parse

	def __init__(self,
			ids_to_be_tracked,
			callsign = 'N0CALL',
			addr = ogn_settings.APRS_SERVER_HOST,
			port = ogn_settings.APRS_SERVER_PORT_FULL_FEED, **kwargs):
		
		super(OGN2GPAero, self).__init__(ids_to_be_tracked, callsign, **kwargs)


def main():
		parser = argparse.ArgumentParser(description= '''
send OGN location packets for specific users to gpaero
''', formatter_class= argparse.RawTextHelpFormatter)
	parser.add_argument('config', type = str, default = '',
			help= '''
json config file - must have 
ids - a dictionary of 'from' aprs packet : IMEI identifiers
optional {:}'''.format(_USABLE_KEYWORDS))
	args = parser.parse_args()
	config = config_file_reader(args.config)
	ids_to_be_tracked = config.pop('ids')
	c = OGN2GPAero(ids_to_be_tracked, callsign, **config)
	c.monitor()

if __name__ == '__main__':
	main()
