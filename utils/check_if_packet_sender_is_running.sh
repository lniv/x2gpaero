#!/bin/bash
# check if the code sending aprs packets to gpaero is alive, if not, restart it
if pgrep -x aprs2gpaero.py >/dev/null
then
	echo "it's running"
else
	echo "found stopped, restarting"
	aprs2gpaero /home/pi/aprs2gp_config_1.json >> /dev/null 2>&1 &
	echo "started"
fi
