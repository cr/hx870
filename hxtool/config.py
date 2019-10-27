# -*- coding: utf-8 -*-

from binascii import hexlify, unhexlify
from logging import getLogger

from .memory import unpack_waypoint, unpack_route
from .protocol import GenericHXProtocol, ProtocolError

logger = getLogger(__name__)


class GenericHXConfig(object):

    def __init__(self, protocol: GenericHXProtocol):
        self.p = protocol

    def limits(self):
        return {
            "waypoints": 200,
            "routes": 20,
        }

    def config_read(self, progress=False):
        config_data = b''
        bytes_to_go = 0x8000
        for offset in range(0x0000, 0x8000, 0x40):
            if progress:
                percent_done = int(100.0 * offset / bytes_to_go)
                if offset % 0x1000 == 0:
                    logger.info(f"{offset} / {bytes_to_go} bytes ({percent_done}%)")
            config_data += self.p.read_config_memory(offset, 0x40)
        if progress:
            logger.info(f"{bytes_to_go} / {bytes_to_go} bytes (100%)")
        return config_data

    def config_write(self, data, check_region=True, progress=False):
        bytes_to_go = len(data)
        if bytes_to_go != 0x8000:
            raise ProtocolError("Unexpected config data size")
        magic = self.p.read_config_memory(0x0000, 2)
        magic_end = self.p.read_config_memory(0x7ffe, 2)
        if magic != data[:2] or magic_end != data[-2:]:
            raise ProtocolError("Unexpected config magic in device")
        region = self.p.read_config_memory(0x010f, 1)
        region_is_us = region == b'0xff'
        data_is_us = data[0x010f] == b'0xff'
        if region_is_us != data_is_us:
            if check_region:
                logger.error("Region mismatch")
                raise ProtocolError("Region mismatch")
            logger.warning("Ignoring region mismatch. Flashing anyway")

        if progress:
            logger.info(f"0 / {bytes_to_go} bytes (0%)")
        self.p.write_config_memory(0x0002, data[0x0002:0x000f])
        self.p.write_config_memory(0x0010, data[0x0010:0x0040])
        for offset in range(0x0040, 0x7fc0, 0x40):
            if progress:
                percent_done = int(100.0 * offset / bytes_to_go)
                if offset % 0x1000 == 0:
                    logger.info(f"{offset} / {bytes_to_go} bytes ({percent_done}%)")
            self.p.write_config_memory(offset, data[offset:offset+0x40])
        self.p.write_config_memory(0x7fc0, data[0x7fc0:0x7ffe])
        if progress:
            logger.info(f"{bytes_to_go} / {bytes_to_go} bytes (100%)")

    def read_waypoints(self):
        return self.read_nav_data() ["waypoints"]

    def read_nav_data(self, progress=False):
        nav_data = b''
        bytes_to_go = 0x5e80 - 0x4300
        for offset in range(0x4300, 0x5e80, 0x40):
            bytes_done = offset - 0x4300
            nav_data += self.p.read_config_memory(offset, 0x40)
            if bytes_done % 0xdc0 == 0:  # 50%
                percent_done = int(100.0 * bytes_done / bytes_to_go)
                logger.info(f"{bytes_done} / {bytes_to_go} bytes ({percent_done}%)")
        waypoints = []
        wp_index = {}
        for offset in range(0, 200 * 0x20, 0x20):
            wp = unpack_waypoint(nav_data[offset:offset+0x20])
            if wp is not None:
                wp_index[wp["id"]] = len(waypoints)
                waypoints.append(wp)
        routes = []
        for offset in range(200 * 0x20, 220 * 0x20, 0x20):
            rt = unpack_route(nav_data[offset:offset+0x20])
            if rt is not None:
                for i in range(0, len(rt["points"])):
                    # unpack_route() just returns waypoint IDs; replace those with the actual waypoints
                    rt["points"][i] = waypoints[wp_index[ rt["points"][i] ]]
                routes.append(rt)
        if progress:
            logger.info(f"{bytes_to_go} / {bytes_to_go} bytes (100%)")
        return {
            "waypoints": waypoints,
            "routes": routes,
        }

    def read_mmsi(self):
        data = hexlify(self.p.read_config_memory(0x00b0, 6)).decode().upper()
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
        self.p.write_config_memory(0x00b0, data)

    def read_atis(self):
        data = hexlify(self.p.read_config_memory(0x00b6, 6)).decode().upper()
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
        self.p.write_config_memory(0x00b6, data)


class HX870Config(GenericHXConfig):
    pass


class HX890Config(GenericHXConfig):
    pass
