import pytest
from serial import Serial
from sys import platform

from hxtool import simulator

# The simulator doesn't work on Windows, so skip test if running on Windows
if platform.startswith("win"):
    pytest.skip("Skipping simulator tests on Windows", allow_module_level=True)


@pytest.fixture(name="cp_sim")
def fixture_cp_simulator():
    s = simulator.HXSimulator(mode="CP", loop_delay=0.01)
    yield s
    s.stop()
    s.join(timeout=1)


@pytest.fixture(name="nmea_sim")
def fixture_nmea_simulator():
    s = simulator.HXSimulator(mode="NMEA", loop_delay=0.01, nmea_delay=0.2)
    yield s
    s.stop()
    s.join(timeout=1)


def test_nmea_simulator(nmea_sim):
    nmea_sim.start()
    s = Serial(nmea_sim.tty, timeout=1.5)

    # Simulator should respond with P iff we send it a P
    s.flushInput()
    s.flushOutput()
    s.write(b"FOOP?IGNOREP")
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
    s.write(b"FOOP?IGNORE")
    assert s.read(1) == b"P", "Simulator still signals NMEA mode"


def test_cp_simulator(cp_sim):
    cp_sim.start()
    s = Serial(cp_sim.tty, timeout=1.5)

    # Simulator should respond with @ iff we send it a ?
    s.flushInput()
    s.flushOutput()
    s.write(b"FOOP?IGNORE?")
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
    s.write(b"FOOP?IGNORE")
    assert s.read(1) == b"@", "Simulator still signals CP mode"
