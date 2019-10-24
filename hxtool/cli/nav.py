# -*- coding: utf-8 -*-

from binascii import hexlify
import gpxpy
import gpxpy.gpx
from logging import getLogger
from os.path import abspath

import hxtool
from .base import CliCommand
from hxtool.memory import unpack_log_line

logger = getLogger(__name__)


class NavCommand(CliCommand):

    name = "nav"
    help = "dump or flash navigation data (waypoints and routes)"

    @staticmethod
    def setup_args(parser) -> None:
        parser.add_argument("-g", "--gpx",
                            help="file name for GPX export",
                            type=abspath,
                            action="store")

    def run(self):

        hx = hxtool.get(self.args)
        if hx is None:
            return 10

        if not hx.comm.cp_mode:
            logger.critical("For navigation data functions, device must be in CP mode (MENU + ON)")
            return 10

        result = 0

        if self.args.gpx or self.args.raw:
                logger.info("Reading nav data from handset")
                raw_nav_data = hx.config.read_waypoints()
                logger.info(f"Received {len(raw_nav_data)} bytes of raw nav data from handset")
        else:
            raw_nav_data = None

        if self.args.gpx:
            logger.info("Exporting GPX nav data to `%s`", self.args.gpx)
            result = max(write_gpx(raw_nav_data, self.args.gpx), result)

        return result


def write_gpx(waypoints: bytes,  file_name: str) -> int:
    if waypoints is None:
        logger.warning("No waypoints in device. Not writing empty GPX file")
        return 0

    gpx = gpxpy.gpx.GPX()

    for point in waypoints:
        p = gpxpy.gpx.GPXWaypoint(
            latitude=point["latitude_decimal"],
            longitude=point["longitude_decimal"],
            name=point["name"],
        )
        gpx.waypoints.append(p)

    with open(file_name, "w") as f:
        f.write(gpx.to_xml(version="1.1"))

    return 0
