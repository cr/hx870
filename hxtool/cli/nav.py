# -*- coding: utf-8 -*-

import gpxpy
import gpxpy.gpx
from logging import getLogger
from os.path import abspath

import hxtool
from .base import CliCommand

logger = getLogger(__name__)


class NavCommand(CliCommand):

    name = "nav"
    help = "dump or flash navigation data (waypoints and routes)"

    @staticmethod
    def setup_args(parser) -> None:
        parser.add_argument("-g", "--gpx",
                            help="name of GPX file",
                            type=abspath,
                            action="store")
        parser.add_argument("-d", "--dump",
                            help="read nav data from device and write to file",
                            action="store_true")
        parser.add_argument("-f", "--flash",
                            help="read nav data from file and write to device",
                            action="store_true")
        parser.add_argument("-e", "--erase",
                            help="erase existing nav data from device",
                            action="store_true")

    def run(self):

        hx = hxtool.get(self.args)
        if hx is None:
            return 10

        if not hx.comm.cp_mode:
            logger.critical("For navigation data functions, device must be in CP mode (MENU + ON)")
            return 10

        result = 0
        
        if self.args.dump:
            result = max(self.dump(hx), result)

        if self.args.flash or self.args.erase:
            raise NotImplementedError

        return result


    def dump(self, hx):
        if self.args.gpx:
            logger.info("Reading nav data from handset")
            raw_nav_data = hx.config.read_nav_data(True)
            logger.info("Writing GPX nav data to `{}`".format(self.args.gpx))
            return write_gpx(raw_nav_data, self.args.gpx)
        return 0


def write_gpx(nav_data: dict,  file_name: str) -> int:
    if len(nav_data["waypoints"]) == 0:
        logger.warning("No waypoints in device. Not writing empty GPX file")
        return 0

    gpx = gpxpy.gpx.GPX()

    for point in nav_data["waypoints"]:
        p = gpxpy.gpx.GPXWaypoint(
            latitude=point["latitude_decimal"],
            longitude=point["longitude_decimal"],
            name=point["name"],
        )
        gpx.waypoints.append(p)
    
    for route in nav_data["routes"]:
        r = gpxpy.gpx.GPXRoute(name=route["name"])
        for point in route["points"]:
            p = gpxpy.gpx.GPXRoutePoint(
                latitude=point["latitude_decimal"],
                longitude=point["longitude_decimal"],
                name=point["name"],
            )
            r.points.append(p)
        gpx.routes.append(r)

    with open(file_name, "w") as f:
        f.write(gpx.to_xml(version="1.1"))

    return 0
