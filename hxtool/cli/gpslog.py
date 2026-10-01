import datetime
import gpxpy
import gpxpy.gpx
from json import dump
from logging import getLogger
from os.path import abspath

import hxtool
from . import ui
from .base import CliCommand
from hxtool.locus import FixQuality, Locus, LocusError

logger = getLogger(__name__)


class GpsLogCommand(CliCommand):

    name = "gpslog"
    help = "dump or clear GPS logger data"

    @staticmethod
    def setup_args(parser) -> None:
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
        parser.add_argument("-p", "--print",
                            help="print log content",
                            action="store_true")
        parser.add_argument("-e", "--erase",
                            help="erase GPS log data from device",
                            action="store_true")
        speed = parser.add_mutually_exclusive_group()
        speed.add_argument("--fast",
                           help="switch the GPS module to 115200 baud for the transfer (default where it is reliable)",
                           action="store_true")
        speed.add_argument("--slow",
                           help="read the log at the GPS module's default speed",
                           action="store_true")

    def run(self):

        hx = hxtool.get(self.args)
        if hx is None:
            return 10

        if not hx.comm.cp_mode:
            logger.critical("For GPS log functions, device must be in CP mode (MENU + ON)")
            return 10

        if hx.gps is None:
            logger.critical(f"GPS log functions are not supported by {hx.handle}")
            return 10

        result = 0

        hx.gps.ensure_ready()
        hx.gps.send("$PMTK", ["605"])  # Query GPS module firmware version
        _ = hx.gps.receive()

        stat = hx.gps.read_log_status()
        logger.info(f"Log size {stat['pages_used'] * 4}kB, "
                    f"{stat['slots_used']} trackpoints, "
                    f"{stat['usage_percent']}% full")
        if stat["full_stop"]:
            logger.warning("Log is full. Logging is halted until erased")
        elif stat['usage_percent'] >= 80:
            logger.warning("Log is almost full. Consider erasing soon")

        if self.args.gpx or self.args.json or self.args.raw or self.args.print:
            if stat["slots_used"] > 0 or self.args.raw:
                logger.info("Reading GPS log from handset")
                with ui.progress("Reading GPS log", "blocks") as progress:
                    fast = self.args.fast or (hx.gps_fast_log and not self.args.slow)
                    raw_log_data = hx.gps.read_log(progress=progress, fast=fast)
                logger.info(f"Received {len(raw_log_data)} bytes of raw log data from handset")
            else:
                logger.info("Nothing to read from handset")
                raw_log_data = None
        else:
            raw_log_data = None

        if raw_log_data is not None:

            if self.args.print:
                result = max(dump_log(raw_log_data), result)

            if self.args.gpx:
                logger.info("Exporting GPX log data to `%s`", self.args.gpx)
                result = max(write_gpx(raw_log_data, self.args.gpx), result)

            if self.args.json:
                logger.info("Exporting JSON log data to `%s`", self.args.json)
                result = max(write_json(raw_log_data, self.args.json), result)

            if self.args.raw:
                logger.info("Exporting raw log data to `%s`", self.args.raw)
                result = max(write_raw(raw_log_data, self.args.raw), result)

        if self.args.erase:
            logger.info("Erasing GPS log data from device")
            hx.gps.erase_log()

        return result


# LOCUS fix quality to the GPX fix element, where GPX has a word for it
GPX_FIX = {
    FixQuality.INVALID.value: "none",
    FixQuality.SPS.value: "3d",
    FixQuality.DGPS.value: "dgps",
    FixQuality.PPS.value: "pps",
}


def write_gpx(log_data: bytes, file_name: str) -> int:
    try:
        log = Locus(log_data)
    except LocusError:
        logger.warning("Log is blank. Not writing empty GPX file")
        return 0

    gpx = gpxpy.gpx.GPX()

    # Create first track in our GPX:
    gpx_track = gpxpy.gpx.GPXTrack()
    gpx.tracks.append(gpx_track)

    # Create first segment in our GPX track:
    gpx_segment = gpxpy.gpx.GPXTrackSegment()
    gpx_track.segments.append(gpx_segment)

    # Create points. GPX 1.0 has elements for everything the log records;
    # 1.1 dropped speed and course in favour of vendor extensions (see #30).
    for point in log:
        p = gpxpy.gpx.GPXTrackPoint(
            time=utc_time(point["utc_time"]),
            latitude=point["latitude"],
            longitude=point["longitude"],
            elevation=point["height"] if "height" in point else None,
            speed=point["speed"] if "speed" in point else None,  # m/s, as the log records it
        )
        if "heading" in point:
            p.course = point["heading"]
        if "fix_type" in point:
            p.type_of_gpx_fix = GPX_FIX.get(point["fix_type"])
        if "satellites" in point:
            p.satellites = point["satellites"]
        gpx_segment.points.append(p)

    with open(file_name, "w") as f:
        f.write(gpx.to_xml(version="1.0"))

    return 0


def write_json(log_data: bytes, file_name: str) -> int:
    try:
        log = Locus(log_data)
    except LocusError:
        logger.warning("Log is blank. Not writing empty JSON log")
        return 0
    jlog = {
        "trackpoints": []
    }
    for wp in log:
        new_wp = {}
        for k in wp:
            new_wp[k] = wp[k]
        jlog["trackpoints"].append(new_wp)
    with open(file_name, "w") as f:
        dump(jlog, f, indent=4)
    return 0


def write_raw(log_data: bytes, file_name: str) -> int:
    if log_data.startswith(b'\xff' * 16):
        logger.info("Log is blank")
    with open(file_name, "wb") as f:
        f.write(log_data)
    return 0


def utc_time(timestamp: int) -> datetime.datetime:
    return datetime.datetime.fromtimestamp(timestamp, datetime.timezone.utc)


def to_hm(deg: float) -> tuple[int, float]:
    """
    Split degrees into whole degrees and minutes, disregarding the sign.
    Minutes are rounded to the four decimals that get printed, so that
    they can never show up as 60.0000.
    """
    degrees, minutes = divmod(round(abs(deg) * 600000), 600000)
    return degrees, minutes / 10000


def dump_log(log_data):
    try:
        log = Locus(log_data)
    except LocusError:
        logger.info("Log is blank. Nothing to print")
        return 0
    for wp in log:
        lat_deg, lat_min = to_hm(wp['latitude'])
        lat_dir = 'N' if wp['latitude'] >= 0 else 'S'
        lon_deg, lon_min = to_hm(wp['longitude'])
        lon_dir = 'E' if wp['longitude'] >= 0 else 'W'
        print(f"{utc_time(wp['utc_time']).strftime('%Y-%m-%dT%H:%M:%SZ')}\t"
              f"{lat_deg:02d}°{lat_min:07.04f}{lat_dir}\t"
              f"{lon_deg:03d}°{lon_min:07.04f}{lon_dir}\t"
              f"{wp['height']:d}m\t"
              f"{wp['heading']:3d}°\t"
              f"{wp['speed']:2d}m/s\t")
    return 0
