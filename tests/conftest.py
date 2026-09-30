# -*- coding: utf-8 -*-

import pytest
import serial.tools.list_ports
import sys

from hxtool.simulator import HXSimulator

WINDOWS = sys.platform.startswith("win")


def pytest_collection_modifyitems(config, items):
    """The simulator needs a pty, so every test that uses one is skipped on Windows"""
    if not WINDOWS:
        return
    skip = pytest.mark.skip(reason="simulator tests need a pty, unavailable on Windows")
    for item in items:
        if any("sim" in name for name in item.fixturenames):
            item.add_marker(skip)


@pytest.fixture(name="kill_sims")
def kill_simulator_threads_fixture():
    """Stop and join every simulator the test started"""
    yield None
    HXSimulator.stop_instances()
    HXSimulator.join_instances()


@pytest.fixture(autouse=True)
def no_real_serial_ports(request, monkeypatch):
    """
    Keep the tests away from real radios: unless a test is marked `hardware`,
    pyserial lists no serial ports at all, so device enumeration sees only the
    simulators (their ptys are never listed) and ports named explicitly.
    """
    if request.node.get_closest_marker("hardware"):
        return
    monkeypatch.setattr(serial.tools.list_ports, "comports", lambda *args, **kwargs: [])
    monkeypatch.setattr(serial.tools.list_ports, "grep", lambda *args, **kwargs: iter([]))
