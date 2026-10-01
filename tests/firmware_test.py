import logging
import pytest
from time import sleep

from hxtool import config, device
from hxtool.main import main
from hxtool.protocol import FirmwareProtocol, GenericHXProtocol, ProtocolError
from hxtool.simulator import HXSimulator

# All of these drive the simulator: the conftest `no_real_serial_ports` fixture hides every
# real port, so nothing here (a firmware write included) can reach a connected radio.

AREA = (0xf40000, 0xf40000 + 0x200)
GOOD_IMAGE = b"  02.04    " + b"AM057N" + bytes(0x1f8 - 17)  # a little short of the area, like a real one


def firmware_of(sim, address_range=AREA):
    return FirmwareProtocol(GenericHXProtocol(sim.tty), config.HX870Config.FLASH_ID, address_range, 0x80)


@pytest.fixture(name="cp_sim")
def fixture_cp_simulator(kill_sims):
    sim = HXSimulator(config.HX870Config, mode="CP", loop_delay=0.0005)
    sim.start()
    return sim


# The handler: one flash session, ended by the reboot


def test_write_and_read_back_in_one_session(cp_sim):
    fw = firmware_of(cp_sim)
    image = bytes((i * 7) & 0xff for i in range(0x200))

    fw.write_image(image)
    assert fw.active, "flash mode stays on between transfers"
    assert fw.read_image() == image
    assert cp_sim.received["#CMDNR"] == 1, "the handshake is granted once per power-on, and needed once"

    fw.reboot()
    assert not fw.active and cp_sim._flash_mode is False


def test_the_radio_s_own_flash_id_is_offered_first(cp_sim):
    firmware_of(cp_sim).read_image()
    assert cp_sim.received["#CMDNR"] == 1 and cp_sim.received["#CFLID"] == 1


def test_second_handshake_without_a_reboot_is_refused(cp_sim):
    firmware_of(cp_sim).read_image()
    with pytest.raises(ProtocolError, match="did not acknowledge #CMDNR"):
        firmware_of(cp_sim).read_image()


def test_reboot_from_plain_cp_mode(cp_sim):
    # Leaving flash mode is what restarts the radio, so a reboot enters it first if need be
    fw = firmware_of(cp_sim, address_range=None)
    fw.reboot()
    assert cp_sim.received["#CFLMC"] == 2 and not fw.active
    fw.reboot()
    assert cp_sim.received["#CMDNR"] == 2, "the reboot renewed the handshake grant"


def test_read_of_an_erased_flash(cp_sim):
    assert firmware_of(cp_sim).read_image() == b"\xff" * 0x200


def test_write_erases_first(cp_sim):
    fw = firmware_of(cp_sim)
    fw.write_image(b"\xaa" * 0x200)
    fw.write_image(b"\x55" * 0x100 + b"\xff" * 0x100)
    assert fw.read_image() == b"\x55" * 0x100 + b"\xff" * 0x100, "the old content did not bleed through"


def test_shorter_image_is_padded_with_erased_flash(cp_sim):
    # The images the vendor updaters carry end a few bytes short of the area
    fw = firmware_of(cp_sim)
    fw.write_image(b"\x12" * 0x1f0)
    assert fw.read_image() == b"\x12" * 0x1f0 + b"\xff" * 0x10


def test_oversized_image_is_refused_before_flash_mode(cp_sim):
    fw = firmware_of(cp_sim)
    with pytest.raises(ProtocolError, match="at most"):
        fw.write_image(bytes(0x201))
    assert not fw.active and cp_sim.received["#CMDNR"] == 0


def test_unknown_layout_is_refused(cp_sim):
    fw = firmware_of(cp_sim, address_range=None)

    assert not fw.supported
    with pytest.raises(ProtocolError, match="layout for this model is unknown"):
        fw.read_image()
    with pytest.raises(ProtocolError, match="layout for this model is unknown"):
        fw.write_image(bytes(0x200))
    assert cp_sim.received["#CMDNR"] == 0


def test_read_command_absent_on_device(cp_sim, monkeypatch):
    # If a radio answers #CFLRR with #CMDUN, the read says so rather than hanging
    original = HXSimulator._process_cp_message

    def no_read(self, msg):
        if msg.startswith(b"#CFLRR"):
            return self._reply("#CMDUN")
        return original(self, msg)

    monkeypatch.setattr(HXSimulator, "_process_cp_message", no_read)
    with pytest.raises(ProtocolError, match="does not know the command #CFLRR"):
        firmware_of(cp_sim).read_image()


