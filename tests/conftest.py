# -*- coding: utf-8 -*-

import pytest
import serial.tools.list_ports


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
