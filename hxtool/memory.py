# -*- coding: utf-8 -*-

from array import array
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

HX870Segments = {
    "Magic": (0x0000, 0x0004),
    "DeviceSetup": (0x0020, 0x0070),
    "ChannelGroupNames": (0x0070, 0x00b0),
    "DSCSetup": (0x00b0,0x0100),
    "FlashID": (0x0100, 0x0108),
    "Region": (0x010f, 0x0110),
    "ChannelEnabled": (0x0120, 0x0190),
    "ScanMemEnabled": (0x0190, 0x0200),
    "PresetList": (0x0200, 0x0300),
    "ChannelSetup": (0x0600, 0x0ba0),
    "ChannelNames": (0x0ba0, 0x3500),
}

def unpack_channels(data: bytes) -> dict:
    channels = {
        "group1": {"list": []},
        "group2": {"list": []},
        "group3": {"list": []},
        "regional": {"list": []},
        "expansion": {"list": []},
        "weather": {"list": []}
    }

    names = unpack_channel_names(data[HX870Segments["ChannelNames"][0]:HX870Segments["ChannelNames"][1]])

    for group, offset, length in (
        ("group1", HX870Segments["ChannelSetup"][0] + 0x0000, 96),
        ("group2", HX870Segments["ChannelSetup"][0] + 0x0180, 96),
        ("group3", HX870Segments["ChannelSetup"][0] + 0x0300, 96)):
        for i, p in zip(range(length), range(offset, offset + length*4, 4)):
            chid, rxshift, rxtxshift, hpallowed, txallowed, lpdefault, unused, dscshipship = unpack_marine_channel_flags(data[p:p+4])
            if chid == "":  # FIXME: work off enable list
                continue
            channels[group]["list"].append({
                "id": chid,
                "name": names[group][i],
                "rxshift": rxshift,
                "rxtxshift": rxtxshift,
                "highpower": hpallowed,
                "txenable": txallowed,
                "lowpowerdefault": lpdefault,
                "unused": unused,
                "dscshiptoship": dscshipship
            })

    for group, offset, length in (
        ("regional", HX870Segments["ChannelSetup"][0] + 0x04a0, 12),
        ("expansion", HX870Segments["ChannelSetup"][0] + 0x0500, 20)):
        for i, p in zip(range(length), range(offset, offset + length*8, 8)):
            chid, rxfreq, txfreq, lponly, unused4, unused2, hpallowed = unpack_private_channel_flags(data[p:p+8])
            if chid == "":  # FIXME: work off enable list
                continue
            channels[group]["list"].append({
                "id": chid,
                "rxfreq": rxfreq,
                "txfreq": txfreq,
                "highpower": hpallowed,
                "lowpowerdefault": not lponly,
                "unused4": unused4,
                "unused2": unused2,
            })
    
    channels["weather"]["list"] = names["weather"]

    return channels


def unpack_channel_groups(data: bytes) -> list:
    return []


def unpack_weather_channels(data: bytes) -> list:
    return []


def unpack_marine_channel_flags(data: bytes) -> object:
    """
    0x0 	channel ID 	numeric
    0x1-0x2 flags       bitmask:
        0x8000 = 1xxxxxxx xxxxxxxx = frq shift Rx only
        0x4000 = x1xxxxxx xxxxxxxx = frq shift Rx and Tx
        0x2000 = xx1xxxxx xxxxxxxx = high power allowed
        0x1000 = xxx1xxxx xxxxxxxx = Tx allowed
        0x0800 = xxxx1xxx xxxxxxxx = high power allowed, but low power is default
        0x0400 = xxxxx1xx xxxxxxxx - unused?
        0x0200 = xxxxxx1x xxxxxxxx = channel suffix: "B"
        0x0100 = xxxxxxx1 xxxxxxxx = channel suffix: "A"
        0x0080 = xxxxxxxx 1xxxxxxx = DSC ship/ship channel
        0x007f = xxxxxxxx x1111111 = channel prefix: 0x7f=none, other=numeric
    See https://johannessen.github.io/hx870/#channel-flags
    """

    flags = int.from_bytes(data[1:3], "big")
    rxshift = bool(flags & 0x8000)
    rxtxshift = bool(flags & 0x4000)
    hpallowed = bool(flags & 0x2000)
    txallowed = bool(flags & 0x1000)
    lpdefault = bool(flags & 0x0800)
    unused = bool(flags & 0x0400)
    suffixb = "B" if bool(flags & 0x0200) else ""
    suffixa = "A" if bool(flags & 0x0100) else ""
    dscshipship = bool(flags & 0x0080)
    prefix = "" if flags & 0x7f == 0x7f else f"{flags & 0x7f:02d}"
    chid = "" if data[0] == 255 else f"{prefix}{data[0]:02d}{suffixa}{suffixb}"    

    return chid, rxshift, rxtxshift, hpallowed, txallowed, lpdefault, unused, dscshipship


def unpack_channel_group_definition(data:bytes) -> list:
    """
    0x0 	    channel group enabled 	0x00=no, 0x01=yes
    0x1 	    DSC enabled 	        0x00=no, 0x01=yes
    0x2 	    ATIS enabled 	        0x00=no, 0x01=yes (see note below)
    0x3-0x7 	channel group name      0xff padded
    0x8-0xf 	model name 	            0xff padded 
    """

    enabled, dsc, atis, name, model = unpack(b'>???5s8s', data)

    return enabled, dsc, atis, name.strip(b'\xff').decode("ascii"), model.strip(b'\xff').decode("ascii")


def unpack_private_channel_flags(data: bytes) -> list:
    """
    0x0-0x1 	channel ID 	2 * char (lower case not supported)
    0x2-0x4 	Rx frequency 	5 nibbles BCD (in kHz above 100 MHz)
    0x5-0x7 	Tx frequency 	5 nibbles BCD (in kHz above 100 MHz), 0xfffff = Tx forbidden
    0x7 	    channel definition flags 	lower nibble:
        0x08 = xxxx1xxx = low power
        0x04 = xxxxx1xx - ?
        0x02 = xxxxxx1x - ?
        0x01 = xxxxxxx1 = user power up
    """

    chid = data[0:2].strip(b'\xff').decode("ascii")
    rxbcd = data[2:5].hex()[:-1]
    rxfreq = "" if rxbcd == "fffff" else f"1{rxbcd[0:2]}.{rxbcd[2:]}"
    txbcd = data[5:8].hex()[:-1]
    txfreq = "" if txbcd == "fffff" else f"1{txbcd[0:2]}.{txbcd[2:]}"
    flags = data[7] & 0x0f
    lponly = bool(flags & 0x08)
    unused4 = bool(flags & 0x04)
    unused2 = bool(flags & 0x02)
    hpallowed = bool(flags & 0x01)

    return chid, rxfreq, txfreq, lponly, unused4, unused2, hpallowed


def unpack_channel_names(data: bytes) -> object:
    names = {
        "group1": [],
        "group2": [],
        "group3": [],
        "regional": [],
        "expansion": [],
        "weather": [],
    }
    for group, offset, length in (
        ("group1", 0x0000, 96),
        ("group2", 0x0c00, 96),
        ("group3", 0x1800, 96),
        ("regional", 0x2400, 12),
        ("expansion", 0x2580, 20),
        ("weather", 0x2820, 10)):
        for p in range(offset, offset + length*16, 16):
            name = data[p:p+16].strip(b'\xff').decode("ascii")
            names[group].append(name)

    return names
