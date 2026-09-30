# -*- coding: utf-8 -*-

import logging
import pytest
from random import getrandbits
from serial import Serial
import subprocess
import sys
from sys import platform
from threading import enumerate
from time import sleep

from hxtool import config
from hxtool import device
from hxtool import simulator
from hxtool.protocol import GenericHXProtocol, ProtocolError

# The simulator doesn't work on Windows, so skip test if running on Windows
if platform.startswith("win"):
    pytest.skip("Skipping simulator tests on Windows", allow_module_level=True)


@pytest.fixture(name="cp_sim")
def fixture_cp_simulator():
    s = simulator.HXSimulator(config.HX870Config, mode="CP", loop_delay=0.0005)
    s.start()
    yield s
    s.stop()
    s.join(timeout=1)


@pytest.fixture(name="nmea_sim")
def fixture_nmea_simulator():
    s = simulator.HXSimulator(config.HX870Config, mode="NMEA", nmea_delay=0.2, loop_delay=0.01)
    s.start()
    yield s
    s.stop()
    s.join(timeout=1)


@pytest.fixture(name="kill_sims")
def kill_simulator_threads_fixture():
    yield None
    simulator.HXSimulator.stop_instances()
    simulator.HXSimulator.join_instances()


@pytest.mark.wip
def test_simulator_instance(kill_sims):
    del kill_sims

    sim_a = simulator.HXSimulator(config.HX870Config, mode="CP", loop_delay=0.001)
    sim_b = simulator.HXSimulator(config.HX890Config, mode="CP", loop_delay=0.001)
    sim_c = simulator.HXSimulator(config.HX891Config, mode="CP", loop_delay=0.001)
    sim_n = simulator.HXSimulator(config.HX891Config, mode="NMEA", nmea_delay=0.03, loop_delay=0.01)

    for sim in sim_a, sim_b, sim_c, sim_n:
        assert sim in simulator.HXSimulator.instances
        assert not sim.is_alive()
        sim.start()
        assert sim.is_alive()

    # No sims should ever share a device
    assert sim_a.tty != sim_b.tty != sim_c.tty != sim_n.tty

    ser_a = Serial(sim_a.tty, timeout=0.1)
    ser_b = Serial(sim_b.tty, timeout=0.1)
    ser_c = Serial(sim_c.tty, timeout=0.1)
    ser_n = Serial(sim_n.tty, timeout=0.1)

    # No serial ports to different sims should ever share a device
    assert ser_a.name != ser_b.name != ser_c.name != ser_n.name

    # Assume all sims appear in list of all the threads
    for sim in sim_a, sim_b, sim_c, sim_n:
        assert sim in enumerate()

    ser_a.write(b"#CMDSY\r\n")
    assert ser_a.readline() == b"#CMDOK\r\n"
    ser_a.write(b"#CMDSY\r\n")
    assert ser_a.readline() == b"#CMDOK\r\n"
    ser_b.write(b"#CMDSY\r\n")
    assert ser_b.readline() == b"#CMDOK\r\n"
    ser_c.write(b"#CMDSY\r\n")
    assert ser_c.readline() == b"#CMDOK\r\n"

    sim_a.stop()
    sim_a.join()
    assert not sim_a.is_alive()
    assert sim_b.is_alive()
    assert sim_c.is_alive()
    assert sim_n.is_alive()

    # Writing to stopped simulator should raise
    with pytest.raises(OSError):
        ser_a.write(b"#CMDSY\r\n")

    # Dump NMEA sentences from sim_n, which sends one every 30 ms
    sleep(0.1)
    assert ser_n.in_waiting > 0
    while ser_n.in_waiting > 0:
        assert ser_n.readline().startswith(b"$G")

    ser_b.write(b"#CMDSY\r\n")
    assert ser_b.readline() == b"#CMDOK\r\n"

    simulator.HXSimulator.stop_instances()
    simulator.HXSimulator.join_instances()

    for sim in sim_a, sim_b, sim_c, sim_n:
        assert not sim.is_alive()


