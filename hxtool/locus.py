# -*- coding: utf-8 -*-

from binascii import hexlify
from enum import Enum, IntFlag
from struct import pack, unpack, error as StructError
from functools import reduce


class LocusError(Exception):
    pass


class InternalError(Exception):
    pass


def checksum(data: bytes) -> int:
    return reduce(lambda x, y: x ^ y, data)


class LocusContent(IntFlag):
    UTC = 1 << 0  # 4 bytes int
    VALID = 1 << 1  # 1 byte uint
    LAT = 1 << 2  # 4 bytes float
    LON = 1 << 3  # 4 bytes float
    HGT = 1 << 4  # 2 bytes int
    SPD = 1 << 5  # 2 bytes uint
    TRK = 1 << 6  # 2 bytes int
    HDOP = 1 << 10  # 2 bytes
    NSAT = 1 << 12  # 1 byte uint


_LocusContentMap = {
    LocusContent.UTC: (0, LocusContent.UTC, "UTC Time", 4, "I"),
    LocusContent.VALID: (1, LocusContent.VALID, "Fix Type", 1, "B"),
    LocusContent.LAT: (2, LocusContent.LAT, "Latitude", 4, "f"),
    LocusContent.LON: (3, LocusContent.LON, "Longitude", 4, "f"),
    LocusContent.HGT: (4, LocusContent.HGT, "Height", 2, "H"),
    LocusContent.SPD: (5, LocusContent.SPD, "Speed", 2, "H"),
    LocusContent.TRK: (6, LocusContent.TRK, "Heading", 2, "H"),
    LocusContent.HDOP: (7, LocusContent.HDOP, "Precision", 2, "H"),  # Horizontal Dilution of Precision
    LocusContent.NSAT: (8, LocusContent.NSAT, "Satellites", 1, "B")
}


def locus_content_descriptor(content: int) -> dict:
    content_size = 0
    fmt_str = "<"
    attributes = []
    labels = []
    for _, value, desc, size, fmt in sorted(_LocusContentMap.values()):
        if content & value != 0:
            content_size += size
            fmt_str += fmt
            attributes.append(desc.lower().replace(" ", "_"))
            labels.append(desc)
    return {
        "size": content_size,
        "format": fmt_str,
        "attributes": attributes,
        "labels": labels
    }


class LoggingMode(IntFlag):
    ALWAYSLOCATE = 1 << 0
    FIXONLY = 1 << 1
    NORMAL = 1 << 2
    INTERVAL = 1 << 3
    DISTANCE = 1 << 4
    SPEED = 1 << 5


class FixQuality(Enum):
    INVALID = 0
    SPS = 1  # GPS Standard Positioning Service
    DGPS = 2  # Differential GPS SPS Mode
    PPS = 3  # GPS Precise Positioning Service
    RTK = 4  # Real Time Kinematic
    FRTK = 5  # Float RTK
    ESTIMATED = 6  # Dead reckoning mode
    MANUAL = 7
    SIMULATOR = 8


class LocusHeader(object):
    def __init__(self, data: bytes, *, verify=True):
        if len(data) < 16:
            raise LocusError("Insufficient data for parsing header")
        (
            self.unknown_00,
            self.unknown_01,
            self.LoggingType,
            self.LoggingMode,
            self.LogContent,
            self.unknown_06,
            self.IntervalSetting,
            self.DistanceSetting,
            self.SpeedSetting,
            self.unknown_0e,
            self.Checksum
        ) = unpack("<BBBBHHHHHBB", data[:16])
        if verify and self.Checksum != checksum(data[:15]):
            raise LocusError(f"Invalid header checksum in {hexlify(data).decode('ascii')}")

    def __bytes__(self):
        packed = pack("<BBBBHHHHHB",
                      self.unknown_00,
                      self.unknown_01,
                      self.LoggingType,
                      self.LoggingMode,
                      self.LogContent,
                      self.unknown_06,
                      self.IntervalSetting,
                      self.DistanceSetting,
                      self.SpeedSetting,
                      self.unknown_0e)
        packed += bytes([checksum(packed)])
        return packed


class LocusWaypoint(object):
    def __init__(self, content_byte: int, data: bytes, *, verify=True):
        if data.startswith(b"\xff"*6) or data.startswith(b"\x00"*6):
            raise LocusError("Empty waypoint data")
        content = locus_content_descriptor(content_byte)
        self._size = content["size"]
        self._format = content["format"]
        self._attributes = content["attributes"]
        self._labels = content["attributes"]
        self._d = {}
        if len(data) != content["size"] + 1:  # plus one checksum byte
            raise LocusError("Too much waypoint data")
        try:
            parsed = unpack(content["format"] + "B", data)  # appending checksum byte
        except StructError as e:
            raise LocusError(f"Waypoint data has unexpected format: {str(e)}") from e
        if len(parsed) != len(content["attributes"]) + 1:  # plus one checksum byte
            raise InternalError("Internal LOCUS parser error: parse size mismatch")
        for i in range(len(content["attributes"])):
            self._d[content["attributes"][i]] = parsed[i]
        self.checksum = parsed[-1]
        if verify and self.checksum != checksum(data[:-1]):
            raise LocusError(f"Checksum mismatch in waypoint data: {hexlify(data).decode('ascii')}")

    def __bytes__(self):
        values = []
        for attr in self._attributes:
            values.append(self._d[attr])
        packed = pack(self._format, values)
        packed += bytes([checksum(packed)])
        return packed

    def __contains__(self, item):
        return item in self._d

    def __getitem__(self, item):
        return self._d[item]

    def __setitem__(self, key, value):
        if key not in self._d:
            raise LocusError(f"Unable to create new LocusWaypoint item `{key}`")
        self._d[key] = value

    def __iter__(self):
        yield from self._d.keys()


class LocusLog(object):
    def __init__(self, header: LocusHeader, data: bytes):
        self._header = header
        content = locus_content_descriptor(header.LogContent)
        self._waypoints = []
        self._size = None
        for offset in range(0, len(data), content["size"] + 1):  # plus checksum byte
            start = offset
            end = offset + content["size"] + 1  # plus checksum byte
            if end > len(data):
                break
            try:
                self._waypoints.append(LocusWaypoint(header.LogContent, data[start:end], verify=True))
            except LocusError:
                break

    def __len__(self):
        return len(self._waypoints)

    def __getitem__(self, item):
        if type(item) is not int:
            raise ValueError("log index must be int")
        return self._waypoints[item]

    def __iter__(self):
        yield from self._waypoints


class Locus(object):
    def __init__(self, data: bytes, *, verify=True):
        self.header = LocusHeader(data[:0x10], verify=verify)
        self.mask = data[0x10:0x3c]
        self.unknown_3c = data[0x3c:0x40]
        self.log = LocusLog(self.header, data[0x40:])

    def __len__(self):
        return len(self.log)

    def __getitem__(self, item):
        if type(item) is not int:
            raise ValueError("log index must be int")
        return self.log[item]

    def __iter__(self):
        yield from self.log
