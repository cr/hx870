# -*- coding: utf-8 -*-

import logging
import pytest
import subprocess
import sys
from sys import platform

from hxtool.main import main
from hxtool.protocol import Message
from hxtool.device import HX870Sim
from hxtool.simulator import HXSimulator


@pytest.fixture(name="kill_sims")
def kill_simulator_threads_fixture():
    # The simulator doesn't work on Windows, so skip tests that need one
    if platform.startswith("win"):
        pytest.skip("Skipping simulator tests on Windows")
    yield None
    HXSimulator.stop_instances()
    HXSimulator.join_instances()


def test_import_is_quiet():
    # Importing the package must not configure logging; that is the CLI's job
    code = "import logging, hxtool; print(logging.getLogger().handlers)"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"


def test_hxtool_configures_logging(capsys, kill_sims):
    del kill_sims
    assert main(["--simulator", "-t", "0", "info"]) == 0
    assert " INFO Device on " in capsys.readouterr().err, "the CLI logs to stderr"
    assert logging.getLogger().handlers, "the CLI installed a handler"


def test_hxtool_devices(capsys, kill_sims):
    del kill_sims
    args = [
        "--simulator",
        "devices"
    ]
    ret = main(args)
    assert ret == 0, "hxtool --simulator devices returns 0"

    outerr = capsys.readouterr()
    out = outerr.out.strip("\n").split("\n")
    assert len(out) >= 2, "Two simulators detected"
    assert out[0].startswith("[0]")
    assert out[1].startswith("[1]")

    cp_sim = out[0].split("\t")
    nmea_sim = out[1].split("\t")

    assert "CP mode" in cp_sim
    assert HX870Sim.brand in cp_sim
    assert HX870Sim.model in cp_sim

    assert "NMEA mode" in nmea_sim
    assert HX870Sim.brand in nmea_sim
    assert HX870Sim.model in nmea_sim


def test_hxtool_devices_selectors(capsys, kill_sims):
    del kill_sims

    # The model selector is honoured, so that the indices shown are the
    # ones that --tty N refers to when given along with the same --model
    assert main(["--simulator", "--model", "HX890", "devices"]) == 0
    out = capsys.readouterr().out.strip("\n").split("\n")
    assert len(out) == 2, "Only the HX890 simulators are listed"
    assert out[0].startswith("[0]") and "CP mode" in out[0]
    assert out[1].startswith("[1]") and "NMEA mode" in out[1]
    assert all("HX890S Simulator" in line for line in out)

    assert main(["--simulator", "--model", "HX890", "--tty", "1", "info"]) == 0
    assert "HX890SIM in NMEA mode" in capsys.readouterr().err, "Index 1 is what devices listed as [1]"

    # The device selector is ignored, as the list is what defines the indices
    assert main(["--simulator", "--tty", "3", "devices"]) == 0
    out = capsys.readouterr().out.strip("\n").split("\n")
    assert len(out) == 7, "All simulators are listed"
    assert [line.split("\t")[0] for line in out] == [f"[{i}]" for i in range(7)]


def test_hxtool_info(capsys, kill_sims):
    del kill_sims
    args = [
        "--simulator",
        "-t", "0",
        "info"
    ]
    ret = main(args)
    assert ret == 0, "hxtool --simulator -t 0 info returns 0"

    outerr = capsys.readouterr()
    assert "CP mode" in outerr.err
    assert HX870Sim.handle in outerr.out
    assert HX870Sim.brand in outerr.out
    assert HX870Sim.model in outerr.out
    assert "23.42" in outerr.out
    assert "MMSI" in outerr.out
    assert "ATIS" in outerr.out

    args = [
        "--simulator",
        "-t", "1",
        "info"
    ]
    ret = main(args)
    assert ret == 0, "hxtool --simulator -t 1 info returns 0"

    outerr = capsys.readouterr()
    assert "NMEA mode" in outerr.err
    assert HX870Sim.handle in outerr.out
    assert HX870Sim.brand in outerr.out
    assert HX870Sim.model in outerr.out


