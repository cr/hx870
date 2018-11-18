# -*- coding: utf-8 -*-

import logging
import time

from .base import CliCommand
import pyhx870

logger = logging.getLogger(__name__)


class NmeaCommand(CliCommand):

    name = "nmea"
    help = "dump NMEA live data"

    def run(self):
        hx = pyhx870.get(self.args)
        if hx is None:
            logger.error("No HX870 connected")
            return 10
        hx.init()
        if hx.cp_mode:
            logger.error("Handset in CP mode, reboot to regular mode")
            return 10
        try:
            print_nmea(hx)
        except KeyboardInterrupt:
            pass
        return 0


def nmea_dump(h):
    while True:
        if h.available() > 0:
            yield h.read_line().decode("ascii").rstrip("\r\n")
        else:
            time.sleep(0.02)

def print_nmea(h):
    for l in nmea_dump(h):
        print(l)