def test_image_checks(cp_sim):
    fw = firmware_of(cp_sim)

    checks = {c.what: c for c in fw.check_image(GOOD_IMAGE)}
    assert all(c.passed for c in checks.values()), checks
    assert "512 bytes" in checks["size"].detail and "padded" in checks["size"].detail
    assert checks["version"].detail == "image version '02.04'"
    assert "AM057N" in checks["model"].detail

    passed = {c.what: c.passed for c in fw.check_image(b"  01.00    " + b"AM070N" + bytes(0x100))}
    assert passed["model"] is False, "an HX891BT image is not for the HX870"
    passed = {c.what: c.passed for c in fw.check_image(bytes(0x201))}
    assert (passed["size"], passed["version"], passed["content"]) == (False, False, True)
    assert {c.what: c.passed for c in fw.check_image(b"\xff" * 0x200)}["content"] is False
    assert cp_sim.received["#CMDNR"] == 0, "checking an image sends nothing to the radio"


def test_erase_outlasts_the_transport_timeout(cp_sim, monkeypatch):
    # The radio acknowledges an erase when it is done, which takes longer than a transfer
    original = HXSimulator._process_cp_message

    def slow_erase(self, msg):
        if msg.startswith(b"#CFLER"):
            sleep(0.5)
        return original(self, msg)

    monkeypatch.setattr(HXSimulator, "_process_cp_message", slow_erase)
    fw = firmware_of(cp_sim)
    fw.enter_flash_mode()
    fw.p.conn.s.timeout = 0.2
    fw.erase()
    assert cp_sim.received["#CFLER"] == 1 and cp_sim.received["#CFLCB"] == 1


def test_flash_status_bits_are_named():
    assert FirmwareProtocol.describe_status("00") == "ready"
    assert FirmwareProtocol.describe_status("80") == "busy"
    assert FirmwareProtocol.describe_status("14") == "program error, ID error"
    assert FirmwareProtocol.describe_status("zz") == "unreadable"


def test_flash_error_status_is_reported_by_name(cp_sim, monkeypatch):
    fw = firmware_of(cp_sim)
    monkeypatch.setattr(FirmwareProtocol, "status", lambda self: "02")
    with pytest.raises(TimeoutError, match="status 02 \\(erase error\\)"):
        fw.wait_for_ready(timeout=0)


# The model class


def test_model_reboot_logs_its_own_line(cp_sim, caplog):
    hx = device.HX870(cp_sim.tty, identified=True)
    with caplog.at_level(logging.INFO):
        hx.reboot()
    assert f"Rebooting HX870 on {cp_sim.tty}" in caplog.text
    assert cp_sim.received["#CFLMC"] == 2 and cp_sim._flash_mode is False


@pytest.mark.parametrize("model", [device.HX870, device.HX890, device.HX891])
def test_flash_layout_of_the_models(model):
    # One area for all three, per the vendor's updaters for the HX870 and the HX890
    assert model.firmware_range == (0xf40000, 0xff0000) and model.firmware_chunk == 0x80
    assert device.GX1400.firmware_range is None


@pytest.mark.parametrize("model, config_model", [(device.HX890, config.HX890Config),
                                                 (device.HX891, config.HX891Config)])
def test_hx890_family_flash_session(model, config_model, kill_sims, monkeypatch):
    monkeypatch.setattr(device.HX870, "firmware_range", AREA)
    sim = HXSimulator(config_model, mode="CP", loop_delay=0.0005)
    sim.start()
    hx = model(sim.tty, identified=True)

    image = bytes((i * 5) & 0xff for i in range(0x200))
    hx.firmware.write_image(image)
    assert hx.firmware.read_image() == image
    assert sim.received["#CFLID"] == 1, "the model's own flash ID was accepted"
    hx.reboot()
    assert sim._flash_mode is False


def test_model_without_a_firmware_handler_cannot_reboot(cp_sim):
    hx = device.HX870(cp_sim.tty, identified=True)
    hx.firmware = None
    with pytest.raises(ProtocolError, match="cannot be rebooted"):
        hx.reboot()


# CLI


@pytest.fixture(name="sims")
def fixture_started_simulators(monkeypatch):
    """The simulators a CLI run starts, for a look at them afterwards"""
    started = []
    sim_start = HXSimulator.start

    def start_and_note(self):
        started.append(self)
        sim_start(self)

    monkeypatch.setattr(HXSimulator, "start", start_and_note)
    return started


@pytest.fixture(name="small_fw_area")
def fixture_small_firmware_area(monkeypatch):
    """Shrink the HX870 flash area so the CLI tests do a few transfers, not thousands"""
    monkeypatch.setattr(device.HX870, "firmware_range", AREA)


def handshakes(sims) -> int:
    return sum(sim.received["#CMDNR"] for sim in sims)


def test_cli_requires_an_action(kill_sims, capsys):
    assert main(["--simulator", "-t", "0", "firmware"]) != 0
    assert "Specify --readto or --writefrom" in capsys.readouterr().err


