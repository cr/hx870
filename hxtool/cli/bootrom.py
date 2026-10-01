from .firmware import FirmwareCommand


class BootromCommand(FirmwareCommand):
    """The firmware command's reading, for the boot block above the firmware area"""

    name = "bootrom"
    help = "read the handset boot ROM"
    what = "boot ROM"
    writable = False

    @staticmethod
    def area(hx):
        return hx.bootrom
