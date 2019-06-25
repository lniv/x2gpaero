# x2gpaero
push packets from aprs/ogn/X to glideport.aero

Note that glideport.aero currently displays different trackers for a single pilot as different tracks, and does not attempt to consolidate them.

Each pilot to be tracked needs to 
* Provide a tracker ID and IMEI identifier pair for each tracking source to whoever is running this service:
	* aprs ID - a callsign (of the form used by their APRS tracker e.g. KXXXXX-9)
	* OGN ID - typically an ICAO address
* Add device url(s) to their glideport.aero configuration, of the form ir_push:IMEI with their IMEI value(s) for each tracking source.

I suspect that the IMEI identifiers need to be different for different sources, i.e. if a pilot wishes to have both ogn and aprs trackers used, two different IMEI identifiers will be needed.

#### Usage

./x2gpaero/aprs2gp.py ~/tmp/sample_config.json

./x2gpaero/ogn2gp.py ~/tmp/sample_config.json


The config file is a json file (see [sample_config_structure.json](./sample_config_structure.json) for an example), with the following keys:
##### mandatory
* callsign - used to access the aprs server in read only mode; not needed for ogn.
* ids - a dictionary of ID : IMEI identifiers

##### optional
* verbose
* min_packet_dt - minimal time (seconds) between valid packets. For aprs this is typically set to a few seconds, for OGN use it should be set shorter.
* N_last_packets - number of recent packets kept to deduplicate. Defaults to 5.
* wait_between_checks - how often (seconds) to receive data ; 0.15 seems a reasonable choice. However, defaults to 1, so should be set to a value.
* max_consecutive_data_loss - the socket will be reset if no packets are received for this many consecutive cycles. Defaults to 3.
* socket_timeout - seconds. Defaults to twice the time between checks.
* print_info_every_x_seconds -  default to 1 sec.
* print_monitor_every_x_seconds  - defults to effectively off.


## P.S.
I've put some utils and notes about setting up a raspi with the code in  [./utils](./utils)
