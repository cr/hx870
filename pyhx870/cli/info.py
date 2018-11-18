# -*- coding: utf-8 -*-

import logging

import pyhx870
from .base import CliCommand
from ..memory import region_code_map
from ..protocol import ProtocolError

logger = logging.getLogger(__name__)


class InfoCommand(CliCommand):

    name = "info"
    help = "show info about connected device"

    def run(self):
        hx = pyhx870.get(self.args)
        if hx is None:
            logger.critical("No HX870 connected")
            return 10
        hx.init()
        try:
            fw = hx.get_firmware_version()
        except ProtocolError:
            logger.critical("Handset not in CP mode (MENU + ON)")
            return 11
        print(f"Firmware version: {fw}")

        region_code = ord(hx.read_config_memory(0x010f, 1))
        region = region_code_map[region_code]
        print(f"Region: {region} [{region_code:02x}]")

        atis_enabled_code = ord(hx.read_config_memory(0x00a2, 1))
        atis_enabled = "ENABLED" if atis_enabled_code == 1 else "DISABLED"
        print(f"ATIS function: {atis_enabled} [{atis_enabled_code:02x}]")

        mmsi, mmsi_status = hx.read_mmsi()
        print(f"MMSI: {mmsi}")
        print(f"MMSI status: {mmsi_status}")

        atis, atis_status = hx.read_atis()
        print(f"ATIS: {atis}")
        print(f"ATIS status: {atis_status}")

        return 0
