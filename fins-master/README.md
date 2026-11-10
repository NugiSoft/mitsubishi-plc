# fins

Partial implementation of Omron FINS protocol in Python.

This was orginally written during the days of Python 2.
Minor changes were made to port to Python 3 and pass tests.
There are probably still bytes/strings issues.

This software was used to talk to Omron PLCs over TCP/IP.
(The vendor-provided software was junk.)

The FINS class implements a subset of FINS commands in the following methods:

- memory_area_read()
- memory_area_write()
- clock_read()
- clock_write()

Run tests with the following command:

    $ python3 test_fins.py
