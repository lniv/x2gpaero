originally written during development, updated following name change and making pipable.
general:
	started from a fresh raspabian image (not noobs - got impatient) around April 2019.
	edited files for a headless start, including ssh server; i don't recall what i had to do, but wasn't hard to find e.g. https://www.raspberrypi.org/documentation/configuration/wireless/headless.md - seems just putting a file called "ssh" into the root folder was enough.
	installed (using apt) screen, vim, ipython (but the aprs code was running before these; this is just for convenient maintenance)
x2gpaero:
	when in /home/pi/code do 
		git clone https://github.com/lniv/x2gpaero.git
		cd x2gpaero
		pip3 install -e .
	create a config file
	
ip notification by email - following https://www.raspberrypi.org/forums/viewtopic.php?t=65010i
	modifying the python script in one of the commens.
	sudo apt-get install ssmtp (for trying mail)
	got another code, variation of the same thing, but google objects to the use
	try nullmailer (which removes ssmtpi) - no go.
	turn on access for less secure devices on the violetcave gmail account.
		seems to work now
restarting code if it died for some reason
	created a minimal script, added to cron (it's in utils)

total additions to crontab (using crontab -e) (includes emailing ip, starting code at boot and restarting it if it died):
	*/10 * * * * python3 /home/pi/code/ip_mailing/send_ip.py
	*/10 * * * * /home/pi/code/misc/check_if_packet_sender_is_running.sh
	@reboot python3 /home/pi/code/ip_mailing/send_ip.py
	@reboot aprs2gpaero /home/pi/aprs2gp_config_1.json

