'''
crude unit tests
note - for various reasons it's annoying to actually install pytest, requests-mock, so for now i'll do some of the setup/teardown manually, or not bother.
'''

from functools import partial
import requests

def fake_post(url, json=None, timeout = None, good_response = True, timing_out = False):
	'''
	fake requests.post
	'''
	print(f'faking connecttion to {url} with json={json} and timeout = {timeout}; should be good = {good_response}, shoudl we time out = {timing_out}')
	mock_response = requests.Response()
	mock_response.status_code = 200 if good_response else 404
	if timing_out:
		raise requests.exceptions.ConnectTimeout
	return mock_response


def test_uploader():
	
	import logging
	from x2gpaero import aprs2gp
	
	# not really needed, and would be taken care of when using a proper fixture
	original_post = aprs2gp.requests.post
	
	print('trying a good one')
	aprs2gp.requests.post = partial(fake_post, good_response = True, timing_out = False)
	
	aprs2gp.upload_packet_to_gpaero(logging.getLogger('test'), {'x' : 4}, 5.0)
	
	print('and now a bad response')
	aprs2gp.requests.post = partial(fake_post, good_response = False, timing_out = False)
	try:
		aprs2gp.upload_packet_to_gpaero(logging.getLogger('test'), {'x' : 4}, 5.0)
	except requests.exceptions.HTTPError:
		print('ok')

	print('and now faking timing out')
	aprs2gp.requests.post = partial(fake_post, good_response = True, timing_out = True)
	try:
		aprs2gp.upload_packet_to_gpaero(logging.getLogger('test'), {'x' : 4}, 5.0)
	except requests.exceptions.ConnectTimeout:
		print('this is ok')

	print('clean up')
	aprs2gp.requests.post = original_post


def test_upload_queue():
	'''
	test starting the uploader in a separate thread, sending it some stuff and how it handles bad responses etc.
	'''
	import logging
	logging.basicConfig(level=logging.DEBUG)

	import time
	from queue import Queue
	from threading import Thread
	
	
	
	from x2gpaero import aprs2gp
	original_post = aprs2gp.requests.post

	for description, post_f, expected_q_size in  (\
				('good packet upload', partial(fake_post, good_response = True, timing_out = False), 0),
				('packet always timing out', partial(fake_post, good_response = True, timing_out = True), 3),
				('packet raising error', partial(fake_post, good_response = False, timing_out = False), 0)):

		print(f'\n\ntesting {description}')
		packets_queue = Queue(maxsize = 7)
		aprs2gp.requests.post = post_f

		# using a very short upload delay (0.01) to get a few cycles from the timing out case; it's harmless for the others.
		fake_upload_thread = Thread(target = aprs2gp.packet_uploader, daemon = True, args =(packets_queue, 5.0, 2.0, 0.01))
		fake_upload_thread.start()

		# this should be ignored; log message, but that's it.
		packets_queue.put({'a' : 0, 'v' : 2})
		# this, should not. (and make it a double)
		packets_queue.put({'Version' : 2.0, 'Events' : [{'imei' : 7, 'blah' : 888},]})
		packets_queue.put({'Version' : 2.0, 'Events' : [{'imei' : 7, 'blah' : 889},]})
		packets_queue.put({'Version' : 2.0, 'Events' : [{'imei' : 7, 'blah' : 890},]})

		time.sleep(2)
		packets_queue.put('stop')
		fake_upload_thread.join(timeout = 5)  # timed so i can see the stop on the one where we're timing out.
		assert packets_queue.qsize() == expected_q_size, f'expected to have {expected_q_size} in queue but have {packets_queue.qsize()}'

	print('clean up')
	aprs2gp.requests.post = original_post
