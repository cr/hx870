from json import load
import pytest
from struct import pack

from hxtool import config, locus
from hxtool.cli.gpslog import to_hm
from hxtool.main import main
from hxtool.protocol import GenericHXProtocol, GPSModuleSilent, MediaTekProtocol
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


def lost_module(radio: int, module: int, **state):
    """A simulator whose radio and GPS module are left at the given speeds, and a connection that gives up fast"""
    sim = HXSimulator(config.HX870Config, mode="CP", loop_delay=0.0005)
    sim.gps_log = SAMPLE_LOG
    sim.gps_radio_baudrate, sim.gps_baudrate = radio, module
    for name, value in state.items():
        setattr(sim, name, value)
    sim.start()
    gps = gps_of(sim)
    gps.p.conn.s.timeout = 0.2  # every unanswered sync costs one timeout
    return sim, gps


@pytest.mark.parametrize("radio, module, requested, what", [
    (115200, 9600, [9600], "the radio's side was left at the high speed"),
    (9600, 115200, [9600, 115200, 9600], "the module was left at the high speed"),
    (9600, 38400, [9600, 115200, 57600, 38400, 9600], "the module sits at a speed the radio never looks for"),
    (9600, 4800, [9600, 115200, 57600, 38400, 19200, 14400, 4800, 9600], "the last speed of the ladder"),
])
def test_lost_module_is_found_and_brought_back(kill_sims, radio, module, requested, what):
    sim, gps = lost_module(radio, module)

    assert gps.read_log() == SAMPLE_LOG, what
    assert (sim.gps_radio_baudrate, sim.gps_baudrate) == (9600, 9600), "both ends at the speed the firmware expects"
    assert sim.gps_baudrates == requested, "the two likely speeds first, then the rest, then back"


def test_module_silenced_at_the_high_speed_is_recovered(kill_sims):
    # A second switch to 115200 silences the module until it is switched to another speed
    sim, gps = lost_module(115200, 115200, gps_stunned=True)

    assert gps.read_log() == SAMPLE_LOG
    assert (sim.gps_radio_baudrate, sim.gps_baudrate) == (9600, 9600)
    assert sim.gps_baudrates == [9600]


def test_module_left_at_the_high_speed_with_the_radio(kill_sims):
    # A run that died mid-transfer: both ends talk at 115200, which the host cannot tell. A second
    # switch to that speed silences the module, so the fast transfer fails
    sim, gps = lost_module(115200, 115200)

    with pytest.raises(TimeoutError):
        gps.read_log(fast=True)
    assert (sim.gps_radio_baudrate, sim.gps_baudrate) == (9600, 9600)
    assert gps.read_log() == SAMPLE_LOG, "the module answers again at the default speed"


def test_switch_back_survives_a_lost_command(kill_sims):
    # The radio now and then cuts the end off its own switch command: the module then stays where it
    # is and only executes the switch when the radio next talks to it at its speed
    sim, gps = lost_module(9600, 38400, gps_cut_switches=1)

    assert gps.read_log() == SAMPLE_LOG
    assert (sim.gps_radio_baudrate, sim.gps_baudrate) == (9600, 9600)
    assert sim.gps_baudrates == [9600, 115200, 57600, 38400, 9600, 38400, 9600]


def test_dead_module_is_reported_and_the_radio_left_at_the_default_speed(kill_sims):
    sim, gps = lost_module(9600, 9600, gps_dead=True)

    with pytest.raises(GPSModuleSilent) as error:
        gps.read_log()
    assert error.value.log_data is None
    assert sim.gps_baudrates == [9600, 115200, 57600, 38400, 19200, 14400, 4800, 9600], "every speed once"
    assert sim.gps_radio_baudrate == 9600


def test_failed_fast_transfer_fails_with_the_module_restored(kill_sims, monkeypatch):
    sim, gps = lost_module(9600, 9600)
    read_lines = MediaTekProtocol._read_log_lines

    def no_header_at_the_high_speed(self, progress=None):
        if sim.gps_radio_baudrate == 115200:
            raise TimeoutError("no log header")
        return read_lines(self, progress)

    monkeypatch.setattr(MediaTekProtocol, "_read_log_lines", no_header_at_the_high_speed)
    with pytest.raises(TimeoutError, match="no log header"):
        gps.read_log(fast=True)
    assert sim.gps_baudrates == [115200, 9600], "no second attempt, just back to the default speed"
    assert (sim.gps_radio_baudrate, sim.gps_baudrate) == (9600, 9600)
    assert gps.read_log() == SAMPLE_LOG, "where the module answers"


@pytest.mark.parametrize("transfer_completes", [True, False])
def test_module_silent_after_a_fast_transfer(kill_sims, monkeypatch, transfer_completes):
    # Seen on both radios: after the transfer the module answers at no speed any more
    sim, gps = lost_module(9600, 9600)
    read_lines = MediaTekProtocol._read_log_lines

    def then_silent(self, progress=None):
        data = read_lines(self, progress)
        sim.gps_dead = True
        if not transfer_completes:
            raise TimeoutError("log line missing")
        return data

    monkeypatch.setattr(MediaTekProtocol, "_read_log_lines", then_silent)
    with pytest.raises(GPSModuleSilent) as error:
        gps.read_log(fast=True)
    assert error.value.log_data == (SAMPLE_LOG if transfer_completes else None), "a complete log is not thrown away"
    assert sim.gps_radio_baudrate == 9600


