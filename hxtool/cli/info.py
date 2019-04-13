# -*- coding: utf-8 -*-

from logging import getLogger

import hxtool
from .base import CliCommand
from ..memory import region_code_map

logger = getLogger(__name__)


class InfoCommand(CliCommand):

    name = "info"
    help = "show device info"

    def run(self):
        hx = hxtool.get(self.args)
        if hx is None:
            return 10

        print(f"Model:\t{hx.brand} {hx.model}")
        print(f"Handle:\t{hx.handle}")
        print(f"Manufacturer:\t{hx.usb_vendor_name}")
        print(f"Serial device:\t{hx.tty}")

        if not hx.comm.cp_mode:
            logger.warning("For firmware and config information, device must be in CP mode (MENU + ON)")
            return 0

        fw = hx.comm.get_firmware_version()
        print(f"Firmware version: {fw}")

        fid = hx.comm.get_flash_id()
        if not hx.check_flash_id():
            logger.warning(f"Flash ID mismatch. {fid} not in {hx.flash_id}")
        print(f"Flash ID:\t{fid}")

        region_code = ord(hx.comm.read_config_memory(0x010f, 1))  # TODO: move to config
        region = region_code_map[region_code]
        print(f"Region:\t{region} [{region_code:02x}]")

        mmsi, mmsi_status = hx.config.read_mmsi()
        print(f"MMSI:\t{mmsi}")
        print(f"MMSI status:\t{mmsi_status}")

        atis_enabled_code = ord(hx.comm.read_config_memory(0x00a2, 1))  # TODO: mode to config
        atis_enabled = "ENABLED" if atis_enabled_code == 1 else "DISABLED"
        print(f"ATIS function:\t{atis_enabled} [{atis_enabled_code:02x}]")

        atis, atis_status = hx.config.read_atis()
        print(f"ATIS:\t{atis}")
        print(f"ATIS status:\t{atis_status}")

        return 0
