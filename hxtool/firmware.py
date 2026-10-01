from typing import NamedTuple

from .progress import Progress
from .protocol import FirmwareProtocol, ProtocolError
from .srec import Image, Segment


class ImageCheck(NamedTuple):
    """One sanity check of a firmware image"""
    what: str
    passed: bool
    detail: str


class GenericHXFirmware:
    """
    Firmware flash of an HX style radio: where the firmware lies, and operations on whole
    images. Everything model specific is a class attribute.

    Images are hxtool.srec.Image: address segments, as the vendor's S-records give them.
    """

    # Firmware area (start, end-exclusive) and transfer chunk, from the write maps of the
    # vendor's updaters for the HX870 and the HX890, which agree. The HX891BT has no
    # updater; an image read from one fills the same area.
    AREA = (0xf40000, 0xff0000)
    CHUNK_SIZE = 0x80

    # The flash commands carry the low 24 bits of the MCU's addresses: the firmware area at
    # 0xF40000 is 0xFFF40000 to the MCU, and in the vendor's S-records.
    ADDRESS_MASK = 0x00ffffff
    ADDRESS_BASE = 0xff000000

    VERSION_LENGTH = 11  # the area starts with the version, blank padded, e.g. "  02.04    "
    CONTENT_LENGTH = 0x1000  # how far from the start of the area an image is looked at for content

    def __init__(self, protocol: FirmwareProtocol, flash_ids: list[str]):
        self.p = protocol
        self.flash_ids = flash_ids  # the IDs this model is known by, see the config class

    def flash_address(self, address: int) -> int:
        """The address the flash commands know an MCU address by"""
        return address & self.ADDRESS_MASK

    def _in_flash(self, image: Image) -> Image:
        """The image by its flash addresses"""
        return Image(Segment(self.flash_address(address), data) for address, data in image.segments)

    def _outside_area(self, flash: Image) -> list[Segment]:
        start, end = self.AREA
        return [segment for segment in flash.segments
                if segment.address < start or segment.address + len(segment.data) > end]

    @staticmethod
    def _span(segment: Segment) -> str:
        return f"0x{segment.address:06x}..0x{segment.address + len(segment.data) - 1:06x}"

    def image_from_binary(self, data: bytes) -> Image:
        """A flat image, which has no addresses of its own, laid at the start of the firmware area"""
        return Image.from_binary(data, self.ADDRESS_BASE | self.AREA[0])

    def read_image(self, progress: Progress | None = None) -> Image:
        """
        Read the whole firmware area, as one segment at its MCU address and under the
        flash ID of the radio. progress is called with (bytes done, bytes total).
        """
        start, end = self.AREA
        self.p.enter_flash_mode()
        data = bytearray()
        for offset in range(start, end, self.CHUNK_SIZE):
            if progress:
                progress(offset - start, end - start)
            data += self.p.read(offset, min(self.CHUNK_SIZE, end - offset))
        if progress:
            progress(end - start, end - start)
        return Image([Segment(self.ADDRESS_BASE | start, bytes(data))], header=self.p.flash_id or "")

    def write_image(self, image: Image, progress: Progress | None = None):
        """
        Erase the firmware area and write an image to it: every chunk the image has bytes
        in, filled up with 0xFF, erased flash. The other chunks stay erased. The image is
        written as given, see check_image(); only one that leaves the area is refused.
        """
        start, end = self.AREA
        flash = self._in_flash(image)
        outside = self._outside_area(flash)
        if outside:
            raise ProtocolError(f"Firmware image at {self._span(outside[0])} lies outside the "
                                f"firmware area 0x{start:06x}..0x{end - 1:06x}")
        chunks = sorted({offset for address, data in flash.segments
                         for offset in range(address - address % self.CHUNK_SIZE, address + len(data),
                                             self.CHUNK_SIZE)})
        total = len(chunks) * self.CHUNK_SIZE
        self.p.enter_flash_mode()
        self.p.erase()
        for n, offset in enumerate(chunks):
            if progress:
                progress(n * self.CHUNK_SIZE, total)
            self.p.write(offset, flash.read(offset, self.CHUNK_SIZE))
        if progress:
            progress(total, total)

    def image_version(self, image: Image) -> str:
        """The version an image names at the start of the firmware area, e.g. '02.04'"""
        version = self._in_flash(image).read(self.AREA[0], self.VERSION_LENGTH)
        return version.decode("ascii", "replace").strip("� ")

    def check_image(self, image: Image) -> list[ImageCheck]:
        """
        What an image tells about its fitness for this model: that it lies within the
        firmware area, names a version, carries one of the model's flash IDs (in its header
        record or its data), and has content at the start of the area. Nothing is sent to
        the radio.
        """
        start, end = self.AREA
        area = f"0x{start:06x}..0x{end - 1:06x}"
        flash = self._in_flash(image)
        outside = self._outside_area(flash)
        version = self.image_version(image)
        in_header = [flash_id for flash_id in self.flash_ids if flash_id in image.header]
        in_data = [flash_id for flash_id in self.flash_ids
                   if any(flash_id.encode("ascii") in data for _, data in flash.segments)]
        has_content = any(b != 0xff for b in flash.read(start, self.CONTENT_LENGTH))
        return [
            ImageCheck("area", not outside,
                       f"{self._span(outside[0])} lies outside {area}" if outside
                       else f"{flash.size} bytes, within {area}"),
            ImageCheck("version", version.replace(".", "").isdigit() and "." in version,
                       f"image version {version!r}" if version else "no version string at the start of the area"),
            ImageCheck("model", bool(in_header or in_data),
                       f"header names the flash ID {in_header[0]!r}" if in_header
                       else f"carries the flash ID {in_data[0]!r}" if in_data
                       else f"carries none of this model's flash IDs {self.flash_ids}"),
            ImageCheck("content", has_content,
                       "starts with code and tables" if has_content else "nothing but erased flash at the start"),
        ]
