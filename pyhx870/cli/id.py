# -*- coding: utf-8 -*-

import logging

from .base import CliCommand
import pyhx870
from ..protocol import ProtocolError

logger = logging.getLogger(__name__)


class IdCommand(CliCommand):

    name = "id"
    help = "MMSI and ATIS setup"

    @staticmethod
    def setup_args(parser) -> None:

        parser.add_argument("-a", "--atis",
                            help="write ATIS to handset",
                            type=str,
                            action="store")

        parser.add_argument("-m", "--mmsi",
                            help="write MMSI to handset",
                            type=str,
                            action="store")

        parser.add_argument("-r", "--reset",
                            help="reset MMSI and ATIS programming",
                            action="store_true")

    def run(self):
        hx = pyhx870.get(self.args)
        if hx is None:
            logger.critical("No HX870 connected")
            return 10
        hx.init()
        try:
            _ = hx.get_firmware_version()
        except ProtocolError:
            logger.critical("Handset not in CP mode (MENU + ON)")
            return 11

        if self.args.atis is None and self.args.mmsi is None and not self.args.reset:
            mmsi, mmsi_status = hx.read_mmsi()
            atis, atis_status = hx.read_atis()
            print(f"MMSI: {mmsi} [{mmsi_status}]")
            print(f"ATIS: {atis} [{atis_status}]")
            return 0

        if self.args.reset:
            try:
                logger.info("Resetting MMSI")
                hx.write_mmsi()
                logger.info("Resetting ATIS")
                hx.write_atis()
            except ProtocolError as e:
                logger.error(e)
                return 12

        if self.args.atis is not None:
            try:
                logger.info(f"New ATIS `{self.args.atis}`")
                hx.write_atis(self.args.atis)
            except ProtocolError as e:
                logger.error(e)
                return 13

        if self.args.mmsi is not None:
            try:
                logger.info(f"New MMSI `{self.args.mmsi}`")
                hx.write_mmsi(self.args.mmsi)
            except ProtocolError as e:
                logger.error(e)
                return 14

        return 0
