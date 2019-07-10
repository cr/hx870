# -*- coding: utf-8 -*-

from binascii import hexlify, unhexlify
import datetime
from functools import reduce
from logging import getLogger
from re import match
from struct import unpack

from . import protocol

logger = getLogger(__name__)


def unpack_waypoint(data):
    wp_id = data[31]
    if wp_id == 255:
        return None
    wp_name = data[16:31].rstrip(b'\xff').decode("ascii")

    lat_str = hexlify(data[4:9])[1:]
    lat_deg = int(lat_str[0:3])
    lat_min = int(lat_str[3:9]) / 10000.0
    lat_dir = chr(data[9])

    lon_str = hexlify(data[10:15])
    lon_deg = int(lon_str[0:4])
    lon_min = int(lon_str[4:10]) / 10000.0
    lon_dir = chr(data[15])

    wp_latitude = "%d%s%3.4f" % (lat_deg, lat_dir, lat_min)
    wp_longitude = "%d%s%3.4f" % (lon_deg, lon_dir, lon_min)

    return {
        "id": wp_id,
        "name": wp_name,
        "latitude": wp_latitude,
        "longitude": wp_longitude
    }


def pack_waypoint(wp):
    m = match(r"""(\d+)([NS])(\d+\.\d+)""", wp["latitude"].upper())
    if m is None:
        raise protocol.ProtocolError("Invalid waypoint latitude format")
    lat_deg = int(m[1])
    lat_dir = m[2]
    lat_min = float(m[3])
    lat_minstr = ("%.04f" % lat_min).replace(".", "").zfill(6)
    lat_hex = "F%03d%s%s" % (lat_deg, lat_minstr, lat_dir)
    if len(lat_hex) != 12:
        raise protocol.ProtocolError("Invalid waypoint latitude format")

    m = match(r"""(\d+)([EW])(\d+\.\d+)""", wp["longitude"].upper())
    if m is None:
        raise protocol.ProtocolError("Invalid waypoint longitude format")
    lon_deg = int(m[1])
    lon_dir = m[2]
    lon_min = float(m[3])
    lon_minstr = ("%.04f" % lon_min).replace(".", "").zfill(6)
    lon_hex = "%04d%s%s" % (lon_deg, lon_minstr, lon_dir)
    if len(lon_hex) != 12:
        raise protocol.ProtocolError("Invalid waypoint longitude format")

    wp_data = b'\xff'*4 + unhexlify(lat_hex) + lat_dir.encode("ascii")
    wp_data += unhexlify(lon_hex) + lon_dir.encode("ascii")
    wp_data += wp["name"].encode("ascii")[:15].ljust(15, b'\xff')
    wp_data += unhexlify("%02x" % wp["id"])  # TODO: There must be an elegant way
    if len(wp_data) != 32:
        raise protocol.ProtocolError("Waypoint encoding error")

    return wp_data


region_code_map = {
    0: "INTERNATIONAL",
    1: "UNITED KINGDOM",
    2: "BELGIUM",
    3: "NETHERLAND",
    4: "SWEDEN",
    5: "GERMANY",
    255: "NONE"
}


region_map = {
    "INTERNATIONAL": 0,
    "CANADA": 0,
    "INTL": 0,
    "INT": 0,
    "CAN": 0,
    "CA": 0,
    "UNITED KINGDOM": 1,
    "UK": 1,
    "BELGIUM": 2,
    "BE": 2,
    "NETHERLAND": 3,
    "NETHERLANDS": 3,
    "NL": 3,
    "SWEDEN": 4,
    "SE": 4,
    "GERMANY": 5,
    "GRMN": 5,
    "DE": 5,
    "NONE": 255
}
