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


def log_sector(points) -> bytes:
    header = pack("<HBBHHHHHB", 0, 1, 8, LOG_CONTENT, 0, 5, 0, 0, 0)
    header += bytes([locus.checksum(header)])
    sector = header + b"\xff" * 0x30
    for utc_time, latitude, longitude in points:
        record = pack("<IBffhHH", utc_time, 1, latitude, longitude, 5, 3, 90)
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
    assert "\t54°30.0000N\t012°15.0000E\t" in out[0]
    assert "\t54°30.0000N\t012°15.0000W\t" in out[1]
    assert "\t33°45.0000S\t151°07.5000E\t" in out[2]
    assert "\t00°30.0000S\t000°15.0000W\t" in out[3]


def test_gpslog_export_and_erase(tmpdir, capsys, monkeypatch, sims_with_log, kill_sims):
    del sims_with_log, kill_sims
    json_file = tmpdir.join("log.json")
    raw_file = tmpdir.join("log.raw")

    assert main(["--simulator", "-t", "0", "gpslog", "--json", str(json_file), "--raw", str(raw_file)]) == 0
    assert raw_file.read_binary() == SAMPLE_LOG
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
