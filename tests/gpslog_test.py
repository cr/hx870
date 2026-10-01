from json import load
import pytest
from struct import pack

from hxtool import config, locus
from hxtool.cli.gpslog import to_hm
from hxtool.main import main
from hxtool.protocol import GenericHXProtocol, MediaTekProtocol
from hxtool.simulator import HXSimulator

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


def gps_of(sim) -> MediaTekProtocol:
    return MediaTekProtocol(GenericHXProtocol(sim.tty))


def test_log_is_read_at_high_speed_and_the_module_restored(kill_sims):
    sim = HXSimulator(config.HX870Config, mode="CP", loop_delay=0.0005)
    sim.gps_log = SAMPLE_LOG
    sim.start()
    gps = gps_of(sim)

    assert gps.read_log(fast=True) == SAMPLE_LOG
    assert sim.gps_baudrates == [115200, 9600], "switched up for the transfer and back down, nothing else"
    assert sim.gps_baudrate == 9600, "the module is left at the speed the firmware expects"
    assert gps.read_log_status()["slots_used"] == 4, "and answers as usual afterwards"

    sim.gps_baudrates.clear()
    assert gps.read_log() == SAMPLE_LOG
    assert sim.gps_baudrates == [], "the default transfer never touches the speed"


def test_module_speed_is_restored_after_a_failed_transfer(kill_sims, monkeypatch):
    sim = HXSimulator(config.HX870Config, mode="CP", loop_delay=0.0005)
    sim.gps_log = SAMPLE_LOG
    sim.start()
    gps = gps_of(sim)

    def interrupted(self, progress=None):
        raise KeyboardInterrupt

    monkeypatch.setattr(MediaTekProtocol, "_read_log_lines", interrupted)
    with pytest.raises(KeyboardInterrupt):
        gps.read_log(fast=True)
    assert sim.gps_baudrates == [115200, 9600], "even an interrupted transfer ends at 9600"
    assert sim.gps_baudrate == 9600


@pytest.mark.parametrize("state, what", [
    (115200, "a previous run died mid-transfer"),
    (None, "the module was left deaf"),
])
def test_unresponsive_module_is_recovered(kill_sims, state, what):
    sim = HXSimulator(config.HX870Config, mode="CP", loop_delay=0.0005)
    sim.gps_log = SAMPLE_LOG
    sim.gps_baudrate = state
    sim.start()
    gps = gps_of(sim)

    assert gps.read_log(fast=True) == SAMPLE_LOG, what
    assert sim.gps_baudrate == 9600


def test_module_is_left_alone_while_it_switches(kill_sims, monkeypatch):
    # A command sent too soon after a switch is lost: the settle time is not optional
    sim = HXSimulator(config.HX870Config, mode="CP", loop_delay=0.0005)
    sim.gps_log = SAMPLE_LOG
    sim.gps_settle = 0.5
    sim.start()
    gps = gps_of(sim)

    monkeypatch.setattr(MediaTekProtocol, "SWITCH_SETTLE", 0.6)
    assert gps.read_log(fast=True) == SAMPLE_LOG


@pytest.mark.parametrize("selector, options, switched", [
    (["-t", "0"], [], True),  # HX870: fast where the module takes it
    (["-t", "0"], ["--slow"], False),
    (["-m", "HX891", "-t", "0"], [], False),  # HX891BT: its module does not
    (["-m", "HX891", "-t", "0"], ["--fast"], True),
    (["-m", "HX890", "-t", "0"], [], False),  # HX890: taken to work like the HX891BT
])
def test_gpslog_speed_by_model(tmpdir, kill_sims, monkeypatch, selector, options, switched):
    switches = []
    sim_stop = HXSimulator.stop

    def stop_and_record(self):
        switches.extend(self.gps_baudrates)
        sim_stop(self)

    monkeypatch.setattr(HXSimulator, "stop", stop_and_record)
    assert main(["--simulator"] + selector + ["gpslog", "--raw", str(tmpdir.join("log.raw"))] + options) == 0
    assert switches == ([115200, 9600] if switched else [])
