# -*- coding: utf-8 -*-

import logging
import os

from .base import CliCommand
import pyhx870
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
        hx = pyhx870.get(self.args)
        if hx is None:
            logger.critical("No HX870 connected")
            return 10
        hx.init()
        if not hx.cp_mode:
            logger.critical("Handset not in CP mode (MENU + ON)")
            return 11

        if self.args.dump is None and self.args.flash is None:
            logger.critical("Specify --dump or --flash")
            return 10

        ret = 0

        if self.args.dump is not None:
            with open(self.args.dump, "wb") as f:
                logger.info("Reading config flash from handset")
                try:
                    data = hx.config_read()
                    logger.info(f"Writing config to `{self.args.dump}`")
                    f.write(data)
                except ProtocolError as e:
                    logger.error(e)
                    ret = 10

        if self.args.flash is not None:
            with open(self.args.write, "rb") as f:
                logger.info("Reading config data from `{self.args.flash}`")
                data = f.read()
                logger.info(f"Writing config to handset")
                try:
                    hx.config_write(data)
                except ProtocolError as e:
                    logger.error(e)
                    ret = 10

        return ret
