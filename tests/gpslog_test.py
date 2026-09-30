# -*- coding: utf-8 -*-

from json import load
import pytest
from struct import pack
from sys import platform

from hxtool import locus
from hxtool.cli.gpslog import to_hm
from hxtool.main import main
from hxtool.simulator import HXSimulator

# The simulator doesn't work on Windows, so skip test if running on Windows
if platform.startswith("win"):
    pytest.skip("Skipping simulator tests on Windows", allow_module_level=True)


LOG_CONTENT = 0x7f  # UTC, fix type, latitude, longitude, height, speed, heading
LOG_CONTENT_NSAT = LOG_CONTENT | 1 << 12  # plus number of satellites


def log_sector(points, content=LOG_CONTENT) -> bytes:
    """points: (utc_time, latitude, longitude) or (utc_time, latitude, longitude, fix_type, satellites)"""
    header = pack("<HBBHHHHHB", 1, 1, 0x0b, content, 0, 60, 0, 0, 0x43)
    header += bytes([locus.checksum(header)])
    used = bytearray(b"\xff" * 44)  # one cleared bit per used slot, most significant bit first
    for i in range(len(points)):
        used[i // 8] &= ~(0x80 >> (i % 8)) & 0xff
    sector = header + used + bytes.fromhex("00fc8c1c")
    for point in points:
        utc_time, latitude, longitude = point[:3]
        fix_type, satellites = point[3:] if len(point) > 3 else (1, 7)
        record = pack("<IBffhHH", utc_time, fix_type, latitude, longitude, 5, 3, 90)
        if content & 1 << 12:
            record += pack("<B", satellites)
        sector += record + bytes([locus.checksum(record)])
    return sector.ljust(0x1000, b"\xff")


# One trackpoint per quadrant, all exactly representable as 32 bit floats
SAMPLE_LOG = log_sector([
    (1700000000, 54.5, 12.25),
    (1700000005, 54.5, -12.25),
    (1700000010, -33.75, 151.125),
    (1700000015, -0.5, -0.25),
])


@pytest.fixture(name="kill_sims")
def kill_simulator_threads_fixture():
    yield None
    HXSimulator.stop_instances()
    HXSimulator.join_instances()


@pytest.fixture(name="sims_with_log")
def fixture_simulators_with_gps_log(monkeypatch):
    sim_start = HXSimulator.start

    def start_with_log(self):
        self.gps_log = SAMPLE_LOG
        sim_start(self)

    monkeypatch.setattr(HXSimulator, "start", start_with_log)


def test_to_hm():
    assert to_hm(54.5) == (54, 30.0)
    assert to_hm(-54.5) == (54, 30.0), "Negative degrees convert like their absolute value"
    assert to_hm(-0.5) == (0, 30.0)
    assert to_hm(0.0) == (0, 0.0)
    assert to_hm(59.9999999) == (60, 0.0), "Minutes never round up to 60"
    degrees, minutes = to_hm(12.59927)
    assert degrees == 12
    assert abs(minutes - 35.9562) < 1e-9


def test_gpslog_print(capsys, sims_with_log, kill_sims):
    del sims_with_log, kill_sims

    assert main(["--simulator", "-t", "0", "gpslog", "--print"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 4
    assert out[0].startswith("2023-11-14T22:13:20Z\t"), "timestamps are printed as UTC"
    assert "\t54°30.0000N\t012°15.0000E\t" in out[0]
    assert "\t54°30.0000N\t012°15.0000W\t" in out[1]
    assert "\t33°45.0000S\t151°07.5000E\t" in out[2]
    assert "\t00°30.0000S\t000°15.0000W\t" in out[3]


def test_gpslog_export_and_erase(tmpdir, capsys, monkeypatch, sims_with_log, kill_sims):
    del sims_with_log, kill_sims
    json_file = tmpdir.join("log.json")
    raw_file = tmpdir.join("log.raw")
    gpx_file = tmpdir.join("log.gpx")

    args = ["--json", str(json_file), "--raw", str(raw_file), "--gpx", str(gpx_file)]
    assert main(["--simulator", "-t", "0", "gpslog"] + args) == 0
    assert raw_file.read_binary() == SAMPLE_LOG
    gpx = gpx_file.read_text("ascii")
    assert gpx.count("<trkpt ") == 4
    assert 'version="1.0"' in gpx and 'xmlns="http://www.topografix.com/GPX/1/0"' in gpx, "GPX 1.0"
    assert "<time>2023-11-14T22:13:20Z</time>" in gpx, "GPX timestamps are marked as UTC"
    assert gpx.count("<ele>5</ele>") == 4
    assert gpx.count("<speed>3</speed>") == 4, "speed is exported"
    assert gpx.count("<course>90</course>") == 4, "heading is exported"
    assert gpx.count("<fix>3d</fix>") == 4, "GPS fix quality is exported"
    assert "<sat>" not in gpx, "no satellite count in this log"
    with open(json_file) as f:
        trackpoints = load(f)["trackpoints"]
    assert len(trackpoints) == 4
    assert trackpoints[1]["latitude"] == 54.5
    assert trackpoints[1]["longitude"] == -12.25
    assert "4 trackpoints" in capsys.readouterr().err

    # All simulators are created anew on every run, so keep the erased one
    # around by checking the device state right after the erase
    erased = []
    sim_stop = HXSimulator.stop

    def stop_and_record(self):
        erased.append(self.gps_log == b"")
        sim_stop(self)

    monkeypatch.setattr(HXSimulator, "stop", stop_and_record)
    assert main(["--simulator", "-t", "0", "gpslog", "--erase"]) == 0
    assert erased.count(True) == 1, "Exactly the selected device has its log erased"


def test_gpslog_empty_log(tmpdir, capsys, kill_sims):
    del kill_sims
    gpx_file = tmpdir.join("log.gpx")
    json_file = tmpdir.join("log.json")

    args = ["--simulator", "-t", "0", "gpslog", "--print", "--gpx", str(gpx_file), "--json", str(json_file)]
    assert main(args) == 0, "Exporting an empty log is not an error"
    outerr = capsys.readouterr()
    assert outerr.out == ""
    assert "0 trackpoints" in outerr.err
    assert not gpx_file.exists()
    assert not json_file.exists()


def test_gpslog_gx1400(capsys, kill_sims):
    del kill_sims

    assert main(["--simulator", "-m", "GX1400", "gpslog"]) != 0
    assert "GPS log" in capsys.readouterr().err


def test_gpx_export_fix_and_satellites(tmpdir):
    from hxtool.cli.gpslog import write_gpx
    log = log_sector([
        (1700000000, 54.5, 12.25, 0, 0),  # no fix
        (1700000005, 54.5, 12.25, 1, 6),  # GPS
        (1700000010, 54.5, 12.25, 2, 9),  # differential GPS
        (1700000015, 54.5, 12.25, 3, 12),  # precise positioning
        (1700000020, 54.5, 12.25, 6, 4),  # dead reckoning: GPX has no word for it
    ], content=LOG_CONTENT_NSAT)
    gpx_file = tmpdir.join("log.gpx")
    assert write_gpx(log, str(gpx_file)) == 0
    gpx = gpx_file.read_text("ascii")
    assert gpx.count("<trkpt ") == 5
    for fix in ("none", "3d", "dgps", "pps"):
        assert gpx.count(f"<fix>{fix}</fix>") == 1
    assert gpx.count("<fix>") == 4, "unmappable fix types are left out"
    for sat in (0, 6, 9, 12, 4):
        assert f"<sat>{sat}</sat>" in gpx
