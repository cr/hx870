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
    what = "firmware"  # the area of the flash this command is about, as the log lines call it
    writable = True

    @staticmethod
    def area(hx):
        """The model's handler for the area"""
        return hx.firmware

    @classmethod
    def setup_args(cls, parser) -> None:

        action = parser.add_mutually_exclusive_group()
        action.add_argument("--readto",
                            help=f"read the {cls.what} from the handset into this file, as S-records",
                            type=abspath,
                            metavar="FILE",
                            action="store")
        if cls.writable:
            action.add_argument("--writefrom",
                                help="assess the firmware image in this file (S-records) against the handset, "
                                     "write nothing, and exit non-zero if it fails (see --really)",
                                type=abspath,
                                metavar="FILE",
                                action="store")
            parser.add_argument("--really",
                                help="write the --writefrom image to the handset, whatever the assessment says "
                                     "(writing is untested on a radio so far)",
                                action="store_true")

        parser.add_argument("--binary",
                            help=f"FILE is a flat binary image of the {cls.what} area instead of S-records",
                            action="store_true")

        parser.add_argument("--reboot",
                            help="restart the handset when the command went through. Without it the handset "
                                 "is left in flash mode, where it takes firmware and bootrom commands only",
                            action="store_true")

    def run(self):
        hx = hxtool.get(self.args)
        if hx is None:
            return 10

        if not hx.comm.cp_mode and not hx.comm.flash_mode:
            logger.critical("Handset not in CP mode (MENU + ON)")
            return 11

        if self.area(hx) is None:
            logger.critical(f"No {self.what} functions for {hx.handle}")
            return 10

        writefrom = self.args.writefrom if self.writable else None
        if self.args.readto is None and writefrom is None and not self.args.reboot:
            logger.critical(f"Specify --readto{', --writefrom' if self.writable else ''} or --reboot")
            return 10

        result = 0
        if self.args.readto is not None:
            result = self.read(hx)
        elif writefrom is not None:
            result = self.write(hx)

        if self.args.reboot and result == 0:
            hx.reboot()
        elif hx.comm.flash_mode:
            logger.info(f"Handset is left in flash mode. `hxtool {self.name} --reboot` restarts it")
        return result

    def log_placement(self, hx, image: Image) -> None:
        """A flat binary carries no addresses, so the log says where it lies"""
        start, size = image.segments[0].address, image.size
        flash = self.area(hx).flash_address(start)
        logger.info(f"Flat binary: {size} bytes for 0x{start:08x}..0x{start + size - 1:08x} "
                    f"(flash address 0x{flash:06x}..0x{flash + size - 1:06x})")

    def read(self, hx) -> int:
        logger.info(f"Reading {self.what} from handset")
        with ui.progress(f"Reading {self.what}", "bytes") as progress:
            image = self.area(hx).read_image(progress=progress)
        version = self.area(hx).image_version(image)
        image_name = f"{self.what} image, version {version}" if version else f"{self.what} image"

        if self.args.binary:
            logger.info(f"Writing {image_name} as flat binary to `{self.args.readto}`")
            with open(self.args.readto, "wb") as f:
                f.write(image.to_binary())
            self.log_placement(hx, image)
            return 0

        # Erased flash is left out: a write erases the area and writes what the records hold
        image = image.without_erased()
        logger.info(f"Writing {image_name} as S-records to `{self.args.readto}` "
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
        # A handset found in flash mode does not tell its version
        running = repr(hx.config.firmware_version().strip()) if hx.comm.cp_mode else "unknown (flash mode)"
        logger.info(f"Handset runs firmware {running}, image is {hx.firmware.image_version(image)!r}")
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
