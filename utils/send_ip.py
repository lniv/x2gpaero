#!/usr/bin/python3
"""
hacked from combining https://www.raspberrypi.org/forums/viewtopic.php?t=178572 and https://github.com/TheOliver/send-email-with-device-ip-address
"""

import socket
import smtplib
import os
import sys
import json
from urllib.request import urlopen

# Import secret informations from file 'secrets.py'
from secrets import sender_address
from secrets import sender_password
from secrets import sender_server
from secrets import sender_port
from secrets import recipient_address 

old_ip_filename = '/home/pi/old_ip_message.txt'

def get_device_ip_address():

    try: 
        gw = os.popen("ip -4 route show default").read().split()
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((gw[2], 0))
        ipaddr = s.getsockname()[0]
        gateway = gw[2]
        host = socket.gethostname()
        local_result = "IP:\t\t" + ipaddr + "\nGateway:\t" + gateway + "\nHost:\t\t" + host
        
        ip = urlopen('http://httpbin.org/ip').read()
        ip = ip.decode('utf-8')
        ip = json.loads(ip)
        publicDomain, alias, addresslist = socket.gethostbyaddr(ip['origin'].split(',')[0])

        remote_result = 'publicDomain\t{:}\nalias\t{:}\naddresslist\t{:}'.format(publicDomain, alias, addresslist)

        
        return local_result + '\n' + remote_result
    except Exception as e:
        return "Could not detect ip address due to {:}".format(e)

def send_email(text):
    try:
        message = "From: " + sender_address + "\nTo: " + recipient_address + "\nSubject: aprs2gpaero raspberrypi information\n\n" + text 

        server = smtplib.SMTP(sender_server, sender_port)
        server.ehlo()
        server.starttls()
        server.login(sender_address, sender_password)
        server.sendmail(sender_address, recipient_address, message)
        server.close()
        print("Message sent:\n", message)

    except Exception as e:
        print("failed to send email due to {:}".format(e))

if __name__ == '__main__':

    message = get_device_ip_address()
    if os.path.exists(old_ip_filename):
        with open(old_ip_filename, 'r') as f:
            lines = ''.join(f.readlines())
            if lines == message:
                print('no change')
                need_to_send= False
            else:
                print ('old:' +  lines + '\nnew'  + message)
                need_to_send = True
    else:
        need_to_send = True
    with open(old_ip_filename, 'w') as f:
        f.write(message)
    print('message\n' + message)
    if need_to_send:
        print("Sending email, can take a while.")
        send_email(message)
        print("Done.")
    else:
        print('No changes, so no need to send this')

sys.exit()
