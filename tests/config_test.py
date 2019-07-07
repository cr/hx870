# -*- coding: utf-8 -*-

import pytest
from sys import platform

from hxtool import config, protocol, simulator

# The simulator doesn't work on Windows, so skip test if running on Windows
if platform.startswith("win"):
    pytest.skip("Skipping simulator tests on Windows", allow_module_level=True)


@pytest.fixture(name="cp_sim")
def fixture_cp_simulator():
    s = simulator.HXSimulator(mode="CP")
    s.start()
    yield s
    s.stop()
    s.join(timeout=1)


@pytest.fixture(name="sim_config")
def fixture_config_simulator(cp_sim):
    yield config.HX870Config(protocol.GenericHXProtocol(cp_sim.tty))
