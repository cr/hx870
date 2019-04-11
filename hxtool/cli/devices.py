# -*- coding: utf-8 -*-

import logging

from .base import CliCommand
from ..device import enumerate

logger = logging.getLogger(__name__)


class DevicesCommand(CliCommand):

    name = "devices"
    help = "enumerate detected devices"

    def run(self):
        devices = enumerate(add_simulator=self.args.simulator)
        if len(devices) > 0:
            for device in devices:
                mode = "unknown mode (BE CAREFUL)"
                if device.comm.nmea_mode:
                    mode = "NMEA mode"
                if device.comm.cp_mode:
                    mode = "CP mode"
                if not device.comm.hx_hardware:
                    mode = "unknown hardware (BE CAREFUL)"
                print(f"[{devices.index(device)}]\t{device.tty}\t{device.brand}\t{device.model}\t{mode}")
            return 0

        else:
            logger.critical("No device detected. Is it connected?")
            return 10
