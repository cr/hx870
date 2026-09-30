# -*- coding: utf-8 -*-

from argparse import Namespace
import pytest

from hxtool.cli import base
from hxtool.protocol import ProtocolError


@pytest.fixture(name="command")
def fixture_command(monkeypatch):
    """A throwaway command that records its life cycle"""
    calls = []

    class Recorder(base.CliCommand):
        name = "recorder"
        setup_ok = True
        run_raises = None

        def setup(self):
            calls.append("setup")
            return self.setup_ok

        def run(self):
            calls.append("run")
            if self.run_raises:
                raise self.run_raises
            return 0

        def teardown(self):
            calls.append("teardown")

    # Keep the throwaway command out of the real command list
    monkeypatch.setattr(base, "list_commands", lambda: {"recorder": Recorder})
    Recorder.calls = calls
    yield Recorder


def test_run_life_cycle(command):
    assert base.run(Namespace(command="recorder")) == 0
    assert command.calls == ["setup", "run", "teardown"]


def test_run_tears_down_after_failed_setup(command):
    command.setup_ok = False
    assert base.run(Namespace(command="recorder")) == 10
    assert command.calls == ["setup", "teardown"]


@pytest.mark.parametrize("exception", [ProtocolError("boom"), TimeoutError("silence"), OSError("gone")])
def test_run_tears_down_on_error(command, exception):
    command.run_raises = exception
    with pytest.raises(type(exception)):
        base.run(Namespace(command="recorder"))
    assert command.calls == ["setup", "run", "teardown"], "teardown runs exactly once, whatever the error"


def test_run_tears_down_on_user_abort(command):
    command.run_raises = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        base.run(Namespace(command="recorder"))
    assert command.calls == ["setup", "run", "teardown"]


def test_run_unknown_command(command):
    assert base.run(Namespace(command="nonesuch")) == 5
    assert command.calls == []
