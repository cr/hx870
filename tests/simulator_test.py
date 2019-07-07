# -*- coding: utf-8 -*-

import pytest
from random import getrandbits
from serial import Serial
from sys import platform
from threading import enumerate
from time import sleep

from hxtool import simulator
from hxtool.protocol import GenericHXProtocol

# The simulator doesn't work on Windows, so skip test if running on Windows
if platform.startswith("win"):
    pytest.skip("Skipping simulator tests on Windows", allow_module_level=True)


@pytest.fixture(name="cp_sim")
def fixture_cp_simulator():
    s = simulator.HXSimulator(mode="CP", loop_delay=0.0005)
    s.start()
    yield s
    s.stop()
    s.join(timeout=1)


@pytest.fixture(name="nmea_sim")
def fixture_nmea_simulator():
    s = simulator.HXSimulator(mode="NMEA", nmea_delay=0.2, loop_delay=0.01)
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

    sim_a = simulator.HXSimulator(mode="CP", loop_delay=0.001)
    sim_b = simulator.HXSimulator(mode="CP", loop_delay=0.001)
    sim_c = simulator.HXSimulator(mode="CP", loop_delay=0.001)
    sim_n = simulator.HXSimulator(mode="NMEA", nmea_delay=0.03, loop_delay=0.01)

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

    ser_a.write(b"#CMDSY\r\n")
    assert ser_a.out_waiting == 8
    assert ser_a.readline() == b""

    # Dump NMEA sentences from sim_n which should have sent several by now
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

    # Simulator should respond with P iff we send it a P
    s.flushInput()
    s.flushOutput()
    s.write(b"XP?P")
    assert s.read(1) == b"P", "Simulator signals NMEA mode"
    assert s.read(1) == b"P", "Simulator signals NMEA mode twice"

    # Simulator should be sending NMEA dummy messages
    m = s.readline()
    assert m.startswith(b"$GPLL") and m.endswith(b"\r\n"), "Simulator sends NMEA message"
    m = s.readline()
    assert m.startswith(b"$GPLL") and m.endswith(b"\r\n"), "Simulator keeps sending NMEA messages"
    m = s.readline()
    assert m.startswith(b"$GPLL") and m.endswith(b"\r\n"), "Simulator keeps sending NMEA messages still"

    # Simulator should still respond with P iff we send it a P
    s.write(b"P?")
    assert s.read(1) == b"P", "Simulator still signals NMEA mode"


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


@pytest.mark.skip
def test_cp_config_rw(cp_sim, kill_sims):
    del kill_sims

    p = GenericHXProtocol(cp_sim.tty)
    p.cmd_mode()

    random_bytes = bytearray(getrandbits(8) for _ in range(0x110))
    p.write_config_memory(0x1000, random_bytes)
    m = p.read_config_memory(0x1000, len(random_bytes))
    assert m == random_bytes
