# -*- coding: utf-8 -*-

import logging
import os

from .base import CliCommand
import hxtool
from ..protocol import ProtocolError

logger = logging.getLogger(__name__)


class InfoCommand(CliCommand):

    name = "config"
    help = "read and write handset configuration"

    @staticmethod
    def setup_args(parser) -> None:

        parser.add_argument("-d", "--dump",
                            help="read config from handset and write to file",
                            type=os.path.abspath,
                            action="store")

        parser.add_argument("-f", "--flash",
                            help="read config from file and write to handset",
                            type=os.path.abspath,
                            action="store")

    def run(self):
        hx = hxtool.get(self.args)
        if hx is None:
            logger.error("No device detected. Connect device or specify --tty")
            return 10

        if not hx.comm.cp_mode:
            logger.critical("Handset not in CP mode (MENU + ON)")
            return 11

        if self.args.dump is None and self.args.flash is None:
            logger.critical("Specify --dump or --flash")
            return 10

        ret = 0

        if self.args.dump is not None:
            # TODO: warn on flash ID mismatch
            with open(self.args.dump, "wb") as f:
                logger.info("Reading config flash from handset")
                try:
                    data = hx.config.config_read()
                    logger.info(f"Writing config to `{self.args.dump}`")
                    f.write(data)
                except ProtocolError as e:
                    logger.error(e)
                    ret = 10

        if self.args.flash is not None:
            # TODO: add --really safeguard on flash ID mismatch
            with open(self.args.flash, "rb") as f:
                logger.info(f"Reading config data from `{self.args.flash}`")
                data = f.read()
                logger.info("Writing config to handset")
                try:
                    hx.config.config_write(data)
                except ProtocolError as e:
                    logger.error(e)
                    ret = 10

        if ret == 0:
            logger.info("Operation successful")

        return ret
