# -*- coding: utf-8 -*-

from binascii import unhexlify
import pytest
from sys import platform

from hxtool import config, protocol, simulator

# The simulator doesn't work on Windows, so skip test if running on Windows
if platform.startswith("win"):
    pytest.skip("Skipping simulator tests on Windows", allow_module_level=True)


@pytest.fixture(name="cp_870_sim")
def fixture_cp_870_simulator():
    memory = bytearray(b"\xff" * 0x8000)
    memory[0x00a2] = 0x00  # ATIS disabled
    memory[0x00b0:0x00b6] = unhexlify("872345900003")  # MMSI
    memory[0x00b6:0x00bc] = unhexlify("972345900005")  # ATIS
    memory[0x010f] = 0x04  # region
    memory[0x4300:0x4310] = unhexlify("9740019080544157174E001235956745")  # waypoint
    memory[0x4310:0x4316] = "WPT001".encode("ascii")
    memory[0x431f] = 0x01  # waypoint id
    memory[0x4320:0x4330] = unhexlify("FFFFFFFFFF2707433353010917166757")  # waypoint
    memory[0x4330:0x433f] = "long waypoint 2".encode("ascii")
    memory[0x433f] = 0x02  # waypoint id
    s = simulator.HXSimulator(config.HX870Config, mode="CP", config=memory)
    s.start()
    yield s
    s.stop()
    s.join(timeout=1)


@pytest.fixture(name="cp_890_sim")
def fixture_cp_890_simulator():
    memory = bytearray(b"\xff" * 0x10000)
    memory[0xd700:0xd710] = unhexlify("FFFFFFFFF0404135384E007402668257")  # waypoint
    memory[0xd710:0xd713] = "foo".encode("ascii")  # waypoint name
    memory[0xd71f] = 0xf0  # waypoint id
    s = simulator.HXSimulator(config.HX890Config, mode="CP", config=memory)
    s.start()
    yield s
    s.stop()
    s.join(timeout=1)


@pytest.fixture(name="kill_sims")
def kill_simulator_threads_fixture():
    yield None
    simulator.HXSimulator.stop_instances()
    simulator.HXSimulator.join_instances()


@pytest.fixture(name="sim_870_config")
def fixture_config_simulator(cp_870_sim):
    yield config.HX870Config(protocol.GenericHXProtocol(cp_870_sim.tty))


@pytest.fixture(name="sim_890_config")
def fixture_config_890_simulator(cp_890_sim):
    yield config.HX890Config(protocol.GenericHXProtocol(cp_890_sim.tty))


# @pytest.mark.skip
# def test_cp_870_config_rw(cp_870_sim, kill_sims):
#     del kill_sims

#     p = GenericHXProtocol(cp_870_sim.tty)
#     p.cmd_mode()

#     random_bytes = bytearray(getrandbits(8) for _ in range(0x110))
#     p.write_config_memory(0x1000, random_bytes)
#     m = p.read_config_memory(0x1000, len(random_bytes))
#     assert m == random_bytes


def test_hx870_mmsi(sim_870_config):
    mmsi, status = sim_870_config.read_mmsi()
    assert mmsi == "872345900", "MMSI offset"
    assert status == "03", "MMSI save counter"

    sim_870_config.write_mmsi(mmsi="318765432", status="02")
    mmsi, status = sim_870_config.read_mmsi()
    assert mmsi == "318765432", "MMSI write/read"
    assert status == "02", "MMSI save counter write/read"

    sim_870_config.write_mmsi()
    mmsi, status = sim_870_config.read_mmsi()
    assert mmsi == "FFFFFFFFF", "MMSI reset"
    assert status == "00", "MMSI reset save counter"

    sim_870_config.write_mmsi(mmsi="1112223330")
    mmsi, status = sim_870_config.read_mmsi()
    assert mmsi == "111222333", "10th digit is accepted but dropped"
    assert status not in ["00", "FF"], "save counter is set automatically"

    with pytest.raises(protocol.ProtocolError):
        sim_870_config.write_mmsi(mmsi="12345678")  # too short
    with pytest.raises(protocol.ProtocolError):
        sim_870_config.write_mmsi(mmsi="11111f111")  # not numeric
    with pytest.raises(protocol.ProtocolError):
        sim_870_config.write_mmsi(mmsi="123456789", status="gh")  # invalid save counter


