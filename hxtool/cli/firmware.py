from logging import getLogger
from os.path import abspath

import hxtool
from . import ui
from .base import CliCommand

logger = getLogger(__name__)


class FirmwareCommand(CliCommand):

    name = "firmware"
    help = "read or write the handset firmware"

    @staticmethod
    def setup_args(parser) -> None:

        action = parser.add_mutually_exclusive_group()
        action.add_argument("--readto",
                            help="read the firmware from the handset into this file",
                            type=abspath,
                            metavar="FILE",
                            action="store")
        action.add_argument("--writefrom",
                            help="assess the firmware image in this file against the handset, write nothing, "
                                 "and exit non-zero if it fails (see --really)",
                            type=abspath,
                            metavar="FILE",
                            action="store")

        parser.add_argument("--really",
                            help="write the --writefrom image to the handset, whatever the assessment says "
                                 "(writing is untested on a radio so far)",
                            action="store_true")

    def run(self):
        hx = hxtool.get(self.args)
        if hx is None:
            return 10

        if not hx.comm.cp_mode:
            logger.critical("Handset not in CP mode (MENU + ON)")
            return 11

        if hx.firmware is None:
            logger.critical(f"Firmware functions are not supported by {hx.handle}")
            return 10

        if self.args.readto is None and self.args.writefrom is None:
            logger.critical("Specify --readto or --writefrom")
            return 10

        try:
            if self.args.readto is not None:
                return self.read(hx)
            return self.write(hx)
        finally:
            # A transfer leaves the radio in flash mode, and the way out is a reboot
            if hx.firmware.active:
                hx.reboot()

    def read(self, hx) -> int:
        logger.info("Reading firmware from handset")
        with ui.progress("Reading firmware", "bytes") as progress:
            image = hx.firmware.read_image(progress=progress)
        logger.info(f"Writing firmware image, version {hx.firmware.image_version(image)}, to `{self.args.readto}`")
        with open(self.args.readto, "wb") as f:
            f.write(image)
        return 0

    def write(self, hx) -> int:
        logger.info(f"Reading firmware image from `{self.args.writefrom}`")
        with open(self.args.writefrom, "rb") as f:
            image = f.read()

        # The assessment is advice: --really writes the image whatever it says
        checks = hx.firmware.check_image(image)
        for check in checks:
            (logger.info if check.passed else logger.error)(f"{check.what}: {check.detail}")
        logger.info(f"Handset runs firmware {hx.config.firmware_version().strip()!r}, "
                    f"image is {hx.firmware.image_version(image)!r}")
        fit = all(check.passed for check in checks)

        if not self.args.really:
            if not fit:
                logger.warning("Nothing written. Do not write this image to the handset, it failed the assessment "
                               "(--really writes it regardless)")
                return 12
            logger.warning("Nothing written. Run again with --really to write this image to the handset")
            return 0

        if not fit:
            logger.warning("Image failed the assessment, writing it regardless")
        logger.warning("Writing firmware to handset (untested on a radio so far)")
        with ui.progress("Writing firmware", "bytes") as progress:
            hx.firmware.write_image(image, progress=progress)
        return 0