def test_cli_refuses_models_without_a_known_layout(kill_sims, sims, capsys, monkeypatch):
    monkeypatch.setattr(device.HX870, "firmware_range", None)
    assert main(["--simulator", "-t", "0", "firmware", "--readto", "/dev/null"]) != 0
    assert "layout for this model is unknown" in capsys.readouterr().err
    assert handshakes(sims) == 0


def test_cli_refuses_models_without_firmware_functions(kill_sims, sims, capsys):
    assert main(["--simulator", "-m", "GX1400", "-t", "0", "firmware", "--readto", "/dev/null"]) != 0
    assert "Firmware functions are not supported by GX1400" in capsys.readouterr().err
    assert handshakes(sims) == 0


@pytest.mark.parametrize("model", ["HX890", "HX891"])
def test_cli_read_from_the_hx890_family(model, tmp_path, kill_sims, sims, capsys, small_fw_area):
    out = tmp_path / "fw.bin"
    assert main(["--simulator", "-m", model, "-t", "0", "firmware", "--readto", str(out)]) == 0
    assert out.read_bytes() == b"\xff" * 0x200
    assert f"Rebooting {model}SIM" in capsys.readouterr().err


def test_cli_read_to_file_and_reboot(tmp_path, kill_sims, sims, capsys, small_fw_area):
    out = tmp_path / "fw.bin"
    assert main(["--simulator", "-t", "0", "firmware", "--readto", str(out)]) == 0
    assert out.read_bytes() == b"\xff" * 0x200, "the firmware area, erased"
    assert "Rebooting HX870SIM" in capsys.readouterr().err
    assert all(sim._flash_mode is False for sim in sims)


WRONG_IMAGE = b"  01.00    " + b"AM070N" + bytes(0x100)  # an HX891BT image, which fits the area


def test_cli_write_without_really_assesses_a_good_image(tmp_path, kill_sims, sims, capsys, small_fw_area):
    image = tmp_path / "fw.bin"
    image.write_bytes(GOOD_IMAGE)

    assert main(["--simulator", "-t", "0", "firmware", "--writefrom", str(image)]) == 0
    log = capsys.readouterr().err
    assert "--really" in log and "image version '02.04'" in log and "runs firmware '23.42'" in log
    assert handshakes(sims) == 0 and "Rebooting" not in log, "the radio is left alone"


def test_cli_write_without_really_warns_off_a_bad_image(tmp_path, kill_sims, sims, capsys, small_fw_area):
    image = tmp_path / "fw.bin"
    image.write_bytes(WRONG_IMAGE)

    assert main(["--simulator", "-t", "0", "firmware", "--writefrom", str(image)]) != 0
    log = capsys.readouterr().err
    assert "none of this model's flash IDs" in log
    assert any("Do not write this image" in line for line in log.splitlines() if " WARNING " in line)
    assert handshakes(sims) == 0


def test_cli_write_with_really_writes_whatever_the_assessment(tmp_path, kill_sims, sims, capsys, small_fw_area):
    image = tmp_path / "fw.bin"
    image.write_bytes(WRONG_IMAGE)

    assert main(["--simulator", "-t", "0", "firmware", "--writefrom", str(image), "--really"]) == 0
    log = capsys.readouterr().err
    assert "Rebooting HX870SIM" in log
    assert any(sim.firmware.get(AREA[0] + 11) == ord("A") for sim in sims), "the image reached the flash"


def test_cli_write_with_really_good_image(tmp_path, kill_sims, sims, capsys, small_fw_area):
    image = tmp_path / "fw.bin"
    image.write_bytes(GOOD_IMAGE)

    assert main(["--simulator", "-t", "0", "firmware", "--writefrom", str(image), "--really"]) == 0
    assert "Rebooting HX870SIM" in capsys.readouterr().err
    assert any(sim.firmware.get(AREA[0] + 2) == ord("0") for sim in sims), "the image reached the flash"


def test_cli_image_that_does_not_fit_cannot_be_written(tmp_path, kill_sims, sims, capsys, small_fw_area):
    image = tmp_path / "fw.bin"
    image.write_bytes(bytes(0x201))

    assert main(["--simulator", "-t", "0", "firmware", "--writefrom", str(image), "--really"]) != 0
    assert "at most 512 fit" in capsys.readouterr().err
    assert handshakes(sims) == 0


def test_cli_reboots_after_a_failed_transfer(tmp_path, kill_sims, sims, capsys, small_fw_area, monkeypatch):
    def fails(self, offset, length):
        raise ProtocolError("read went wrong")

    monkeypatch.setattr(FirmwareProtocol, "read", fails)
    assert main(["--simulator", "-t", "0", "firmware", "--readto", str(tmp_path / "fw.bin")]) != 0
    log = capsys.readouterr().err
    assert "read went wrong" in log and "Rebooting HX870SIM" in log, "the radio is not left in flash mode"
    assert not (tmp_path / "fw.bin").exists()