def test_module_is_left_alone_while_it_switches(kill_sims, monkeypatch):
    # A command sent too soon after a switch is lost: the settle time is not optional
    sim = HXSimulator(config.HX870Config, mode="CP", loop_delay=0.0005)
    sim.gps_log = SAMPLE_LOG
    sim.gps_settle = 0.5
    sim.start()
    gps = gps_of(sim)

    monkeypatch.setattr(MediaTekProtocol, "SWITCH_SETTLE", 0.6)
    assert gps.read_log(fast=True) == SAMPLE_LOG


@pytest.fixture(name="sims")
def fixture_started_simulators(monkeypatch, sims_with_log):
    """The simulators a CLI run starts, for a look at them afterwards"""
    started = []
    sim_start = HXSimulator.start

    def start_and_note(self):
        started.append(self)
        sim_start(self)

    monkeypatch.setattr(HXSimulator, "start", start_and_note)
    return started


@pytest.mark.parametrize("selector, options, requested", [
    (["-t", "0"], [], []),
    (["-m", "HX891", "-t", "0"], [], []),
    (["-m", "HX890", "-t", "0"], [], []),
    (["-t", "0"], ["--fast"], [115200, 9600]),
])
def test_gpslog_speed(tmpdir, kill_sims, sims, selector, options, requested):
    assert main(["--simulator"] + selector + ["gpslog", "--raw", str(tmpdir.join("log.raw"))] + options) == 0
    assert [rate for sim in sims for rate in sim.gps_baudrates] == requested, "9600 unless asked, on every model"


def test_gpslog_fast_option_warns(capsys):
    with pytest.raises(SystemExit):
        main(["gpslog", "--help"])
    assert "unstable" in " ".join(capsys.readouterr().out.split())


def test_gpslog_failed_fast_transfer_is_an_error(tmpdir, kill_sims, sims, monkeypatch, capsys):
    def no_header(self, progress=None):
        raise TimeoutError("no log header")

    monkeypatch.setattr(MediaTekProtocol, "_read_log_lines", no_header)
    log_file = tmpdir.join("log.raw")
    assert main(["--simulator", "-t", "0", "gpslog", "--fast", "--raw", str(log_file)]) != 0
    assert not log_file.exists()
    log = capsys.readouterr().err
    assert "ERROR Fast log transfer failed (no log header)" in log
    assert "without --fast" in log
    assert all((sim.gps_radio_baudrate, sim.gps_baudrate) == (9600, 9600) for sim in sims), "left in a sane state"


def test_gpslog_silent_module_keeps_the_log_and_says_what_to_do(tmpdir, kill_sims, sims, monkeypatch, capsys):
    read_lines = MediaTekProtocol._read_log_lines

    def then_silent(self, progress=None):
        data = read_lines(self, progress)
        for sim in sims:
            sim.gps_dead = True
        self.p.conn.s.timeout = 0.05  # every speed is tried twice
        return data

    monkeypatch.setattr(MediaTekProtocol, "_read_log_lines", then_silent)
    log_file = tmpdir.join("log.raw")
    assert main(["--simulator", "-t", "0", "gpslog", "--fast", "--erase", "--raw", str(log_file)]) != 0
    assert log_file.read_binary() == SAMPLE_LOG, "the log was read completely before the module fell silent"
    errors = [line for line in capsys.readouterr().err.splitlines() if " ERROR " in line]
    assert any("Reboot the radio" in line and "hxtool firmware --reboot" in line for line in errors), \
        "an instruction, not just a timeout"
    assert all(sim.gps_log == SAMPLE_LOG for sim in sims), "nothing is erased"


def test_gpslog_module_silent_from_the_start_says_to_reboot(kill_sims, monkeypatch, capsys):
    # The locked state as it is met by any later run: no answer at any speed, before anything was read
    monkeypatch.setattr(MediaTekProtocol, "_sync_when_idle", lambda self, patience=180: False)
    assert main(["--simulator", "-t", "0", "gpslog", "--print"]) != 0
    log = capsys.readouterr().err
    assert "CRITICAL GPS module lost (GPS module does not answer at any speed)" in log
    assert any("Reboot the radio" in line and "hxtool firmware --reboot" in line
               for line in log.splitlines() if " ERROR " in line)


@pytest.fixture(name="busy_sim")
def fixture_simulator_with_abandoned_dump(kill_sims):
    """A radio whose GPS module is in the middle of a log dump that nobody is reading any more,
    as after Ctrl-C on a slow transfer: it streams for another four seconds"""
    sim = HXSimulator(config.HX870Config, mode="CP", loop_delay=0.0005)
    sim.gps_log = SAMPLE_LOG
    sim.gps_line_delay = 0.1
    sim.start()
    abandoned = GenericHXProtocol(sim.tty)
    abandoned.send("$PMTK", ["622", "1"])
    assert abandoned.receive(nmea=True).args[:2] == ["LOX", "0"], "the dump has started"
    abandoned.conn.s.close()
    yield sim


def test_connection_copes_with_a_streaming_gps_module(busy_sim):
    p = GenericHXProtocol(busy_sim.tty)
    assert (p.cp_mode, p.nmea_mode) == (True, False), "CP mode is recognised although GPS sentences stream in"
    assert p.read_config_memory(0x0100, 6) == b"AM057N", "and config memory is read past them"
    assert p.get_firmware_version() == "23.42"


def test_busy_gps_module_is_waited_for(busy_sim):
    gps = MediaTekProtocol(GenericHXProtocol(busy_sim.tty))
    assert gps.read_log() == SAMPLE_LOG
    assert busy_sim.gps_baudrates == [], "a module that is merely busy is not treated as deaf"
