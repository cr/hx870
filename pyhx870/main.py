#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import coloredlogs
import IPython
import logging
import time

from . import HX870, Message


coloredlogs.DEFAULT_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
coloredlogs.install(level="DEBUG")
logger = logging.getLogger(__name__)


def wait_for_tty(timeout=60):
    timeout_time = time.time() + timeout
    while time.time() < timeout_time:
        try:
            return HX870("/dev/tty.usbmodem1411")
        except:
            time.sleep(0.1)
            pass

def nmea_dump(h):
    rest = ""
    while True:
        if h.available() > 0:
            yield h.read_line().decode("ascii").rstrip("\r\n")
        else:
            time.sleep(0.02)

def print_nmea(h):
    for l in nmea_dump(h):
        print(l)

def main():
    with open("HX870/hx870_factory_reset.dat", "rb") as f:
        o = f.read()
    with open("HX870/orig eu fw202.dat", "rb") as f:
        e = f.read()
    h = wait_for_tty()
    h.init()
    # h.sync()
    IPython.embed()
