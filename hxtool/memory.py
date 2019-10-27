# -*- coding: utf-8 -*-

from binascii import hexlify, unhexlify
import datetime
from functools import reduce
from logging import getLogger
from re import match
from struct import unpack
from math import copysign

from . import protocol

logger = getLogger(__name__)


def unpack_waypoint(data):
    wp_id = data[31]
    if wp_id == 255:
        return None
    wp_name = data[16:31].rstrip(b'\xff').decode("ascii")
    wp_mmsi = hexlify(data[0:5]).decode()[0:9]
    if wp_mmsi == "fffffffff":
        wp_mmsi = None

    lat_str = hexlify(data[4:9])[1:]
    lat_deg = int(lat_str[1:3])
    lat_min = int(lat_str[3:9]) / 10000.0
    lat_dir = chr(data[9])

    lon_str = hexlify(data[10:15])
    lon_deg = int(lon_str[0:4])
    lon_min = int(lon_str[4:10]) / 10000.0
    lon_dir = chr(data[15])

    wp_lat_decimal = { "S": -1.0, "N": 1.0 }[lat_dir] * lat_deg + lat_min / 60.0
    wp_lon_decimal = { "W": -1.0, "E": 1.0 }[lon_dir] * lon_deg + lon_min / 60.0

    wp_latitude = "%d%s%3.4f" % (lat_deg, lat_dir, lat_min)
    wp_longitude = "%d%s%3.4f" % (lon_deg, lon_dir, lon_min)

    return {
        "id": wp_id,
        "name": wp_name,
        "mmsi": wp_mmsi,
        "latitude_decimal": wp_lat_decimal,
        "longitude_decimal": wp_lon_decimal,
        "latitude": wp_latitude,
        "longitude": wp_longitude
    }


def pack_waypoint(wp):
    if isinstance(wp["latitude"], float):
        lat_deg = int(abs(wp["latitude"]))
        lat_min = (abs(wp["latitude"]) - lat_deg) * 60.0
        lat_dir = "N" if copysign(1.0, wp["latitude"]) > 0.0 else "S"
    elif isinstance(wp["latitude"], str):
        m = match(r"""(\d+)([NS])(\d+\.\d+)""", wp["latitude"].upper())
        if m is None:
            raise protocol.ProtocolError("Invalid waypoint latitude format")
        lat_deg = int(m[1])
        lat_dir = m[2]
        lat_min = float(m[3])
    else:
        raise protocol.ProtocolError("Invalid waypoint latitude format")

    lat_minstr = ("%.04f" % lat_min).replace(".", "").zfill(6)
    lat_hex = "%02d%s%02x" % (lat_deg, lat_minstr, ord(lat_dir))
    if len(lat_hex) != 10:
        raise protocol.ProtocolError("Invalid waypoint latitude format")

    if isinstance(wp["longitude"], float):
        lon_deg = int(abs(wp["longitude"]))
        lon_min = (abs(wp["longitude"]) - lon_deg) * 60.0
        lon_dir = "E" if copysign(1.0, wp["longitude"]) > 0.0 else "W"
    elif isinstance(wp["longitude"], str):
        m = match(r"""(\d+)([EW])(\d+\.\d+)""", wp["longitude"].upper())
        if m is None:
            raise protocol.ProtocolError("Invalid waypoint longitude format")
        lon_deg = int(m[1])
        lon_dir = m[2]
        lon_min = float(m[3])
    else:
        raise protocol.ProtocolError("Invalid waypoint longitude format")

    lon_minstr = ("%.04f" % lon_min).replace(".", "").zfill(6)
    lon_hex = "%04d%s%02x" % (lon_deg, lon_minstr, ord(lon_dir))
    if len(lon_hex) != 12:
        raise protocol.ProtocolError("Invalid waypoint longitude format")

    wp_data = b'\xff'*5
    if "mmsi" in wp and wp["mmsi"] is not None:
        wp_data = unhexlify(wp["mmsi"] + "0")
    wp_data += unhexlify(lat_hex) + unhexlify(lon_hex)
    wp_data += wp["name"].encode("ascii")[:15].ljust(15, b'\xff')
    wp_data += unhexlify("%02x" % wp["id"])  # TODO: There must be an elegant way
    if len(wp_data) != 32:
        raise protocol.ProtocolError("Waypoint encoding error")

    return wp_data


def unpack_route(data):
    if data[0x10] == 255:
        return None
    name = data[0:0x10].rstrip(b'\xff').decode("ascii")
    waypoint_ids = []
    for i in range(0x10, 0x20):
        if data[i] != 255:
            waypoint_ids.append(data[i])
    return {
        "name": name,
        "points": waypoint_ids,
    }


def pack_route(route):
    data = route["name"].encode("ascii")[:15].ljust(16, b'\xff')
    for point in route["points"]:
        id = point
        if isinstance(id, dict):
            id = point["id"]
        data += unhexlify("%02x" % id)
    while len(data) < 0x20:
        data += b'\xff'
    if len(data) != 0x20:
        raise protocol.ProtocolError("Route encoding error")
    return data


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
