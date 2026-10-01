from logging import getLogger
from os.path import abspath

import hxtool
from . import ui
from .base import CliCommand
from ..protocol import ProtocolError

logger = getLogger(__name__)


class ConfigCommand(CliCommand):

    name = "config"
    help = "read and write handset configuration"

    @staticmethod
    def setup_args(parser) -> None:

        parser.add_argument("-d", "--dump",
                            help="read config from handset and write to file",
                            type=abspath,
                            action="store")

        parser.add_argument("-f", "--flash",
                            help="read config from file and write to handset",
                            type=abspath,
                            action="store")

        parser.add_argument("--force",
                            help="flash despite config magic or region mismatch, and write the "
                                 "protected device state too (everything but magic and flash ID)",
                            action="store_true")

        parser.add_argument("--force-flashid",
                            help="write the flash ID from the image (changes the device's hardware identity)",
                            action="store_true")

    def run(self):
        hx = hxtool.get(self.args)
        if hx is None:
            return 10

        if not hx.comm.cp_mode:
            logger.critical("Handset not in CP mode (MENU + ON)")
            return 11

        if self.args.dump is None and self.args.flash is None:
            logger.critical("Specify --dump or --flash")
            return 10

        ret = 0

        if self.args.dump is not None:
            logger.info("Reading config flash from handset")
            try:
                with ui.progress("Reading config", "bytes") as progress:
                    data = hx.config.config_read(progress=progress)
            except ProtocolError as e:
                logger.error(e)
                ret = 10
            else:
                # Only touch the file once the read is complete
                logger.info(f"Writing config to `{self.args.dump}`")
                with open(self.args.dump, "wb") as f:
                    f.write(data)

        if self.args.flash is not None:
            with open(self.args.flash, "rb") as f:
                logger.info(f"Reading config data from `{self.args.flash}`")
                data = f.read()
                logger.info("Writing config to handset")
                try:
                    with ui.progress("Writing config", "bytes") as progress:
                        hx.config.config_write(data, force=self.args.force, write_flash_id=self.args.force_flashid,
                                               progress=progress)
                except ProtocolError as e:
                    logger.error(e)
                    ret = 10

        if ret == 0:
            logger.info("Operation successful")

        return ret
