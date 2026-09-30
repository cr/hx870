import pytest

from hxtool import config, protocol, simulator


@pytest.fixture(name="cp_870_sim")
def fixture_cp_870_simulator():
    memory = bytearray(b"\xff" * 0x8000)
    memory[0x00a2] = 0x00  # ATIS disabled
    memory[0x00b0:0x00b6] = bytes.fromhex("872345900003")  # MMSI
    memory[0x00b6:0x00bc] = bytes.fromhex("972345900005")  # ATIS
    memory[0x010f] = 0x04  # region
    memory[0x4300:0x4310] = bytes.fromhex("9740019080544157174E001235956745")  # waypoint
    memory[0x4310:0x4316] = "WPT001".encode("ascii")
    memory[0x431f] = 0x01  # waypoint id
    memory[0x4320:0x4330] = bytes.fromhex("FFFFFFFFFF2707433353010917166757")  # waypoint
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
    memory[0xd700:0xd710] = bytes.fromhex("FFFFFFFFF0404135384E007402668257")  # waypoint
    memory[0xd710:0xd713] = "foo".encode("ascii")  # waypoint name
    memory[0xd71f] = 0xf0  # waypoint id
    s = simulator.HXSimulator(config.HX890Config, mode="CP", config=memory)
    s.start()
    yield s
    s.stop()
    s.join(timeout=1)


@pytest.fixture(name="sim_870_config")
def fixture_config_simulator(cp_870_sim):
    yield config.HX870Config(protocol.GenericHXProtocol(cp_870_sim.tty))


@pytest.fixture(name="sim_890_config")
def fixture_config_890_simulator(cp_890_sim):
    yield config.HX890Config(protocol.GenericHXProtocol(cp_890_sim.tty))


def test_hx870_mmsi(sim_870_config):
    assert sim_870_config.read_mmsi() == ("872345900", 3), "MMSI offset and update counter"

    sim_870_config.write_mmsi(mmsi="318765432")
    assert sim_870_config.read_mmsi() == ("318765432", 3), "MMSI write leaves the update counter alone"
    raw = sim_870_config.p.read_config_memory(sim_870_config.MMSI_OFFSET, 5)
    assert raw == bytes.fromhex("3187654320"), "MMSI is stored with a zero as 10th digit"

    sim_870_config.write_mmsi(mmsi="111222333", counter=7)
    assert sim_870_config.read_mmsi() == ("111222333", 7), "explicit update counter"

    sim_870_config.write_mmsi(counter=9)
    assert sim_870_config.read_mmsi() == ("FFFFFFFFF", 9), "reset with explicit update counter"

    sim_870_config.write_mmsi(mmsi="111222333", counter=7)
    sim_870_config.write_mmsi()
    assert sim_870_config.read_mmsi() == ("FFFFFFFFF", 0), "reset restores the factory state"

    for bad_mmsi in ("12345678",  # too short
                     "11111f111",  # not numeric
                     "",  # empty
                     "\u0669" * 9,  # digits, but not ASCII
                     "1112223330",  # the 10th digit is protocol padding, not for the caller to provide
                     "1112223339"):
        with pytest.raises(protocol.ProtocolError):
            sim_870_config.write_mmsi(mmsi=bad_mmsi)
    for bad_counter in (-1, 256, "02", 1.5, True):
        with pytest.raises(protocol.ProtocolError):
            sim_870_config.write_mmsi(mmsi="123456789", counter=bad_counter)
    assert sim_870_config.read_mmsi() == ("FFFFFFFFF", 0), "rejected writes change nothing"


def test_hx870_atis(sim_870_config):
    assert sim_870_config.read_atis() == ("9723459000", 5), "ATIS offset and update counter"

    sim_870_config.write_atis(atis="9318765432")
    assert sim_870_config.read_atis() == ("9318765432", 5), "ATIS write leaves the update counter alone"

    sim_870_config.write_atis(atis="9876543210", counter=2)
    assert sim_870_config.read_atis() == ("9876543210", 2), "explicit update counter"

    # Ten digits are taken as they are, even without the leading 9
    sim_870_config.write_atis(atis="2987654321")
    assert sim_870_config.read_atis() == ("2987654321", 2), "ATIS content is trusted"

    sim_870_config.write_atis()
    assert sim_870_config.read_atis() == ("FFFFFFFFFF", 0), "reset restores the factory state"

    for bad_atis in ("987654321",  # too short
                     "91111f1111",  # not numeric
                     "",  # empty
                     "\u0669" * 10):  # digits, but not ASCII
        with pytest.raises(protocol.ProtocolError):
            sim_870_config.write_atis(atis=bad_atis)
    for bad_counter in (-1, 256, "02"):
        with pytest.raises(protocol.ProtocolError):
            sim_870_config.write_atis(atis="9876543210", counter=bad_counter)
    assert sim_870_config.read_atis() == ("FFFFFFFFFF", 0), "rejected writes change nothing"

    atis_enabled, atis_config = sim_870_config.read_atis_enabled()
    assert not atis_enabled, "ATIS enabled offset"
    assert atis_config == 0, "ATIS enabled"

    sim_870_config.write_atis_enabled(True)
    assert sim_870_config.read_atis_enabled()[0], "ATIS enabled write/read"

    with pytest.raises(protocol.ProtocolError):
        sim_870_config.write_atis_enabled(999)


def test_hx870_region(sim_870_config):
    region, code = sim_870_config.read_region()
    assert region == "SWEDEN", "region code offset"
    assert code == 4, "region code"

    with pytest.raises(protocol.ProtocolError):
        data = bytearray(b"\xff" * 0x8000)
        sim_870_config.config_write(data)  # region mismatch

    sim_870_config.write_region(0xff)
    assert sim_870_config.read_region()[1] == 0xff, "region code write/read"

    sim_870_config.write_region(73)
    region, code = sim_870_config.read_region()
    assert region == "", "unknown region"
    assert code == 73, "region code"
    sim_870_config.write_region(0xff)

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
