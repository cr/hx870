# -*- coding: ascii -*-

import pytest
import re

import hxtool
from hxtool.device import enumerate, GX1400, HX870, models, read_magic
from hxtool.main import main
from hxtool.protocol import GenericHXProtocol, ProtocolError
from hxtool.simulator import HXSimulator
import serial
from time import sleep


def comport(tty, meta):
    port = serial.tools.list_ports_common.ListPortInfo(tty)
    port.vid, port.pid, port.description = meta["vid"], meta["pid"], meta["desc"]
    return port


def enumerate_devices(*args):
    devices = hxtool.device.enumerate_devices(*args)
    return [(c.model.__name__, c.tty) for c in devices]  # The class name is easier to test for


def identified_devices(*args):
    return [(c.model.__name__, c.tty, c.identified) for c in hxtool.device.enumerate_devices(*args)]


@pytest.fixture(name="monkeypatch_read_magic")
def fixture_read_magic(monkeypatch):
    conn = dict()

    def mock_hxtty(self, tty, timeout=2, baudrate=9600):
        conn["tty"], conn["baudrate"] = tty, baudrate

    def mock_sync(self, flush_output=False, flush_input=True):
        if conn["tty"] == "/dev/gx1400" and conn["baudrate"] != 38400:
            raise TimeoutError
        if conn["tty"] == "/dev/busy":
            raise OSError
        if conn["tty"] == "/dev/alien":
            raise ProtocolError  # response unlike that of a Yaesu/SH device

    def mock_read_config_memory(self, offset, length):
        mock_sync(self)
        if offset != 0 or length != 2:
            raise NotImplementedError
        if conn["tty"] == "/dev/hx870":
            return b"\x03\x67"
        if conn["tty"] == "/dev/gx1400":
            return b"\x05\x78"
        return b"\xff\xff"

    monkeypatch.setattr(hxtool.tty.GenericHXTTY, "__init__", mock_hxtty)
    monkeypatch.setattr(GenericHXProtocol, "sync", mock_sync)
    monkeypatch.setattr(GenericHXProtocol, "read_config_memory", mock_read_config_memory)
    yield None


def test_read_magic(monkeypatch_read_magic):
    assert read_magic("/dev/gx1400") == 1400, "GX1400: default baudrate"
    assert read_magic("/dev/gx1400", {38400}) == 1400, "GX1400: 38400 baud"
    assert read_magic("/dev/gx1400", {9600}) == 0, "GX1400: requires 38400 baud"
    assert read_magic("/dev/gx1400", {4800, 9600, 19200, 38400, 57600}) == 1400, "large set"

    assert read_magic("/dev/hx870", {0}) == 871, "HX870: ignores baudrate"
    assert read_magic("/dev/hx870", {}) == 0, "empty set fails"

    assert read_magic("/dev/alien") == 0, "ignores device not made by Yaesu/SH"
    assert read_magic("/dev/busy") == 0, "ignores device that raises an OSError"


def test_enumerate_devices(monkeypatch, caplog):

    def mock_comports(links=None):
        return [comport(tty, devices[tty]) for tty in devices.keys()]

    def mock_read_magic(tty, baudrates=None):
        probed.append(tty)
        probed_rates.update(baudrates or ())
        return devices[tty]["magic"] if tty in devices else unlisted.get(tty, 0)

    probed = []
    probed_rates = set()
    unlisted = {"/dev/pty7": 890}  # ports the system does not list

    def mock_grep(regexp):
        return (port for port in mock_comports() if re.search(regexp, port.device))

    monkeypatch.setattr(serial.tools.list_ports, "comports", mock_comports)
    monkeypatch.setattr(serial.tools.list_ports, "grep", mock_grep)
    monkeypatch.setattr(hxtool.device, "read_magic", mock_read_magic)

    # Detection by USB metadata

    devices = {
        "/dev/gx0": dict(vid=None, pid=None, desc="GX1400", magic=1400),
        "/dev/hx00": dict(vid=0x26aa, pid=0x10, desc="HX870", magic=871),
        "/dev/hx0": dict(vid=0x26aa, pid=0x1e, desc="HX890", magic=890),
        "/dev/ix0": dict(vid=0x26aa, pid=0x2e, desc="HX890", magic=891),
    }

    assert enumerate_devices(models.values(), None) == [
        ("HX870", "/dev/hx00"),
        ("HX890", "/dev/hx0"),
        ("HX891", "/dev/ix0"),
    ], "all devices with USB metadata"

    assert enumerate_devices(models.values(), "/hx0") == [
        ("HX870", "/dev/hx00"),
        ("HX890", "/dev/hx0"),
    ], "force_device grep match"

    assert enumerate_devices(models.values(), "/dev/hx0") == [
        ("HX890", "/dev/hx0"),
    ], "force_device exact match"

    assert enumerate_devices([HX870], "/dev/hx0") == [
        ("HX870", "/dev/hx0"),
    ], "force a wrong model class"  # both force_model and force_device

    # A port is identified when USB metadata or the user's forced model says what it is
    assert identified_devices(models.values(), "/dev/hx0") == [("HX890", "/dev/hx0", True)], "by USB metadata"
    assert identified_devices([HX870], "/dev/hx0") == [("HX870", "/dev/hx0", True)], "by forced model"

    assert not enumerate_devices(models.values(), "blah"), "invalid force_device"
    assert "Invalid device selector blah" in caplog.text

    # Unlisted ports are taken literally

    probed.clear()
    assert enumerate_devices(models.values(), "/dev/pty7") == [
        ("HX890", "/dev/pty7"),
    ], "unlisted force_device detected by config magic"
    assert probed == ["/dev/pty7"], "only the given port is probed"
    assert probed_rates == {38400}, "at one rate: the USB models' own rate is not a probing rate"

    probed.clear()
    assert enumerate_devices([GX1400], "/dev/pty7") == [
        ("GX1400", "/dev/pty7"),
    ], "unlisted force_device with force_model"
    assert probed == [], "both forced skips probing"
    assert identified_devices(models.values(), "/dev/pty7") == [("HX890", "/dev/pty7", False)], "by magic only"

    # Detection by config magic

    devices = {
        "/dev/cu.URT1": dict(vid=None, pid=None, desc="HX870", magic=871),
        "/dev/gx0": dict(vid=None, pid=None, desc="GX1400", magic=1400),
        "/dev/hx1": dict(vid=None, pid=None, desc="HX890", magic=891),
    }

    assert enumerate_devices([GX1400]) == [
        ("GX1400", "/dev/gx0"),
    ], "given model only"

    assert enumerate_devices(models.values()) == [
        ("GX1400", "/dev/gx0"),
        ("HX891", "/dev/hx1"),
    ], "exclude_ports: skip URT1"

    hxtool.device.include_ports = ["/dev/hx1"]
    assert enumerate_devices(models.values()) == [
        ("HX891", "/dev/hx1"),
    ], "include_ports: only hx1"