def test_nmea_simulator(nmea_sim, kill_sims):
    del kill_sims

    s = Serial(nmea_sim.tty, timeout=1.5)

    # Like the real radio, the simulator answers neither P nor ? in NMEA mode,
    # it just keeps sending NMEA dummy messages
    s.flushInput()
    s.flushOutput()
    s.write(b"XP?P")
    m = s.readline()
    assert m.startswith(b"$GPLL") and m.endswith(b"\r\n"), "Simulator sends NMEA message"
    m = s.readline()
    assert m.startswith(b"$GPLL") and m.endswith(b"\r\n"), "Simulator keeps sending NMEA messages"
    m = s.readline()
    assert m.startswith(b"$GPLL") and m.endswith(b"\r\n"), "Simulator keeps sending NMEA messages still"

    s.write(b"P?")
    m = s.readline()
    assert m.startswith(b"$GPLL") and m.endswith(b"\r\n"), "Simulator ignores the CP mode handshake"


@pytest.mark.parametrize("identified", [False, True])
def test_detect_nmea_mode_streaming(nmea_sim, kill_sims, identified):
    del kill_sims
    p = GenericHXProtocol(nmea_sim.tty, identified=identified)
    assert (p.hx_hardware, p.nmea_mode, p.cp_mode) == (True, True, False)
    assert p.nmea_output_seen


def test_detect_nmea_mode_mid_sentence(kill_sims):
    del kill_sims
    sim = simulator.HXSimulator(config.HX870Config, mode="NMEA", nmea_delay=0.2, loop_delay=0.01, nmea_partial=True)
    sim.start()
    p = GenericHXProtocol(sim.tty)
    assert (p.hx_hardware, p.nmea_mode, p.cp_mode) == (True, True, False), "a partial sentence is still NMEA"


def test_detect_nmea_mode_silent(kill_sims, caplog):
    del kill_sims
    caplog.set_level(logging.INFO)
    sim = simulator.HXSimulator(config.HX870Config, mode="NMEA", nmea_delay=None, loop_delay=0.01)
    sim.start()

    p = GenericHXProtocol(sim.tty)
    assert (p.hx_hardware, p.nmea_mode, p.cp_mode) == (False, False, False), "silence on an unknown port"

    p = GenericHXProtocol(sim.tty, identified=True)
    assert (p.hx_hardware, p.nmea_mode, p.cp_mode) == (True, True, False), "silence on an identified HX"
    assert not p.nmea_output_seen
    assert "assuming NMEA mode" in caplog.text


def test_detect_nmea_mode_ping_reply(kill_sims):
    # HX891BT style: answers the handshake although its GPS is silent
    del kill_sims
    sim = simulator.HXSimulator(config.HX891Config, mode="NMEA", nmea_delay=None, loop_delay=0.01, nmea_ping=True)
    sim.start()
    p = GenericHXProtocol(sim.tty)
    assert (p.hx_hardware, p.nmea_mode, p.cp_mode) == (True, True, False), "the ping reply identifies the radio"
    assert not p.nmea_output_seen


@pytest.mark.parametrize("identified", [False, True])
def test_detect_cp_mode(cp_sim, kill_sims, identified):
    del kill_sims
    p = GenericHXProtocol(cp_sim.tty, identified=identified)
    assert (p.hx_hardware, p.nmea_mode, p.cp_mode) == (True, False, True)


def test_cp_simulator(cp_sim, kill_sims):
    del kill_sims

    s = Serial(cp_sim.tty, timeout=1.5)

    # Simulator should respond with @ iff we send it a ?
    s.flushInput()
    s.flushOutput()
    s.write(b"P?X?")
    assert s.read(1) == b"@", "Simulator signals CP mode"
    assert s.read(1) == b"@", "Simulator signals CP mode twice"

    # FIXME: Dummy simulator responds with #CMDER to every message
    s.write(b"#CMDSY\r\n")
    m = s.readline()
    assert m == b"#CMDOK\r\n", "CP simulator responds like a dummy FIXME"

    s.write(b"#CMDSY\r\n")
    m = s.readline()
    assert m == b"#CMDOK\r\n", "CP simulator responds like a dummy again FIXME"

    # Simulator should still respond with @ iff we send it a ?
    s.write(b"P?")
    assert s.read(1) == b"@", "Simulator still signals CP mode"