def test_hx870_atis(sim_870_config):
    atis, status = sim_870_config.read_atis()
    assert atis == "9723459000", "ATIS offset"
    assert status == "05", "ATIS save counter"

    sim_870_config.write_atis(atis="9318765432", status="02")
    atis, status = sim_870_config.read_atis()
    assert atis == "9318765432", "ATIS write/read"
    assert status == "02", "ATIS save counter write/read"

    sim_870_config.write_atis()
    atis, status = sim_870_config.read_atis()
    assert atis == "FFFFFFFFFF", "ATIS reset"
    assert status == "00", "ATIS reset save counter"

    sim_870_config.write_atis(atis="9876543210")
    atis, status = sim_870_config.read_atis()
    assert status not in ["00", "FF"], "save counter is set automatically"

    with pytest.raises(protocol.ProtocolError):
        sim_870_config.write_atis(atis="987654321")  # too short
    with pytest.raises(protocol.ProtocolError):
        sim_870_config.write_atis(atis="91111f1111")  # not numeric
    with pytest.raises(protocol.ProtocolError):
        sim_870_config.write_atis(atis="2987654321")  # doesn't start with 9
    with pytest.raises(protocol.ProtocolError):
        sim_870_config.write_atis(atis="9876543210", status="gh")  # invalid save counter

    atis_config = sim_870_config.read_atis_enabled()
    assert atis_config == 0, "ATIS disabled"

    sim_870_config.write_atis_enabled(True)
    assert sim_870_config.read_atis_enabled() == 1, "ATIS enabled write/read"

    with pytest.raises(protocol.ProtocolError):
        sim_870_config.write_atis_enabled(999)


def test_hx870_region(sim_870_config):
    code = sim_870_config.read_region()
    assert code == 4, "region code"

    with pytest.raises(protocol.ProtocolError):
        data = bytearray(b"\xff" * 0x8000)
        sim_870_config.config_write(data)  # region mismatch

    sim_870_config.write_region(0xff)
    assert sim_870_config.read_region() == 0xff, "region code write/read"

    with pytest.raises(protocol.ProtocolError):
        data = bytearray(b"\xff" * 0x8000)
        data[0x010f] = 0x01
        sim_870_config.config_write(data)  # region mismatch

    with pytest.raises(protocol.ProtocolError):
        sim_870_config.write_region(0x100)  # too large


def test_hx870_waypoints(sim_870_config):
    waypoints = sim_870_config.read_waypoints()

    assert waypoints[0]["id"] == 1, "wpt 1 id"
    assert waypoints[0]["name"] == "WPT001", "wpt 1 name"
    assert waypoints[0]["mmsi"] == "974001908", "wpt 1 mmsi"
    assert waypoints[0]["latitude"] == "54N41.5717", "wpt 1 lat"
    assert waypoints[0]["longitude"] == "12E35.9567", "wpt 1 lon"

    assert waypoints[1]["id"] == 2, "wpt 2 id"
    assert waypoints[1]["name"] == "long waypoint 2", "wpt 2 name"
    assert waypoints[1]["mmsi"] is None, "wpt 2 mmsi"
    assert waypoints[1]["latitude"] == "27S07.4333", "wpt 2 lat"
    assert waypoints[1]["longitude"] == "109W17.1667", "wpt 2 lon"


def test_hx890_waypoints(sim_890_config):
    waypoints = sim_890_config.read_waypoints()

    assert len(waypoints) == 1
    assert waypoints[0]["id"] == 240, "wpt 1 id"
    assert waypoints[0]["name"] == "foo", "wpt 1 name"
    assert waypoints[0]["mmsi"] is None, "wpt 1 mmsi"
    assert waypoints[0]["latitude"] == "40N41.3538", "wpt 1 lat"
    assert waypoints[0]["longitude"] == "74W02.6682", "wpt 1 lon"


@pytest.mark.slow
def test_hx870_config(sim_870_config):
    data = bytearray(sim_870_config.config_read())
    data[0x00b0:0x00b5] = unhexlify("9793485160")  # MMSI
    data[0x010f] = 0xff  # region mismatch (will be ignored)
    sim_870_config.config_write(data, check_region=False)
    assert sim_870_config.read_mmsi()[0] == "979348516"
    assert sim_870_config.read_region() == 0xff

    with pytest.raises(protocol.ProtocolError):
        sim_870_config.config_write(b"\xff" * 0x8001)  # wrong data size
    with pytest.raises(protocol.ProtocolError):
        data[0x0000] = 0x56  # wrong magic
        sim_870_config.config_write(data)