def test_enumerate_force_model(kill_sims):
    devices = [type(d).__name__ for d in enumerate(force_model="gx1400", add_simulator=True)]
    assert devices == ["GX1400"]
    assert not enumerate(force_model="GX123", add_simulator=True)

    devices = enumerate(force_device="0", force_model="HX891", add_simulator=True)
    assert [type(d).__name__ for d in devices] == ["HX891Sim"], "index within the model's own list"
    assert devices[0].cp_mode


def test_enumerate_force_device(kill_sims):
    all_devices = enumerate(add_simulator=True)
    simulated = [type(d).__name__ for d in all_devices]
    assert simulated == ["HX870Sim", "HX870Sim", "HX890Sim", "HX890Sim", "HX891Sim", "HX891Sim", "GX1400"]
    for i in range(len(all_devices)):
        devices = enumerate(force_device=f"{i}", add_simulator=True)
        assert len(devices) == 1
        assert type(devices[0]) is type(all_devices[i])
        assert devices[0].cp_mode == all_devices[i].cp_mode

    assert not enumerate(force_device=f"{len(all_devices) + 1}", add_simulator=True)


@pytest.mark.parametrize("model", [HX870, GX1400])
def test_enumerate_unlisted_device(kill_sims, monkeypatch, model):
    # The simulator's pty is a port that the system does not list
    sim = HXSimulator(model.config_model, mode="CP")
    sim.c[0:2] = model.config_model.CONFIG_MAGIC.to_bytes(2, "big")
    sim.start()

    devices = enumerate(force_device=sim.tty, force_model=model.handle)
    assert len(devices) == 1
    assert type(devices[0]) is model
    assert devices[0].tty == sim.tty
    assert devices[0].cp_mode

    # The simulator reads its input far slower than a real device. Give it
    # time to consume the tail of the probe before the port is opened again,
    # because opening flushes whatever the simulator has not read by then.
    def slow_read_magic(*args):
        magic = read_magic(*args)
        sleep(0.2)
        return magic

    monkeypatch.setattr(hxtool.device, "read_magic", slow_read_magic)

    devices = enumerate(force_device=sim.tty)
    assert len(devices) == 1
    assert type(devices[0]) is model, "model detected by config magic"
    assert devices[0].cp_mode


def test_hxtool_devices_silent_nmea(capsys, kill_sims, monkeypatch):
    # A simulated radio whose GPS never says anything
    sim_start = HXSimulator.start

    def start_silent(self):
        if self.mode == "NMEA":
            self.nmea_delay = None
        sim_start(self)

    monkeypatch.setattr(HXSimulator, "start", start_silent)

    assert main(["--simulator", "-m", "HX870", "devices"]) == 0
    outerr = capsys.readouterr()
    assert "does not behave like HX hardware" not in outerr.err
    lines = [line for line in outerr.out.strip("\n").split("\n") if "Simulator" in line]
    assert len(lines) == 2
    assert "CP mode" in lines[0]
    assert "NMEA mode (no output seen)" in lines[1]
