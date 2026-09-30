# -*- coding: utf-8 -*-

from logging import getLogger

import hxtool
from .base import CliCommand
from ..protocol import ProtocolError

logger = getLogger(__name__)


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

        parser.add_argument("--mmsi-counter",
                            help="write the MMSI update counter (left alone otherwise)",
                            type=int,
                            action="store")

        parser.add_argument("--atis-counter",
                            help="write the ATIS update counter (left alone otherwise)",
                            type=int,
                            action="store")

    def run(self):
        hx = hxtool.get(self.args)
        if hx is None:
            return 10

        if not hx.comm.cp_mode:
            logger.critical("Handset not in CP mode (MENU + ON)")
            return 11

        args = self.args
        if args.atis is None and args.mmsi is None and not args.reset \
                and args.mmsi_counter is None and args.atis_counter is None:
            mmsi, mmsi_counter = hx.config.read_mmsi()
            atis, atis_counter = hx.config.read_atis()
            print(f"MMSI: {mmsi} [counter {mmsi_counter}]")
            print(f"ATIS: {atis} [counter {atis_counter}]")
            return 0

        if args.reset:
            try:
                logger.info("Resetting MMSI")
                hx.config.write_mmsi(counter=args.mmsi_counter)
                logger.info("Resetting ATIS")
                hx.config.write_atis(counter=args.atis_counter)
            except ProtocolError as e:
                logger.error(e)
                return 12

        if args.atis is not None or (args.atis_counter is not None and not args.reset):
            try:
                atis = args.atis if args.atis is not None else programmed(hx.config.read_atis()[0])
                logger.info(f"New ATIS `{atis}`" if args.atis is not None else f"New ATIS counter {args.atis_counter}")
                hx.config.write_atis(atis, counter=args.atis_counter)
            except ProtocolError as e:
                logger.error(e)
                return 13

        if args.mmsi is not None or (args.mmsi_counter is not None and not args.reset):
            try:
                mmsi = args.mmsi if args.mmsi is not None else programmed(hx.config.read_mmsi()[0])
                logger.info(f"New MMSI `{mmsi}`" if args.mmsi is not None else f"New MMSI counter {args.mmsi_counter}")
                hx.config.write_mmsi(mmsi, counter=args.mmsi_counter)
            except ProtocolError as e:
                logger.error(e)
                return 14

        logger.info("Operation successful")
        return 0


def programmed(code: str):
    """The code as read from the device, or None if it is the factory placeholder"""
    return None if code.strip("F") == "" else code
