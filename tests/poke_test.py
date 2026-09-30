# -*- coding: utf-8 -*-

import argparse
import pytest

from hxtool.main import main


def test_hxtool_peek(capsys):
    ret = main("--simulator -t 0 poke 0100 --length 0x6".split())
    assert ret == 0

    outerr = capsys.readouterr()
    assert "Operation successful" in outerr.err
    assert "414d3035374e\n" == outerr.out, "read HX870 flash id"


def test_hxtool_peek_no_length(capsys):
    ret = main("--simulator -t 0 poke 1c".split())
    assert ret == 0

    outerr = capsys.readouterr()
    assert "Operation successful" in outerr.err
    assert "ff\n" == outerr.out, "peek length defaults to 1"


def test_hxtool_poke(capsys):
    ret = main("--debug --simulator -t 0 poke 1234 aBCd".split())
    assert ret == 0

    outerr = capsys.readouterr()
    assert "Operation successful" in outerr.err
    assert """CP simulator processing message b'#CEPWR\\t1234\\t02\\tABCD\\t72\\r\\n'""" in outerr.err


def test_hxtool_poke_truncate(capsys):
    ret = main("--debug --simulator -t 0 poke 10 0x01020304 -l 1".split())
    assert ret == 0

    outerr = capsys.readouterr()
    assert "Truncating data to 0x1 byte" in outerr.err
    assert "Operation successful" in outerr.err
    assert """CP simulator processing message b'#CEPWR\\t0010\\t01\\t01\\t71\\r\\n'""" in outerr.err


def test_hxtool_peek_too_long_data():
    with pytest.raises(argparse.ArgumentError):
        main("--simulator -t 0 poke 005a -l 41".split())


def test_hxtool_poke_too_short_data():
    with pytest.raises(argparse.ArgumentError):
        main("--simulator -t 0 poke 12 00 -l 2".split())


def test_hxtool_poke_too_high_address():
    with pytest.raises(argparse.ArgumentError):
        main("--simulator -t 0 poke 7fff 0100".split())