def test_cp_config_rw(cp_sim, kill_sims):
    del kill_sims

    p = GenericHXProtocol(cp_sim.tty)
    p.cmd_mode()

    random_bytes = bytes(getrandbits(8) for _ in range(0xff))
    p.write_config_memory(0x1000, random_bytes)
    assert p.read_config_memory(0x1000, len(random_bytes)) == random_bytes, "largest transfer round-trips"
    assert p.read_config_memory(0x1000, 1) == random_bytes[:1], "smallest transfer"

    # The length field is one byte, so larger transfers cannot be expressed on the wire
    for length in 0x100, 0x110:
        with pytest.raises(ProtocolError, match="length"):
            p.write_config_memory(0x2000, bytes(length))
        with pytest.raises(ProtocolError, match="length"):
            p.read_config_memory(0x2000, length)
    with pytest.raises(ProtocolError, match="length"):
        p.write_config_memory(0x2000, b"")
    assert cp_sim.c[0x2000:0x2110] == b"\xff" * 0x110, "rejected transfers never reach the device"
    assert p.read_config_memory(0x1000, 4) == random_bytes[:4], "connection is still in sync"


def test_cp_checksum_verification(cp_sim, kill_sims):
    del kill_sims

    p = GenericHXProtocol(cp_sim.tty)
    assert p.read_config_memory(0x0100, 6) == b"AM057N", "Read works without fault"

    # Each checksummed reply type must be rejected when its checksum is broken
    cp_sim.faults["#CEPDT"] = "checksum"
    with pytest.raises(ProtocolError, match="[Cc]hecksum"):
        p.read_config_memory(0x0100, 6)
    del cp_sim.faults["#CEPDT"]
    p.sync()
    assert p.read_config_memory(0x0100, 6) == b"AM057N", "Read recovers after fault"

    cp_sim.faults["#CEPSD"] = "checksum"
    with pytest.raises(ProtocolError, match="[Cc]hecksum"):
        p.wait_for_ready()
    del cp_sim.faults["#CEPSD"]
    p.sync()
    p.wait_for_ready()

    cp_sim.faults["#CVRDQ"] = "checksum"
    with pytest.raises(ProtocolError, match="[Cc]hecksum"):
        p.get_firmware_version()
    del cp_sim.faults["#CVRDQ"]
    p.sync()
    assert p.get_firmware_version() == "23.42", "Firmware version recovers after fault"


@pytest.mark.parametrize("fault", ["address", "length", "truncate"])
def test_cp_read_reply_verification(cp_sim, kill_sims, fault):
    del kill_sims

    p = GenericHXProtocol(cp_sim.tty)
    assert p.read_config_memory(0x0100, 6) == b"AM057N", "Read works without fault"

    # A data reply that does not match the request must be rejected,
    # even though its checksum is valid
    cp_sim.faults["#CEPDT"] = fault
    with pytest.raises(ProtocolError, match="Unexpected"):
        p.read_config_memory(0x0100, 6)
    del cp_sim.faults["#CEPDT"]
    p.sync()
    assert p.read_config_memory(0x0100, 6) == b"AM057N", "Read recovers after fault"


def test_import_without_pty():
    # On platforms without pty support (Windows), hxtool must still import
    code = "import sys; sys.modules['pty'] = None; import hxtool; print('imported')"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "imported" in result.stdout


def test_simulator_without_pty(monkeypatch, caplog, kill_sims):
    del kill_sims
    monkeypatch.setitem(sys.modules, "pty", None)  # makes importing pty fail

    instances_before = len(simulator.HXSimulator.instances)
    with pytest.raises(simulator.SimulatorError, match="not supported"):
        simulator.HXSimulator(config.HX870Config, mode="CP")
    assert len(simulator.HXSimulator.instances) == instances_before, "Failed simulator is not registered"

    # Asking for simulators is reported, but does not get in the way of real devices
    monkeypatch.setattr(device, "enumerate_devices", lambda *args: [device.Candidate(device.HX870Sim, "real", True)])
    monkeypatch.setattr(device.HX870Sim, "__init__", lambda self, tty, identified=False: setattr(self, "tty", tty))
    devices = device.enumerate(add_simulator=True)
    assert [d.tty for d in devices] == ["real"]
    assert "not supported" in caplog.text
