# -*- coding: utf-8 -*-

from binascii import hexlify
import gpxpy
import gpxpy.gpx
from json import dump
from logging import getLogger
from os.path import abspath
from pprint import pprint as pp

import hxtool
from .base import CliCommand
from hxtool.memory import unpack_log_line

logger = getLogger(__name__)


class GpsLogCommand(CliCommand):

    name = "gpslog"
    help = "dump or clear GPS logger data"

    @staticmethod
    def setup_args(parser) -> None:
        parser.add_argument("-e", "--erase",
                            help="erase GPS log data from device",
                            action="store_true")
        parser.add_argument("-g", "--gpx",
                            help="file name for GPX export",
                            type=abspath,
                            action="store")
        parser.add_argument("-j", "--json",
                            help="file name for JSON export",
                            type=abspath,
                            action="store")
        parser.add_argument("-r", "--raw",
                            help="file name for raw log data export",
                            type=abspath,
                            action="store")

    def run(self):

        hx = hxtool.get(self.args)
        if hx is None:
            return 10

        if not hx.comm.cp_mode:
            logger.critical("For GPS log functions, device must be in CP mode (MENU + ON)")
            return 10

        result = 0

        if self.args.gpx or self.args.json or self.args.raw or not self.args.erase:
            logger.info("Reading log data from handset (takes a while)")
            raw_log_data = hx.comm.read_gps_log()
            logger.info(f"Received {len(raw_log_data)} bytes of raw log data from handset")
        else:
            raw_log_data = None

        if self.args.gpx:
            logger.info("Exporting GPX log data to `%s`", self.args.gpx)
            result = max(write_gpx(raw_log_data, self.args.gpx), result)

        if self.args.json:
            logger.info("Exporting JSON log data to `%s`", self.args.json)
            result = max(write_json(raw_log_data, self.args.json), result)

        if self.args.raw:
            logger.info("Exporting raw log data to `%s`", self.args.raw)
            result = max(write_raw(raw_log_data, self.args.raw), result)

        if not (self.args.gpx or self.args.json or self.args.raw or self.args.erase):
            result = max(dump_log(raw_log_data), result)

        if self.args.erase:
            logger.info("Erasing GPS log data from device")
            hx.comm.erase_gps_log()

        return result


def decode_gps_log(data: bytes) -> dict:
    log_header = data[0x00:0x16]
    bitmap = data[0x16:0x3c]  # bitfield encoding log slot usage: 1 unused, 0: used
    unknown = data[0x3c:0x40]

    log = {
        "header": hexlify(log_header).decode("ascii"),
        "unknown": hexlify(unknown).decode("ascii"),
        "waypoints": []
    }

    offset = 0x40
    while True:

        # FIXME: Work with bitmap
        # This will likely stop working once the log overflows and there are no more unwritten slots.
        if data[offset:offset+4] == b"\xff\xff\xff\xff":
            break
        log["waypoints"].append(unpack_log_line(data[offset:offset+20]))
        offset += 20

    return log


def write_gpx(log_data: bytes,  file_name: str) -> int:
    log = decode_gps_log(log_data)

    gpx = gpxpy.gpx.GPX()

    # Create first track in our GPX:
    gpx_track = gpxpy.gpx.GPXTrack()
    gpx.tracks.append(gpx_track)

    # Create first segment in our GPX track:
    gpx_segment = gpxpy.gpx.GPXTrackSegment()
    gpx_track.segments.append(gpx_segment)

    # Create points:
    for point in log["waypoints"]:
        gpx_segment.points.append(gpxpy.gpx.GPXTrackPoint(
            latitude=point["latitude"],
            longitude=point["longitude"],
            elevation=point["altitude"],
            time=point["utc_time"],
            speed=point["speed"]
        ))

    with open(file_name, "w") as f:
        f.write(gpx.to_xml())

    return 0


def write_json(log_data: bytes, file_name: str) -> int:
    log = decode_gps_log(log_data)
    for w in log["waypoints"]:
        w["utc_time"] = w["utc_time"].isoformat()
    with open(file_name, "w") as f:
        dump(log, f, indent=4)
    return 0


def write_raw(log_data: bytes, file_name: str) -> int:
    with open(file_name, "wb") as f:
        f.write(log_data)
    return 0


def dump_log(log_data):
    pp(decode_gps_log(log_data))
    return 0
