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
            result = max(self.flash_erase(hx), result)

        return result


    def dump(self, hx):
        if self.args.gpx:
            logger.info("Reading nav data from handset")
            raw_nav_data = hx.config.read_nav_data(True)
            logger.info("Writing GPX nav data to `{}`".format(self.args.gpx))
            return write_gpx(raw_nav_data, self.args.gpx)
        return 0


    def flash_erase(self, hx):
        nav_data = { "waypoints": [], "routes": [] }

        if self.args.flash:
            if self.args.gpx:
                logger.info("Reading GPX nav data from `{}`".format(self.args.gpx))
                nav_data = read_gpx(self.args.gpx)

            logger.info(log_nav_data("Read {w} waypoint{ws} and {r} route{rs} from file", nav_data))
            if self.args.erase:
                logger.info("Will replace nav data on device")
            else:
                logger.info("Will append to nav data on device")

                logger.info("Reading nav data from handset")
                raise NotImplementedError

        logger.info(log_nav_data("In total {w} waypoint{ws} and {r} route{rs}", nav_data))
        if nav_data_oversized(nav_data, hx):
            return 10
        
        logger.info("Writing nav data to handset")
        hx.config.write_nav_data(nav_data, True)

        return 0


def log_nav_data(text: str, nav_data: dict) -> str:
    waypoint_count = len(nav_data["waypoints"])
    route_count = len(nav_data["routes"])
    return text.format(
            w = waypoint_count, ws = "s" if waypoint_count != 1 else "",
            r = route_count,    rs = "s" if route_count != 1 else "" )


def nav_data_oversized(nav_data: dict, hx: object) -> bool:
    limits = hx.config.limits()
    oversized = False
    if len(nav_data["waypoints"]) > limits["waypoints"]:
        logger.critical("Too many waypoints to fit on device (maximum: {})".format(limits["waypoints"]))
        oversized = True
    if len(nav_data["routes"]) > limits["routes"]:
        logger.critical("Too many routes to fit on device (maximum: {})".format(limits["routes"]))
        oversized = True
    return oversized


def read_gpx(file_name: str) -> dict:
    gpx = gpxpy.parse(open(file_name, 'r'))
    nav_data = { "waypoints": [], "routes": [] }
    index = 0
    # Known issue: Route/waypoint relationships read from device are not
    # stored in GPX, resulting in a profliferation of duplicate waypoints
    # when routes that had been dumped from the device are flashed back.
    # See GH #30 for a brief discussion of possible solutions.

    for p in gpx.waypoints:
        index += 1
        point = {
            "latitude": p.latitude,
            "longitude": p.longitude,
            "name": p.name,
            "id": index,
        }
        nav_data["waypoints"].append(point)

    for r in gpx.routes:
        route = { "name": r.name, "points": [] }
        for p in r.points:
            index += 1
            point = {
                "latitude": p.latitude,
                "longitude": p.longitude,
                "name": p.name,
                "id": index,
            }
            route["points"].append(point)
            nav_data["waypoints"].append(point)
        nav_data["routes"].append(route)

    return nav_data


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
