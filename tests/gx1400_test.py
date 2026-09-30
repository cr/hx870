# -*- coding: utf-8 -*-

from binascii import unhexlify
import logging
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

    with pytest.raises(ProtocolError):
        config.read_waypoints()


def test_gx1400_region(gx1400_sim):
    config = GX1400(gx1400_sim.tty).config

    config.write_region(73)
    region, code = config.read_region()
    assert region == "", "unknown region"
    assert code == 73, "region code"

    with pytest.raises(ProtocolError):
        data = bytearray(b"\xff" * 0x2000)
        data[0x009f] = 0x00
        config.config_write(data)  # region mismatch


def test_gx1400_config_write(gx1400_sim, caplog):
    caplog.set_level(logging.INFO)
    config = GX1400(gx1400_sim.tty).config

    data = bytearray(config.config_read())
    data[0x0060:0x0065] = unhexlify("9987064120")  # MMSI
    config.config_write(data, progress=True)

    assert config.read_mmsi()[0] == "998706412"

    assert "0 / 8192 bytes (0%)" in caplog.text
    assert "2048 / 8192 bytes (25%)" in caplog.text
    assert "8192 / 8192 bytes (100%)" in caplog.text


def test_gx1400_counters(gx1400_sim):
    # Reverse engineering of the vendor tooling showed that the byte after each
    # code counts that code's updates: programming a different code increments
    # it, clearing the code does not, but increments the clear counters at
    # 0x0096 (MMSI) and 0x0097 (ATIS) instead. The radios themselves ignore
    # the counters. hxtool leaves the update counter alone unless told
    # otherwise, and a reset restores the factory state.
    config = GX1400(gx1400_sim.tty).config
    clear_counters = config.p.read_config_memory(0x0096, 2)

    config.write_mmsi(mmsi="876543210")
    assert config.read_mmsi() == ("876543210", 1), "update counter is left alone"
    config.write_mmsi(mmsi="888777666", counter=6)
    assert config.read_mmsi() == ("888777666", 6), "explicit update counter"
    config.write_atis(atis="9998887770", counter=7)
    assert config.read_atis() == ("9998887770", 7), "explicit update counter"

    config.write_mmsi()
    config.write_atis()
    assert config.read_mmsi() == ("FFFFFFFFF", 0), "reset restores the factory state"
    assert config.read_atis() == ("FFFFFFFFFF", 0), "reset restores the factory state"
    assert config.p.read_config_memory(0x0096, 2) == clear_counters, "clear counters are not touched"


def test_hxtool_devices(capsys):
    args = [
        "--simulator",
        "devices",
    ]
    ret = main(args)
    assert ret == 0, "hxtool --simulator devices returns 0"

    outerr = capsys.readouterr()
    out = outerr.out.strip("\n").split("\n")
    gx1400 = [device for device in out if "GX1400" in device]
    assert len(gx1400) == 1, "One GX1400 simulator detected"

    device = gx1400[0].split("\t")
    assert GX1400.brand in device
    assert GX1400.model in device
    assert "CP mode" in device
