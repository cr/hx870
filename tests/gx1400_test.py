# -*- coding: utf-8 -*-

from binascii import unhexlify
import pytest

from hxtool.config import GX1400Config
from hxtool.device import GX1400
from hxtool.main import main
from hxtool.protocol import ProtocolError
from hxtool.simulator import HXSimulator


@pytest.fixture(name="blank_sim")
def fixture_blank_simulator():
    blank = bytearray(b"\xff" * 0x2000)
    s = HXSimulator(GX1400Config, mode="CP", config=blank)
    s.start()
    yield s
    s.stop()
    s.join(timeout=1)


@pytest.fixture(name="gx1400_sim")
def fixture_gx1400_simulator():
    memory = bytearray(b"\xff" * 0x2000)
    memory[0x001d:0x001f] = unhexlify("0099")  # firmware version
    memory[0x0052] = 0x20  # ATIS disabled
    memory[0x0060:0x0066] = unhexlify("972001400001")  # MMSI
    memory[0x0066:0x006c] = unhexlify("997200140006")  # ATIS
    memory[0x0096:0x0098] = unhexlify("0005")  # code clear counters
    memory[0x0098:0x009e] = "AM065N".encode("ascii")  # flash ID
    memory[0x009f] = 0x01  # region
    memory[0x00d0:0x00dd] = "GX1400GPS-SIM".encode("ascii")  # model variant
    s = HXSimulator(GX1400Config, mode="CP", config=memory)
    s.start()
    yield s
    s.stop()
    s.join(timeout=1)


def test_blank_device(caplog, blank_sim):
    device = GX1400(blank_sim.tty)
    assert device.config is None
    assert "does not behave or look like GX1400" in caplog.text


def test_gx1400_device(gx1400_sim):
    device = GX1400(gx1400_sim.tty)

    assert device.comm.hx_hardware
    assert device.comm.cp_mode
    assert device.config.firmware_version() == "0.99"
    assert device.config.variant() == "GX1400GPS-SIM"
    assert device.handle == "GX1400GPS-SIM"
    assert device.config.flash_id() == "AM065N"


def test_gx1400_config_offsets(gx1400_sim):
    config = GX1400(gx1400_sim.tty).config

    assert config.read_mmsi() == ("972001400", 1), "MMSI and update counter"
    assert config.read_atis() == ("9972001400", 6), "ATIS and update counter"

    atis_enabled, atis_config = config.read_atis_enabled()
    assert not atis_enabled, "ATIS enabled"
    assert atis_config == 0x20, "ATIS enabled code"

    region, region_code = config.read_region()
    assert region == "INTL", "region short name"
    assert region_code == 0x01, "region code"
    config.write_region(73)
    assert config.read_region() == ("", 73), "unknown region"

    with pytest.raises(ProtocolError):
        config.read_waypoints()
    assert main(["--simulator", "-m", "GX1400", "gpslog"]) != 0, "no GPS log either"


def test_gx1400_counters(gx1400_sim):
    # Reverse engineering of the vendor tooling showed that the byte after each
    # code counts that code's updates: programming a different code increments
    # it, clearing the code does not, but increments the clear counters at
    # 0x0096 (MMSI) and 0x0097 (ATIS) instead. The radios themselves ignore
    # the counters. hxtool leaves the update counter alone unless told
    # otherwise, and a reset restores the factory state.
    # The counter rule itself is tested on the HX870 in config_test.py.
    config = GX1400(gx1400_sim.tty).config
    clear_counters = config.p.read_config_memory(0x0096, 2)
    config.write_mmsi(mmsi="888777666", counter=6)
    config.write_mmsi()
    config.write_atis()
    assert config.p.read_config_memory(0x0096, 2) == clear_counters, "clear counters are not touched"
