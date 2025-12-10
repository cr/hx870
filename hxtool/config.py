# -*- coding: utf-8 -*-

from binascii import hexlify, unhexlify
from logging import getLogger
from typing import Tuple

from .memory import unpack_waypoint, region_code_map
from .protocol import GenericHXProtocol, ProtocolError

logger = getLogger(__name__)


class GenericHXConfig(object):

    CONFIG_MAGIC = 0xffff
    FLASH_ID = ["AM000A"]

    CHUNK_SIZE = 0x40
    CONFIG_SIZE = 0x8000
    PROGRESS_LOG_AT = 0x1000

    MMSI_OFFSET = 0x00b0
    ATIS_CODE_OFFSET = 0x00b6
    ATIS_ENABLED_OFFSET = 0x00a2
    FLASH_ID_OFFSET = 0x0100
    REGION_CODE_OFFSET = 0x010f
    WAYPOINT_OFFSET = 0x4300

    REGION_CODE_US = 0xff
    WAYPOINT_COUNT = 200

    def __init__(self, protocol: GenericHXProtocol):
        self.p = protocol

    def config_read(self, progress=False):
        config_data = b''
        bytes_to_go = self.CONFIG_SIZE
        for offset in range(0x0000, self.CONFIG_SIZE, self.CHUNK_SIZE):
            if progress:
                percent_done = int(100.0 * offset / bytes_to_go)
                if offset % self.PROGRESS_LOG_AT == 0:
                    logger.info(f"{offset} / {bytes_to_go} bytes ({percent_done}%)")
            config_data += self.p.read_config_memory(offset, self.CHUNK_SIZE)
        if progress:
            logger.info(f"{bytes_to_go} / {bytes_to_go} bytes (100%)")
        return config_data

    def _config_write_precheck(self, data, check_region):
        if len(data) != self.CONFIG_SIZE:
            raise ProtocolError("Unexpected config data size")
        magic = self.p.read_config_memory(0x0000, 2)
        magic_end = self.p.read_config_memory(self.CONFIG_SIZE-2, 2)
        if magic != data[:2] or magic_end != data[-2:]:
            raise ProtocolError("Unexpected config magic in device")
        region = ord(self.p.read_config_memory(self.REGION_CODE_OFFSET, 1))
        region_is_us = region == self.REGION_CODE_US
        data_is_us = data[self.REGION_CODE_OFFSET] == self.REGION_CODE_US
        if region_is_us != data_is_us:
            if check_region:
                logger.error("Region mismatch")
                raise ProtocolError("Region mismatch")
            logger.warning("Ignoring region mismatch. Flashing anyway")

    def config_write(self, data, check_region=True, progress=False):
        self._config_write_precheck(data, check_region)
        bytes_to_go = len(data)
        if progress:
            logger.info(f"0 / {bytes_to_go} bytes (0%)")
        self.p.write_config_memory(0x0002, data[0x0002:0x000f])
        self.p.write_config_memory(0x0010, data[0x0010:self.CHUNK_SIZE])
        last_chunk = self.CONFIG_SIZE - self.CHUNK_SIZE
        for offset in range(self.CHUNK_SIZE, last_chunk, self.CHUNK_SIZE):
            if progress:
                percent_done = int(100.0 * offset / bytes_to_go)
                if offset % self.PROGRESS_LOG_AT == 0:
                    logger.info(f"{offset} / {bytes_to_go} bytes ({percent_done}%)")
            self.p.write_config_memory(offset, data[offset:offset+self.CHUNK_SIZE])
        self.p.write_config_memory(last_chunk, data[last_chunk:-2])
        if progress:
            logger.info(f"{bytes_to_go} / {bytes_to_go} bytes (100%)")

    def read_waypoints(self):
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
        data = hexlify(self.p.read_config_memory(self.MMSI_OFFSET, 6)).decode().upper()
        mmsi = data[0:9]
        status = data[10:12]
        return mmsi, status

    def write_mmsi(self, mmsi: str = None, status: str = None):
        if mmsi is None:
            mmsi = "FFFFFFFFFF"
            if status is None:
                status = "00"
        else:
            if not mmsi.isdecimal():
                raise ProtocolError("Invalid MMSI format")
            if status is None:
                status = "02"
        if len(mmsi) == 9:
            mmsi += "0"
        if len(mmsi) != 10:
            raise ProtocolError("Invalid MMSI length")
        if status.upper() not in ["00", "01", "02", "FF"]:
            raise ProtocolError("Invalid MMSI status")
        data = unhexlify(mmsi + status)
        self.p.write_config_memory(self.MMSI_OFFSET, data)

    def read_atis(self):
        data = hexlify(self.p.read_config_memory(self.ATIS_CODE_OFFSET, 6)).decode().upper()
        atis = data[0:10]
        status = data[10:12]
        return atis, status

    def write_atis(self, atis: str = None, status: str = None):
        if atis is None:
            atis = "FFFFFFFFFF"
            if status is None:
                status = "00"
        else:
            if not atis[0] == "9" or not atis.isdecimal():
                raise ProtocolError("Invalid ATIS format")
            if status is None:
                status = "01"
        if len(atis) != 10:
            raise ProtocolError("Invalid ATIS length")
        if status.upper() not in ["00", "01", "02", "FF"]:
            raise ProtocolError("Invalid ATIS status")
        data = unhexlify(atis + status)
        self.p.write_config_memory(self.ATIS_CODE_OFFSET, data)

    def read_atis_enabled(self) -> Tuple[bool, int]:
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

    def read_region(self) -> Tuple[str, int]:
        region_code = ord(self.p.read_config_memory(self.REGION_CODE_OFFSET, 1))
        region = region_code_map[region_code]
        return region, region_code

    def write_region(self, region: int):
        try:
            b = bytes([region])
        except ValueError:
            raise ProtocolError("Invalid region format")
        if region not in region_code_map:
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
    PROGRESS_LOG_AT = 0x0800

    MMSI_OFFSET = 0x0060
    ATIS_CODE_OFFSET = 0x0066
    ATIS_ENABLED_OFFSET = 0x0052
    FLASH_ID_OFFSET = 0x0098
    REGION_CODE_OFFSET = 0x009f
    WAYPOINT_OFFSET = None

    REGION_CODE_US = 0x00
    WAYPOINT_COUNT = 0

    def config_write(self, data, check_region=True, progress=False):
        self._config_write_precheck(data, check_region)
        bytes_to_go = self.CONFIG_SIZE
        if progress:
            logger.info(f"0 / {bytes_to_go} bytes (0%)")
        # Skip writing the following data to the device:
        # magic, firmware version, flash ID, unknown 0x00a0-0x00bf, last
        # turned off fix, serial no, production date, some padding at the end
        self.p.write_config_memory(0x0002, data[0x0002:0x001d])
        self.p.write_config_memory(0x0020, data[0x0020:0x0040])
        self.p.write_config_memory(0x0040, data[0x0040:0x0060])
        self.p.write_config_memory(0x0060, data[0x0060:0x0080])
        self.p.write_config_memory(0x0080, data[0x0080:0x0098])
        self.p.write_config_memory(0x009f, data[0x009f:0x00a0])
        self.p.write_config_memory(0x00d0, data[0x00d0:0x00f0])
        self.p.write_config_memory(0x00f0, data[0x00f0:0x0110])
        for offset in range(0x0120, 0x1fa0, self.CHUNK_SIZE):
            if progress:
                percent_done = int(100.0 * offset / bytes_to_go)
                if offset % self.PROGRESS_LOG_AT == 0:
                    logger.info(f"{offset} / {bytes_to_go} bytes ({percent_done}%)")
            self.p.write_config_memory(offset, data[offset:offset+self.CHUNK_SIZE])
        if progress:
            logger.info(f"{bytes_to_go} / {bytes_to_go} bytes (100%)")

    def read_waypoints(self):
        raise ProtocolError("Waypoints unsupported by GX1400")

    def read_region(self):
        region_code = ord(self.p.read_config_memory(self.REGION_CODE_OFFSET, 1))
        try:
            region = ["USA", "INTL", "UK", "BE", "NL", "SW", "GRM", "JPN"][region_code]
        except IndexError:
            region = ""
        return region, region_code
