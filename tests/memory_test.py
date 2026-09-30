# -*- coding: utf-8 -*-

from binascii import unhexlify
import pytest

from hxtool.memory import pack_waypoint, unpack_waypoint
from hxtool.protocol import ProtocolError

# Waypoint records as stored in config memory (see config_test.py)
WPT_DSC = unhexlify("9740019080544157174E001235956745") + b"WPT001".ljust(15, b"\xff") + b"\x01"
WPT_MANUAL = unhexlify("FFFFFFFFFF2707433353010917166757") + b"long waypoint 2".ljust(15, b"\xff") + b"\x02"
WPT_EMPTY = b"\xff" * 32


def test_unpack_waypoint():
    assert unpack_waypoint(WPT_DSC) == {
        "id": 1, "name": "WPT001", "mmsi": "974001908", "latitude": "54N41.5717", "longitude": "12E35.9567",
    }
    assert unpack_waypoint(WPT_MANUAL) == {
        "id": 2, "name": "long waypoint 2", "mmsi": None, "latitude": "27S07.4333", "longitude": "109W17.1667",
    }
    assert unpack_waypoint(WPT_EMPTY) is None


def test_pack_waypoint_round_trip():
    for record in WPT_DSC, WPT_MANUAL:
        assert pack_waypoint(unpack_waypoint(record)) == record, "pack is the inverse of unpack"

    waypoint = {"id": 200, "name": "0123456789ABCDE", "mmsi": "123456789", "latitude": "0N00.0000",
                "longitude": "180W00.0000"}
    assert unpack_waypoint(pack_waypoint(waypoint)) == waypoint, "unpack is the inverse of pack"

    packed = pack_waypoint({"id": 3, "name": "short", "mmsi": None, "latitude": "1N2.3", "longitude": "4E5.6"})
    assert len(packed) == 32
    assert unpack_waypoint(packed)["latitude"] == "1N02.3000", "minutes are normalised"
    assert unpack_waypoint(packed)["name"] == "short"


@pytest.mark.parametrize("field, value", [
    ("latitude", "54X41.5717"),  # bad hemisphere
    ("latitude", "54N"),  # no minutes
    ("latitude", "54E41.5717"),  # longitude hemisphere in latitude
    ("latitude", "54N60.0000"),  # minutes out of range
    ("latitude", "91N00.0000"),  # degrees out of range
    ("longitude", "181E00.0000"),  # degrees out of range
    ("longitude", "12N35.9567"),  # latitude hemisphere in longitude
    ("name", "0123456789ABCDEF"),  # too long
    ("name", "Ünïcode"),  # not ASCII
    ("mmsi", "12345"),  # too short
    ("mmsi", "1234567890"),  # ten digits: the padding digit is not for the caller to provide
    ("mmsi", "12345678x"),  # not numeric
    ("id", "abc"),  # not numeric
    ("id", 0),  # ids are one-based
    ("id", 256),  # ids are one byte
])
def test_pack_waypoint_rejects(field, value):
    waypoint = {"id": 1, "name": "WPT001", "mmsi": None, "latitude": "54N41.5717", "longitude": "12E35.9567"}
    waypoint[field] = value
    with pytest.raises(ProtocolError):
        pack_waypoint(waypoint)
