# -*- coding: utf-8 -*-

from binascii import unhexlify
import os
import pytest
from sys import platform

from hxtool.config import GX1400Config
from hxtool.device import GX1400
from hxtool.main import main
from hxtool.protocol import ProtocolError
from hxtool.simulator import HXSimulator

# The simulator may not work on Windows, so skip test if running on Windows
if platform.startswith("win"):
    pytest.skip("Skipping simulator tests on Windows", allow_module_level=True)


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


def test_blank_device(capsys, blank_sim):
    device = GX1400(blank_sim.tty)
    outerr = capsys.readouterr()
    assert "does not behave or look like GX1400" in outerr.err


def test_gx1400_device(gx1400_sim):
    device = GX1400(gx1400_sim.tty)

    assert device.comm.hx_hardware
    assert device.comm.cp_mode
    assert device.comm.get_firmware_version() == "0.99"
    assert device.handle == "GX1400GPS-SIM"


def test_gx1400_config_offsets(gx1400_sim):
    config = GX1400(gx1400_sim.tty).config

    mmsi, mmsi_status = config.read_mmsi()
    atis, atis_status = config.read_atis()
    assert mmsi == "972001400", "MMSI"
    assert mmsi_status == "01", "MMSI save counter"
    assert atis == "9972001400", "ATIS"
    assert atis_status == "06", "ATIS save counter"

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


def test_gx1400_config_write(gx1400_sim, capsys):
    config = GX1400(gx1400_sim.tty).config

    data = bytearray(config.config_read())
    data[0x0060:0x0065] = unhexlify("9987064120")  # MMSI
    config.config_write(data, progress=True)

    assert config.read_mmsi()[0] == "998706412"

    outerr = capsys.readouterr()
    assert "0 / 8192 bytes (0%)" in outerr.err
    assert "2048 / 8192 bytes (25%)" in outerr.err
    assert "8192 / 8192 bytes (100%)" in outerr.err


@pytest.mark.xfail
def test_gx1400_save_counters(gx1400_sim):
    config = GX1400(gx1400_sim.tty).config

    # The "status" byte counts the number of times the code has been saved
    config.write_mmsi(mmsi="876543210", status=6)
    assert config.read_mmsi()[1] == 6
    config.write_atis(atis="9876543210", status=7)
    assert config.read_atis()[1] == 7

    # Changing the code increments the save counter
    config.write_mmsi(mmsi="888777666")
    config.write_atis(atis="9998887770")
    assert config.read_mmsi()[1] == 7
    assert config.read_atis()[1] == 8

    mmsi_clear_counter = ord(config.p.read_config_memory(0x0096, 1))
    atis_clear_counter = ord(config.p.read_config_memory(0x0097, 1))

    # Clearing the code doesn't change the save counter
    config.write_mmsi(mmsi=None)
    config.write_atis(atis=None)
    assert config.read_mmsi()[1] == 7
    assert config.read_atis()[1] == 8

    # ... but increments the clear counter
    assert ord(config.p.read_config_memory(0x0096, 1)) == mmsi_clear_counter + 1
    assert ord(config.p.read_config_memory(0x0097, 1)) == atis_clear_counter + 1


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
