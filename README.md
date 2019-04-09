# aprs2gpaero
push packets from aprs to gliderport.aero

minimal usage in a shell

./aprs2gpaero.py ~/tmp/sample_config.json

The config file is a json file, with the following keys:
## mandatory
* callsign
* ids - a dictionary of 'from' aprs packet : IMEI identifiers
## optional
* verbose
* wait_between_checks - how often (seconds) to receive data ; 0.15 seems a reasonable choice.
* max_consecutive_data_loss - the socket will be reset if no packets are received for this many consecutive cycles.

See [sample_config_structure](./sample_config_structure.json) for an example.