def test_hxtool_info_unknown_region(capsys, kill_sims, monkeypatch):
    del kill_sims
    sim_start = HXSimulator.start

    def start_with_unknown_region(self):
        self.c[self.type.REGION_CODE_OFFSET] = 0x49
        sim_start(self)

    monkeypatch.setattr(HXSimulator, "start", start_with_unknown_region)

    ret = main(["--simulator", "-t", "0", "info"])
    assert ret == 0, "hxtool info copes with an unknown region code"
    assert "Region:\t [49]" in capsys.readouterr().out


@pytest.fixture(name="sim_faults")
def fixture_simulator_faults(monkeypatch):
    # Faults put into this dict apply to all simulators started afterwards
    faults = {}
    sim_start = HXSimulator.start

    def start_with_faults(self):
        self.faults.update(faults)
        sim_start(self)

    monkeypatch.setattr(HXSimulator, "start", start_with_faults)
    yield faults


@pytest.mark.parametrize("command, reply_type", [
    (["info"], "#CEPDT"),
    (["id"], "#CEPDT"),
    (["gpslog"], "$PMTK"),
])
def test_hxtool_reports_protocol_errors(capsys, kill_sims, sim_faults, command, reply_type):
    del kill_sims
    sim_faults[reply_type] = "checksum"

    ret = main(["--simulator", "-t", "0"] + command)  # must not raise
    assert ret != 0, "Protocol error makes the command fail"
    err = capsys.readouterr().err
    assert "Protocol error" in err
    assert "Checksum mismatch" in err


def test_hxtool_reports_timeouts(capsys, kill_sims, sim_faults):
    del kill_sims
    sim_faults["#CVRDQ"] = "drop"

    ret = main(["--simulator", "-t", "0", "info"])
    assert ret != 0, "Timeout makes the command fail"
    err = capsys.readouterr().err
    assert "timeout" in err
    assert "Connection lost" not in err, "A silent device is not a lost connection"


def test_hxtool_id(capsys, kill_sims):
    del kill_sims

    args = [
        "--simulator",
        "-t", "0",
        "id"
    ]
    ret = main(args)
    assert ret == 0, "hxtool --simulator -t 0 id returns 0"

    outerr = capsys.readouterr()
    assert "CP mode" in outerr.err
    assert "23.42" in outerr.err
    assert "MMSI" in outerr.out
    assert "ATIS" in outerr.out

    args = [
        "--simulator",
        "-t", "1",
        "id"
    ]
    ret = main(args)
    assert ret != 0, "hxtool --simulator -t 1 id fails"

    outerr = capsys.readouterr()
    assert "not in CP mode" in outerr.err


def test_hxtool_atis_mmsi(capsys, kill_sims):
    del kill_sims

    args = [
        "--debug",
        "--simulator",
        "-t", "0",
        "id",
        "--mmsi", "123456789",
        "--atis", "9123456789",
        "--reset"
    ]
    ret = main(args)
    assert ret == 0, "hxtool atis/mmsi writing and reset returns 0"

    outerr = capsys.readouterr()
    assert written("00B0", "FFFFFFFFFF00") in outerr.err, "MMSI reset"
    assert written("00B6", "FFFFFFFFFF00") in outerr.err, "ATIS reset"
    assert written("00B6", "912345678900") in outerr.err, "ATIS written, counter left as reset"
    assert written("00B0", "123456789000") in outerr.err, "MMSI written, counter left as reset"


def written(offset, data) -> str:
    """The simulator's log line for a config write, checksum included"""
    return f"CP simulator processing message {Message('#CEPWR', [offset, '%02X' % (len(data) // 2), data])!r}"


