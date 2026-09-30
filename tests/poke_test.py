# -*- coding: utf-8 -*-

import pytest

from hxtool.main import main
from hxtool.protocol import Message
from hxtool.simulator import HXSimulator


@pytest.fixture(name="sim_memory")
def fixture_simulator_memory(monkeypatch):
    """Preset the config memory of every simulator started afterwards, and keep the final state"""
    preset = {}
    final = {}
    sim_start, sim_stop = HXSimulator.start, HXSimulator.stop

    def start_with_preset(self):
        for offset, data in preset.items():
            self.c[offset:offset + len(data)] = data
        sim_start(self)

    def stop_and_record(self):
        final[self.type.__name__, self.mode] = bytes(self.c)
        sim_stop(self)

    monkeypatch.setattr(HXSimulator, "start", start_with_preset)
    monkeypatch.setattr(HXSimulator, "stop", stop_and_record)
    yield preset, final


def written(offset, data) -> str:
    """The simulator's log line for a config write, checksum included"""
    return f"CP simulator processing message {Message('#CEPWR', [offset, '%02X' % (len(data) // 2), data])!r}"


def test_hxtool_peek(capsys, kill_sims):
    assert main("--simulator -t 0 poke 0100 --length 0x6".split()) == 0
    outerr = capsys.readouterr()
    assert "Operation successful" in outerr.err
    assert outerr.out == "414d3035374e\n", "read HX870 flash id"


def test_hxtool_peek_no_length(capsys, kill_sims):
    assert main("--simulator -t 0 poke 1c".split()) == 0
    outerr = capsys.readouterr()
    assert "Operation successful" in outerr.err
    assert outerr.out == "ff\n", "peek length defaults to 1"


def test_hxtool_peek_length_from_environment(capsys, kill_sims, monkeypatch):
    monkeypatch.setenv("HXTOOL_PEEK_LENGTH", "4")
    assert main("--simulator -t 0 poke 0100".split()) == 0
    assert capsys.readouterr().out == "414d3035\n", "default peek length from the environment"

    monkeypatch.setenv("HXTOOL_PEEK_LENGTH", "four")
    assert main("--simulator -t 0 poke 0100".split()) == 0
    assert capsys.readouterr().out == "41\n", "unusable environment value falls back to 1"


def test_hxtool_poke(capsys, kill_sims, sim_memory):
    _, final = sim_memory
    assert main("--debug --simulator -t 0 poke 1234 aBCd".split()) == 0
    outerr = capsys.readouterr()
    assert "Operation successful" in outerr.err
    assert written("1234", "ABCD") in outerr.err
    assert final["HX870Config", "CP"][0x1234:0x1237] == b"\xab\xcd\xff", "poke landed in device memory"


def test_hxtool_poke_truncate(capsys, kill_sims):
    assert main("--debug --simulator -t 0 poke 10 0x01020304 -l 1".split()) == 0
    outerr = capsys.readouterr()
    assert "Truncating data to 0x1 byte" in outerr.err
    assert "Operation successful" in outerr.err
    assert written("0010", "01") in outerr.err


def test_hxtool_peek_preset_memory(capsys, kill_sims, sim_memory):
    preset, _ = sim_memory
    preset[0x2000] = b"\x01\x02\x03\x04"
    assert main("--simulator -t 0 poke 2000 -l 4".split()) == 0
    assert capsys.readouterr().out == "01020304\n"


def test_hxtool_poke_memory_limits(capsys, kill_sims):
    # HX870: 0x40 bytes per transfer, 0x8000 bytes of memory
    assert main("--simulator -t 0 poke 0000 -l 40".split()) == 0, "a whole chunk at once"
    assert capsys.readouterr().out == "0367" + "ff" * 0x3e + "\n", "starts with the config magic"
    assert main("--simulator -t 0 poke 7fff".split()) == 0, "last byte of memory"
    assert capsys.readouterr().out == "67\n", "the config magic's low byte"

    assert main("--simulator -t 0 poke 005a -l 41".split()) != 0, "more than a chunk"
    assert "more than 0x40 bytes" in capsys.readouterr().err
    assert main("--simulator -t 0 poke 7fff 0100".split()) != 0, "past the end of memory"
    assert "past the end" in capsys.readouterr().err
    assert main("--simulator -t 0 poke 8000".split()) != 0, "first byte past the end of memory"
    assert "past the end" in capsys.readouterr().err

    # GX1400: 0x20 bytes per transfer, 0x2000 bytes of memory
    assert main("--simulator -m GX1400 poke 0000 -l 20".split()) == 0
    assert main("--simulator -m GX1400 poke 0000 -l 21".split()) != 0
    assert "more than 0x20 bytes" in capsys.readouterr().err
    assert main("--simulator -m GX1400 poke 1fff".split()) == 0
    assert main("--simulator -m GX1400 poke 2000".split()) != 0


def test_hxtool_poke_data_length(capsys, kill_sims):
    assert main("--simulator -t 0 poke 12 00 -l 2".split()) != 0, "data shorter than length"
    assert "shorter than 0x2 bytes" in capsys.readouterr().err


@pytest.mark.parametrize("args", [
    "poke -1",  # negative offset
    "poke 10 -l -1",  # negative length
    "poke 10 abc",  # odd number of hex digits
    "poke 10 xyz",  # not hex
    "poke zz",  # offset not hex
])
def test_hxtool_poke_invalid_arguments(capsys, args):
    with pytest.raises(SystemExit) as e:
        main(("--simulator -t 0 " + args).split())
    assert e.value.code == 2, "argparse rejects the arguments"
    assert "usage:" in capsys.readouterr().err


def test_hxtool_poke_needs_cp_mode(capsys, kill_sims):
    assert main("--simulator -t 1 poke 0100".split()) == 11, "NMEA mode simulator"
    assert "not in CP mode" in capsys.readouterr().err


def test_hxtool_poke_no_device(capsys, kill_sims):
    assert main("--tty /dev/hxtool-does-not-exist poke 0100".split()) == 10
    assert "No device detected" in capsys.readouterr().err


def test_hxtool_poke_protocol_error(capsys, kill_sims, monkeypatch):
    sim_start = HXSimulator.start

    def start_with_fault(self):
        self.faults["#CEPSD"] = "checksum"
        sim_start(self)

    monkeypatch.setattr(HXSimulator, "start", start_with_fault)
    assert main("--simulator -t 0 poke 1234 abcd".split()) != 0
    err = capsys.readouterr().err
    assert "Protocol error" in err and "Checksum mismatch" in err
    assert "Operation successful" not in err
