import logging
import pytest

from hxtool import config, protocol, simulator
from hxtool.protocol import GenericHXProtocol, GX1400Protocol

MODELS = [config.HX870Config, config.HX890Config, config.GX1400Config]

# What the writer leaves alone, per model: (start, end) byte ranges, end exclusive
FLASH_ID_RANGE = {
    config.HX870Config: (0x0100, 0x010f),
    config.HX890Config: (0x0100, 0x010f),
    config.GX1400Config: (0x0098, 0x009f),
}
OTHER_PROTECTED = {
    config.HX870Config: [(0x000f, 0x0010), (0x0110, 0x0120)],
    config.HX890Config: [(0x000f, 0x0010), (0x0110, 0x0120)],
    # Firmware version, unknown block, last turned off fix, serial and production date, tail padding
    config.GX1400Config: [(0x001d, 0x0020), (0x00a0, 0x00d0), (0x0110, 0x0120), (0x1fa0, 0x2000)],
}


def magic_ranges(model):
    return [(0x0000, 0x0002), (model.CONFIG_SIZE - 2, model.CONFIG_SIZE)]


def in_ranges(offset, ranges):
    return any(start <= offset < end for start, end in ranges)


def factory_image(model) -> bytearray:
    """A plausible device memory: magic at both ends, flash ID, US region"""
    data = bytearray(b"\xff" * model.CONFIG_SIZE)
    data[0:2] = model.CONFIG_MAGIC.to_bytes(2, "big")
    data[-2:] = model.CONFIG_MAGIC.to_bytes(2, "big")
    fid = model.FLASH_ID[0].encode("ascii")
    data[model.FLASH_ID_OFFSET:model.FLASH_ID_OFFSET + len(fid)] = fid
    data[model.REGION_CODE_OFFSET] = model.REGION_CODE_US
    return data


def changed_image(model) -> bytearray:
    """Every byte differs from the factory image, except magic and region"""
    data = bytearray((0x100 - (i & 0xff)) & 0xff if (i & 0xff) != 0 else 0x01 for i in range(model.CONFIG_SIZE))
    data[0:2] = model.CONFIG_MAGIC.to_bytes(2, "big")
    data[-2:] = model.CONFIG_MAGIC.to_bytes(2, "big")
    data[model.REGION_CODE_OFFSET] = model.REGION_CODE_US
    factory = factory_image(model)
    for i in range(model.CONFIG_SIZE):
        if data[i] == factory[i] and not in_ranges(i, magic_ranges(model)) and i != model.REGION_CODE_OFFSET:
            data[i] ^= 0x55
    return data


@pytest.fixture(name="sim")
def fixture_simulator(request):
    model = request.param
    s = simulator.HXSimulator(model, mode="CP", config=factory_image(model), loop_delay=0.0005)
    s.start()
    yield s
    s.stop()
    s.join(timeout=1)


def connect(sim) -> config.GenericHXConfig:
    proto = GX1400Protocol if sim.type is config.GX1400Config else GenericHXProtocol
    return sim.type(proto(sim.tty))


def assert_written_except(sim, image, untouched, factory):
    """Device memory equals the image outside `untouched`, and the factory state inside"""
    for i in range(sim.type.CONFIG_SIZE):
        expected = factory[i] if in_ranges(i, untouched) else image[i]
        assert sim.c[i] == expected, f"byte 0x{i:04x}"


@pytest.mark.parametrize("sim", MODELS, indirect=True)
@pytest.mark.parametrize("force, write_flash_id", [(False, False), (False, True), (True, False), (True, True)])
def test_config_write_overrides(sim, force, write_flash_id):
    """Without overrides the writer leaves the magic, the flash ID and the protected
    ranges alone; write_flash_id releases the flash ID, force the protected ranges"""
    model, factory, image = sim.type, factory_image(sim.type), changed_image(sim.type)
    connect(sim).config_write(image, force=force, write_flash_id=write_flash_id)
    untouched = magic_ranges(model)
    if not write_flash_id:
        untouched.append(FLASH_ID_RANGE[model])
    if not force:
        untouched += OTHER_PROTECTED[model]
    assert_written_except(sim, image, untouched, factory)


@pytest.mark.parametrize("sim", MODELS, indirect=True)
def test_config_write_checks(sim, caplog):
    caplog.set_level(logging.WARNING)
    model, factory = sim.type, factory_image(sim.type)
    c = connect(sim)

    with pytest.raises(protocol.ProtocolError, match="size"):
        c.config_write(factory + b"\x00")
    with pytest.raises(protocol.ProtocolError, match="size"):
        c.config_write(factory + b"\x00", force=True, write_flash_id=True)

    wrong_magic = bytearray(factory)
    wrong_magic[0] ^= 0x01
    with pytest.raises(protocol.ProtocolError, match="magic"):
        c.config_write(wrong_magic)
    wrong_region = bytearray(factory)
    wrong_region[model.REGION_CODE_OFFSET] = 0x01 if model.REGION_CODE_US != 0x01 else 0x02
    with pytest.raises(protocol.ProtocolError, match="[Rr]egion"):
        c.config_write(wrong_region)
    assert bytes(sim.c) == bytes(factory), "rejected images change nothing"

    wrong_magic[0x0020] ^= 0xff
    c.config_write(wrong_magic, force=True)
    assert "magic" in caplog.text.lower() and "flashing anyway" in caplog.text.lower()
    assert sim.c[0x0020] == wrong_magic[0x0020], "written despite the magic mismatch"
    assert sim.c[0:2] == factory[0:2], "the device's magic is never written"

    caplog.clear()
    c.config_write(wrong_region, force=True)
    assert "region" in caplog.text.lower() and "flashing anyway" in caplog.text.lower()
    assert sim.c[model.REGION_CODE_OFFSET] == wrong_region[model.REGION_CODE_OFFSET]


@pytest.mark.parametrize("sim", MODELS, indirect=True)
def test_identity_reads(sim):
    c = connect(sim)
    assert c.flash_id() == sim.type.FLASH_ID[0]
    assert c.check_flash_id()
    assert c.read_region()[1] == sim.type.REGION_CODE_US
    assert c.read_region()[0] in sim.type.REGION_CODES.values()
    sim.c[sim.type.FLASH_ID_OFFSET] ^= 0x01
    assert not c.check_flash_id()
