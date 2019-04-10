# -*- coding: utf-8 -*-

import logging
import time

from .base import CliCommand
from ..device import enumerate

logger = logging.getLogger(__name__)


class NmeaCommand(CliCommand):

    name = "nmea"
    help = "dump NMEA live data"

    def run(self):

        try:
            hx = enumerate(force_device=self.args.tty, force_model=self.args.model)[0]
        except IndexError:
            logger.critical("No device to work with")
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
