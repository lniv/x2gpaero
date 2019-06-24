# aprs2gpaero
push packets from aprs to glideport.aero
a child module for ogn traffic is included as well, but does not work yet, so the instructions below are specific to aprs traffic.

Note that glideport.aero currently displays different trackers for a single pilot as different tracks, and does not attempt to consolidate them.

Each pilot to be tracked needs to
* Provide a callsign (of the form used by their APRS tracker e.g. KXXXXX-9) and an IMEI identifier (typically of their cell phone).
* Add a device url to their glideport.aero configuration, of the form ir_push:IMEI with their IMEI value.

## Usage

./aprs2gpaero.py ~/tmp/sample_config.json

The config file is a json file (see [sample_config_structure.json](./sample_config_structure.json) for an example), with the following keys:
## mandatory
* callsign (used to access the aprs server in read only mode)
* ids - a dictionary of 'from' aprs packet : IMEI identifiers
## optional
* verbose
* wait_between_checks - how often (seconds) to receive data ; 0.15 seems a reasonable choice. However, defaults to 1, so should be set to a value.
* max_consecutive_data_loss - the socket will be reset if no packets are received for this many consecutive cycles. Defaults to 3.
* socket_timeout - seconds. Defaults to twice the time between checks.
* print_info_every_x_seconds -  default to 1 sec.
* print_monitor_every_x_seconds  - defults to effectively off.

## P.S.
I've put some utils and notes about setting up a raspi with the code in  [./utils](./utils)
