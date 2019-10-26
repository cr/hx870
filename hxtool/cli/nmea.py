# -*- coding: utf-8 -*-

from logging import getLogger
import sys
from time import sleep

import hxtool
from .base import CliCommand

logger = getLogger(__name__)


class NmeaCommand(CliCommand):

    name = "nmea"
    help = "dump NMEA live data"

    def run(self):

        hx = hxtool.get(self.args)
        if hx is None:
            return 10

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
        if h.comm.available() > 0:
            yield h.comm.read_line().decode("ascii")
        else:
            sleep(0.02)


def print_nmea(h):
    for l in nmea_dump(h):
        sys.stdout.write(l)
        sys.stdout.flush()
