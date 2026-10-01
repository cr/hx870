from logging import getLogger

from .memory import unpack_waypoint
from .progress import Progress
from .protocol import GenericHXProtocol, ProtocolError

logger = getLogger(__name__)


def _unprotected(start, end, skipped):
    """The sub-ranges of [start, end) that are not covered by any of the skipped ranges"""
    pieces = [(start, end)]
    for s_start, s_end in skipped:
        pieces = [piece for a, b in pieces
                  for piece in ((a, min(b, s_start)), (max(a, s_end), b)) if piece[0] < piece[1]]
    return sorted(pieces)


def _counter_byte(counter, what: str) -> bytes:
    if type(counter) is not int or not 0 <= counter <= 0xff:
        raise ProtocolError(f"Invalid {what} update counter")
    return bytes([counter])


class GenericHXConfig:
    """
    Config memory of an HX style radio. Everything model specific is a class
    attribute; subclasses only override attributes, not methods.
    """

    CONFIG_MAGIC = 0xffff  # first and last two bytes of config memory, big endian
    FLASH_ID = ["AM000A"]  # hardware IDs this model is known by

    CHUNK_SIZE = 0x40  # bytes per transfer
    CONFIG_SIZE = 0x8000

    MMSI_OFFSET = 0x00b0  # 10 nibbles BCD, then the update counter byte
    ATIS_CODE_OFFSET = 0x00b6  # 10 nibbles BCD, then the update counter byte
    ATIS_ENABLED_OFFSET = 0x00a2
    FLASH_ID_OFFSET = 0x0100
    FLASH_ID_RANGE = (0x0100, 0x010f)  # flash ID and its padding
    REGION_CODE_OFFSET = 0x010f
    FIRMWARE_VERSION_OFFSET = None  # None: the radio answers #CVRRQ instead
    VARIANT_OFFSET = None  # None: no variant name in config memory
    VARIANT_LENGTH = 14
    WAYPOINT_OFFSET = 0x4300  # None: no waypoints
    WAYPOINT_COUNT = 200

    # Ranges (start, end) a config write leaves alone unless forced: device
    # identity and state that the firmware maintains. The magic at both ends
    # and the flash ID range are protected separately.
    # The vendor tool leaves the same ranges alone (USB capture of its HX870 config
    # write), except for the last turned off block, which it writes.
    PROTECTED_RANGES = [
        (0x000f, 0x0010),  # always 0x00
        (0x0078, 0x0080),  # model name of channel group 1
        (0x0088, 0x0090),  # model name of channel group 2
        (0x0098, 0x00a0),  # model name of channel group 3
        (0x00a8, 0x00b0),  # model name of channel group 4
        (0x0110, 0x0120),  # radio last turned off: timestamp and position
        (0x0280, 0x0300),  # unknown, in the preset list page
    ]

    REGION_CODE_US = 0xff
    REGION_CODES = {
        0: "INTERNATIONAL",
        1: "UNITED KINGDOM",
        2: "BELGIUM",
        3: "NETHERLAND",
        4: "SWEDEN",
        5: "GERMANY",
        255: "NONE",
    }

    def __init__(self, protocol: GenericHXProtocol):
        self.p = protocol

    def config_read(self, progress: Progress | None = None) -> bytes:
        """Read the whole config memory; progress is called with (bytes done, bytes total)"""
        config_data = b''
        for offset in range(0x0000, self.CONFIG_SIZE, self.CHUNK_SIZE):
            if progress:
                progress(offset, self.CONFIG_SIZE)
            config_data += self.p.read_config_memory(offset, self.CHUNK_SIZE)
        if progress:
            progress(self.CONFIG_SIZE, self.CONFIG_SIZE)
        return config_data

    def magic_ranges(self):
        return [(0x0000, 0x0002), (self.CONFIG_SIZE - 2, self.CONFIG_SIZE)]

    def _config_write_precheck(self, data, force):
        if len(data) != self.CONFIG_SIZE:
            raise ProtocolError(f"Unexpected config data size {len(data)}, expected {self.CONFIG_SIZE}")
        magic = self.p.read_config_memory(0x0000, 2)
        magic_end = self.p.read_config_memory(self.CONFIG_SIZE - 2, 2)
        if magic != data[:2] or magic_end != data[-2:]:
            if not force:
                raise ProtocolError("Unexpected config magic in device")
            logger.warning("Ignoring config magic mismatch. Flashing anyway")
        region = ord(self.p.read_config_memory(self.REGION_CODE_OFFSET, 1))
        region_is_us = region == self.REGION_CODE_US
        data_is_us = data[self.REGION_CODE_OFFSET] == self.REGION_CODE_US
        if region_is_us != data_is_us:
            if not force:
                raise ProtocolError("Region mismatch")
            logger.warning("Ignoring region mismatch. Flashing anyway")

    def config_write(self, data, force=False, write_flash_id=False, progress: Progress | None = None):
        """
        Write a config image to the device, leaving the device's identity alone:
        the magic is never written, the flash ID only with write_flash_id, and
        the model's other protected ranges only with force. force also turns
        the magic and region checks into warnings.
        progress is called with (bytes done, bytes total).
        """
        self._config_write_precheck(data, force)
        skipped = self.magic_ranges()
        if not write_flash_id:
            skipped.append(self.FLASH_ID_RANGE)
        else:
            logger.warning(f"Writing flash ID {self.flash_id()!r} -> {self._flash_id_of(data)!r}")
        if not force:
            skipped += self.PROTECTED_RANGES
        for offset in range(0, self.CONFIG_SIZE, self.CHUNK_SIZE):
            if progress:
                progress(offset, self.CONFIG_SIZE)
            for start, end in _unprotected(offset, offset + self.CHUNK_SIZE, skipped):
                self.p.write_config_memory(start, data[start:end])
        if progress:
            progress(self.CONFIG_SIZE, self.CONFIG_SIZE)

    def _flash_id_of(self, image) -> str:
        """The flash ID stored in a config image"""
        start, end = self.FLASH_ID_RANGE
        return image[start:end].rstrip(b"\x00\xff").decode("ascii", errors="replace")

    def flash_id(self) -> str:
        start, end = self.FLASH_ID_RANGE
        return self.p.read_config_memory(start, end - start).rstrip(b"\x00\xff").decode("ascii", errors="replace")

    def check_flash_id(self) -> bool:
        fid = self.flash_id()
        if fid in self.FLASH_ID:
            logger.debug("Device reported expected flash ID %s", fid)
            return True
        logger.debug(f"Flash ID mismatch. Device reported {fid}, expected {self.FLASH_ID}")
        return False

    def firmware_version(self) -> str:
        if self.FIRMWARE_VERSION_OFFSET is None:
            return self.p.get_firmware_version()
        data = self.p.read_config_memory(self.FIRMWARE_VERSION_OFFSET, 3).hex()
        return (data[1] if data.startswith("0") else data[0:2]) + "." + data[2:4]

    def variant(self):
        """The variant name stored in config memory, or None if the model has none"""
        if self.VARIANT_OFFSET is None:
            return None
        return self.p.read_config_memory(self.VARIANT_OFFSET, self.VARIANT_LENGTH).rstrip(b"\xff").decode()

    def read_waypoints(self):
        if self.WAYPOINT_OFFSET is None:
            raise ProtocolError(f"Waypoints unsupported by {type(self).__name__[:-6]}")
        wp_data = b''
        waypoint_end_offset = self.WAYPOINT_OFFSET + self.WAYPOINT_COUNT * 32
        for address in range(self.WAYPOINT_OFFSET, waypoint_end_offset, self.CHUNK_SIZE):
            wp_data += self.p.read_config_memory(address, self.CHUNK_SIZE)
        wp_list = []
        for wp_index in range(0, self.WAYPOINT_COUNT):
            offset = wp_index * 32
            wp = unpack_waypoint(wp_data[offset:offset+32])
            if wp is not None:
                wp_list.append(wp)
        return wp_list

    def read_mmsi(self):
        data = self.p.read_config_memory(self.MMSI_OFFSET, 6)
        mmsi = data[0:5].hex().upper()[0:9]
        return mmsi, data[5]

    def write_mmsi(self, mmsi: str = None, counter: int = None):
        """
        Program the MMSI, or reset it to the factory state when None.
        The update counter next to it is left as it is, unless given.
        """
        if mmsi is None:
            code = "FFFFFFFFFF"
            if counter is None:
                counter = 0
        else:
            if not (mmsi.isascii() and mmsi.isdecimal()):
                raise ProtocolError("Invalid MMSI format")
            if len(mmsi) != 9:
                raise ProtocolError("Invalid MMSI length")
            # DSC addresses are coded with ten digits, the last one always being zero
            code = mmsi + "0"
            if counter is None:
                counter = self.read_mmsi()[1]
        self.p.write_config_memory(self.MMSI_OFFSET, bytes.fromhex(code) + _counter_byte(counter, "MMSI"))

    def read_atis(self):
        data = self.p.read_config_memory(self.ATIS_CODE_OFFSET, 6)
        atis = data[0:5].hex().upper()
        return atis, data[5]

    def write_atis(self, atis: str = None, counter: int = None):
        """
        Program the ATIS code, or reset it to the factory state when None.
        The update counter next to it is left as it is, unless given.
        """
        if atis is None:
            code = "FFFFFFFFFF"
            if counter is None:
                counter = 0
        else:
            if not (atis.isascii() and atis.isdecimal()):
                raise ProtocolError("Invalid ATIS format")
            if len(atis) != 10:
                raise ProtocolError("Invalid ATIS length")
            code = atis
            if counter is None:
                counter = self.read_atis()[1]
        self.p.write_config_memory(self.ATIS_CODE_OFFSET, bytes.fromhex(code) + _counter_byte(counter, "ATIS"))

    def read_atis_enabled(self) -> tuple[bool, int]:
        atis_config = ord(self.p.read_config_memory(self.ATIS_ENABLED_OFFSET, 1))
        atis_enabled = atis_config & 1 == 1
        return atis_enabled, atis_config

    def write_atis_enabled(self, state: int):
        try:
            b = bytes([state])
        except ValueError:
            raise ProtocolError("Invalid ATIS enabled format")
        if state not in [0, 1]:
            logger.warning("Unknown ATIS enabled value. Flashing anyway")
        return self.p.write_config_memory(self.ATIS_ENABLED_OFFSET, b)

    def read_region(self) -> tuple[str, int]:
        region_code = ord(self.p.read_config_memory(self.REGION_CODE_OFFSET, 1))
        region = self.REGION_CODES.get(region_code, "")
        return region, region_code

    def write_region(self, region: int):
        try:
            b = bytes([region])
        except ValueError:
            raise ProtocolError("Invalid region format")
        if region not in self.REGION_CODES:
            logger.warning("Unknown region. Flashing anyway")
        return self.p.write_config_memory(self.REGION_CODE_OFFSET, b)


