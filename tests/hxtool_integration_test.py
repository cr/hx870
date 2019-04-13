# -*- coding: utf-8 -*-

import pytest

from hxtool.main import main
from hxtool.device import HXSim


def test_hxtool_devices(capsys):
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
    assert HXSim.brand in cp_sim
    assert HXSim.model in cp_sim

    assert "NMEA mode" in nmea_sim
    assert HXSim.brand in nmea_sim
    assert HXSim.model in nmea_sim


def test_hxtool_info(capsys):
    args = [
        "--simulator",
        "-t", "0",
        "info"
    ]
    ret = main(args)
    assert ret == 0, "hxtool --simulator -t 0 info returns 0"

    outerr = capsys.readouterr()
    assert "CP mode" in outerr.err
    assert HXSim.handle in outerr.out
    assert HXSim.brand in outerr.out
    assert HXSim.model in outerr.out
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
    assert HXSim.handle in outerr.out
    assert HXSim.brand in outerr.out
    assert HXSim.model in outerr.out


def test_hxtool_id(capsys):
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


def test_hxtool_atis_mmsi(capsys):
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
    assert """CP simulator processing message b'#CEPWR\\t00B0\\t06\\tFFFFFFFFFF00\\t04\\r\\n'""" in outerr.err
    assert """CP simulator processing message b'#CEPWR\\t00B6\\t06\\tFFFFFFFFFF00\\t02\\r\\n'""" in outerr.err
    assert """CP simulator processing message b'#CEPWR\\t00B6\\t06\\t912345678901\\t0B\\r\\n'""" in outerr.err
    assert """CP simulator processing message b'#CEPWR\\t00B0\\t06\\t123456789002\\t07\\r\\n'""" in outerr.err


@pytest.mark.slow
def test_hxtool_config_dump(tmpdir):
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


@pytest.mark.slow
def test_hxtool_config_flash(tmpdir):
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