def test_hxtool_id_counters(capsys, kill_sims):
    del kill_sims

    # A fresh simulator has never been programmed
    assert main(["--simulator", "-t", "0", "id"]) == 0
    out = capsys.readouterr().out
    assert "MMSI: FFFFFFFFF [counter 255]" in out
    assert "ATIS: FFFFFFFFFF [counter 255]" in out

    # Writing a code leaves the update counter alone
    assert main(["--debug", "--simulator", "-t", "0", "id", "--mmsi", "123456789"]) == 0
    assert written("00B0", "1234567890FF") in capsys.readouterr().err

    # The counter can be written by itself, leaving the code alone ...
    assert main(["--debug", "--simulator", "-t", "0", "id", "--mmsi-counter", "3"]) == 0
    assert written("00B0", "FFFFFFFFFF03") in capsys.readouterr().err

    # ... or along with the code
    assert main(["--debug", "--simulator", "-t", "0", "id", "--atis", "9123456789", "--atis-counter", "4"]) == 0
    assert written("00B6", "912345678904") in capsys.readouterr().err

    # A reset restores the factory state, unless a counter is given explicitly
    assert main(["--debug", "--simulator", "-t", "0", "id", "--reset", "--mmsi-counter", "9"]) == 0
    err = capsys.readouterr().err
    assert written("00B0", "FFFFFFFFFF09") in err
    assert written("00B6", "FFFFFFFFFF00") in err

    assert main(["--simulator", "-t", "0", "id", "--mmsi-counter", "300"]) != 0, "counter is one byte"


@pytest.mark.slow
def test_hxtool_config_dump(tmpdir, kill_sims):
    del kill_sims
    conf_file = tmpdir.mkdir("config_dump").join("config.dat")

    args = [
        "--simulator",
        "-t", "1",
        "config",
        "-d", str(conf_file)
    ]
    ret = main(args)
    assert ret != 0, "hxtool --simulator -t 1 config --dump fails"

    args = [
        "--simulator",
        "-t", "0",
        "config",
        "-d", str(conf_file)
    ]
    ret = main(args)
    assert ret == 0, "hxtool --simulator -t 0 config --dump returns 0"

    with open(conf_file, mode="rb") as f:
        config = f.read()
    assert len(config) == 1 << 15


def test_hxtool_config_dump_failure_keeps_file(tmpdir, kill_sims, monkeypatch):
    del kill_sims
    dump_dir = tmpdir.mkdir("config_dump")
    backup_file = dump_dir.join("backup.dat")
    backup_file.write_binary(b"precious backup")
    new_file = dump_dir.join("new.dat")

    # Make every simulator send config data with a broken checksum
    sim_start = HXSimulator.start

    def start_with_fault(self):
        self.faults["#CEPDT"] = "checksum"
        sim_start(self)

    monkeypatch.setattr(HXSimulator, "start", start_with_fault)

    for conf_file in backup_file, new_file:
        args = [
            "--simulator",
            "-t", "0",
            "config",
            "-d", str(conf_file)
        ]
        ret = main(args)
        assert ret != 0, "hxtool config --dump fails when the read fails"

    assert backup_file.read_binary() == b"precious backup", "Failed dump leaves existing file untouched"
    assert not new_file.exists(), "Failed dump does not create a file"


@pytest.mark.slow
def test_hxtool_config_flash(tmpdir, kill_sims):
    del kill_sims
    conf_file = tmpdir.mkdir("config_dump").join("config.dat")
    with open(conf_file, "wb") as f:
        f.write(b"\xff" * (1 << 15))

    args = [
        "--simulator",
        "-t", "1",
        "config",
        "-f", str(conf_file)
    ]
    ret = main(args)
    assert ret != 0, "hxtool --simulator -t 1 config --flash fails"

    args = [
        "--simulator",
        "-t", "0",
        "config",
        "-f", str(conf_file)
    ]
    ret = main(args)
    assert ret == 0, "hxtool --simulator -t 0 config --flash returns 0"