class HX870Config(GenericHXConfig):
    CONFIG_MAGIC = 871
    CONFIG_SIZE = 0x8000
    FLASH_ID = ["AM057N", "AM057N2"]


class HX890Config(GenericHXConfig):
    CONFIG_MAGIC = 890
    CONFIG_SIZE = 0x10000
    FLASH_ID = ["AM063N"]
    WAYPOINT_OFFSET = 0xd700
    WAYPOINT_COUNT = 250


class HX891Config(GenericHXConfig):
    CONFIG_MAGIC = 891
    CONFIG_SIZE = 0x10000
    FLASH_ID = ["AM070N"]
    WAYPOINT_OFFSET = 0xd700
    WAYPOINT_COUNT = 250


class GX1400Config(GenericHXConfig):

    CONFIG_MAGIC = 1400
    FLASH_ID = ["AM065N"]

    CHUNK_SIZE = 0x20
    CONFIG_SIZE = 0x2000

    MMSI_OFFSET = 0x0060
    ATIS_CODE_OFFSET = 0x0066
    ATIS_ENABLED_OFFSET = 0x0052
    FLASH_ID_OFFSET = 0x0098
    FLASH_ID_RANGE = (0x0098, 0x009f)
    REGION_CODE_OFFSET = 0x009f
    FIRMWARE_VERSION_OFFSET = 0x001d
    VARIANT_OFFSET = 0x00d0
    WAYPOINT_OFFSET = None
    WAYPOINT_COUNT = 0

    PROTECTED_RANGES = [
        (0x001d, 0x0020),  # firmware version
        (0x00a0, 0x00d0),  # unknown, and radio last turned off fix
        (0x0110, 0x0120),  # serial number and production date
        (0x1fa0, 0x2000),  # padding
    ]

    REGION_CODE_US = 0x00
    REGION_CODES = {
        0: "USA",
        1: "INTL",
        2: "UK",
        3: "BE",
        4: "NL",
        5: "SW",
        6: "GRM",
        7: "JPN",
    }
