# -*- coding: ascii -*-

import pytest

import hxtool
from hxtool.device import enumerate, GX1400, HX870, models, read_magic
from hxtool.protocol import GenericHXProtocol, ProtocolError
from hxtool.simulator import HXSimulator
import serial
from sys import platform


def comport(tty, meta):
    port = serial.tools.list_ports_common.ListPortInfo(tty)
    port.vid, port.pid, port.description = meta["vid"], meta["pid"], meta["desc"]
    return port


def enumerate_devices(*args):
    devices = hxtool.device.enumerate_devices(*args)
    return [(m.__name__, t) for m, t in devices]  # The class name is easier to test for


@pytest.fixture(name="kill_sims")
def kill_simulator_threads_fixture():
    if platform.startswith("win"):
        pytest.skip("Skipping simulator tests on Windows", allow_module_level=True)
    yield None
    HXSimulator.stop_instances()
    HXSimulator.join_instances()


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


def test_enumerate_devices(monkeypatch):

    def mock_comports(links=None):
        return [comport(tty, devices[tty]) for tty in devices.keys()]

    def mock_read_magic(tty, baudrates=None):
        return devices[tty]["magic"]

    monkeypatch.setattr(serial.tools.list_ports, "comports", mock_comports)
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

    assert not enumerate_devices(models.values(), "blah"), "invalid force_device"

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


def test_enumerate_all(kill_sims):
    devices = [type(d).__name__ for d in enumerate(add_simulator=True)]
    assert "HX870Sim" in devices
    assert "HX890Sim" in devices
    assert "HX891Sim" in devices
    assert "GX1400" in devices
    assert len(devices) == 7


def test_enumerate_force_model(kill_sims):
    devices = [type(d).__name__ for d in enumerate(force_model="gx1400", add_simulator=True)]
    assert "GX1400" in devices
    assert len(devices) == 1

    assert not enumerate(force_model="GX123", add_simulator=True)


def test_enumerate_force_device(kill_sims):
    all_devices = enumerate(add_simulator=True)
    for i in range(len(all_devices)):
        devices = enumerate(force_device=f"{i}", add_simulator=True)
        assert len(devices) == 1
        assert type(devices[0]) is type(all_devices[i])
        assert devices[0].cp_mode == all_devices[i].cp_mode

    assert not enumerate(force_device=f"{len(all_devices) + 1}", add_simulator=True)


def test_enumerate_force_both(kill_sims):
    devices = enumerate(force_device="0", force_model="HX891", add_simulator=True)
    assert len(devices) == 1
    assert type(devices[0]).__name__ == "HX891Sim"
    assert devices[0].cp_mode
