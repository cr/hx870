# -*- coding: ascii -*-

import pytest

from hxtool.device import enumerate
from hxtool.simulator import HXSimulator
from sys import platform


@pytest.fixture(name="kill_sims")
def kill_simulator_threads_fixture():
    if platform.startswith("win"):
        pytest.skip("Skipping simulator tests on Windows", allow_module_level=True)
    yield None
    HXSimulator.stop_instances()
    HXSimulator.join_instances()


def test_enumerate_all(kill_sims):
    devices = [type(d).__name__ for d in enumerate(add_simulator=True)]
    assert "HX870Sim" in devices
    assert "HX890Sim" in devices
    assert "HX891Sim" in devices
    assert "GX1400" in devices
    assert len(devices) == 7


def test_enumerate_force_device(kill_sims):
    all_devices = enumerate(add_simulator=True)
    for i in range(len(all_devices)):
        devices = enumerate(force_device=f"{i}", add_simulator=True)
        assert len(devices) == 1
        assert type(devices[0]) is type(all_devices[i])
        assert devices[0].cp_mode == all_devices[i].cp_mode

    assert not enumerate(force_device=f"{len(all_devices) + 1}", add_simulator=True)
