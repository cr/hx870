from logging import getLogger
from os.path import abspath

import hxtool
from . import ui
from .base import CliCommand
from ..srec import Image, SRecordError

logger = getLogger(__name__)


class FirmwareCommand(CliCommand):

    name = "firmware"
    help = "read or write the handset firmware"

    @staticmethod
    def setup_args(parser) -> None:

        action = parser.add_mutually_exclusive_group()
        action.add_argument("--readto",
                            help="read the firmware from the handset into this file, as S-records",
                            type=abspath,
                            metavar="FILE",
                            action="store")
        action.add_argument("--writefrom",
                            help="assess the firmware image in this file (S-records) against the handset, "
                                 "write nothing, and exit non-zero if it fails (see --really)",
                            type=abspath,
                            metavar="FILE",
                            action="store")

        parser.add_argument("--binary",
                            help="FILE is a flat binary image of the firmware area instead of S-records",
                            action="store_true")

        parser.add_argument("--really",
                            help="write the --writefrom image to the handset, whatever the assessment says "
                                 "(writing is untested on a radio so far)",
                            action="store_true")

        parser.add_argument("--reboot",
                            help="restart the handset at the end. Without it a read or write leaves the "
                                 "handset in flash mode, where it takes further firmware commands only",
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

        if self.args.readto is None and self.args.writefrom is None and not self.args.reboot:
            logger.critical("Specify --readto, --writefrom or --reboot")
            return 10

        try:
            if self.args.readto is not None:
                return self.read(hx)
            if self.args.writefrom is not None:
                return self.write(hx)
            return 0
        finally:
            if self.args.reboot:
                hx.reboot()
            elif hx.firmware.active:
                logger.info("Handset is left in flash mode. `hxtool firmware --reboot` restarts it")

    @staticmethod
    def log_placement(hx, image: Image) -> None:
        """A flat binary carries no addresses, so the log says where it lies"""
        start, size = image.segments[0].address, len(image.to_binary())
        flash = hx.firmware.flash_address(start)
        logger.info(f"Flat binary: {size} bytes for 0x{start:08x}..0x{start + size - 1:08x} "
                    f"(flash address 0x{flash:06x}..0x{flash + size - 1:06x})")

    def read(self, hx) -> int:
        logger.info("Reading firmware from handset")
        with ui.progress("Reading firmware", "bytes") as progress:
            image = hx.firmware.read_image(progress=progress)
        version = hx.firmware.image_version(image)

        if self.args.binary:
            logger.info(f"Writing firmware image, version {version}, as flat binary to `{self.args.readto}`")
            with open(self.args.readto, "wb") as f:
                f.write(image.to_binary())
            self.log_placement(hx, image)
            logger.info(f"To load it where it lies: rizin -a rx -b 32 -m 0x{image.segments[0].address:08x} "
                        f"{self.args.readto}")
            return 0

        # Erased flash is left out: a write erases the area and writes what the records hold
        image = image.without_erased()
        logger.info(f"Writing firmware image, version {version}, as S-records to `{self.args.readto}` "
                    f"({image.size} bytes in {len(image.segments)} segments)")
        with open(self.args.readto, "w", encoding="ascii", newline="\n") as f:
            f.write(image.to_srec())
        return 0

    def write(self, hx) -> int:
        logger.info(f"Reading firmware image from `{self.args.writefrom}`")
        with open(self.args.writefrom, "rb") as f:
            raw = f.read()
        if self.args.binary:
            image = hx.firmware.image_from_binary(raw)
            if image.segments:
                self.log_placement(hx, image)
        else:
            try:
                image = Image.from_srec(raw)
            except SRecordError as e:
                logger.critical(f"`{self.args.writefrom}` is not S-records ({e}). "
                                f"A flat binary image takes --binary")
                return 10

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
