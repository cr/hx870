# -*- coding: utf-8 -*-

import pytest
from sys import platform

from hxtool import config, protocol, simulator

# The simulator doesn't work on Windows, so skip test if running on Windows
if platform.startswith("win"):
    pytest.skip("Skipping simulator tests on Windows", allow_module_level=True)


@pytest.fixture(name="cp_870_sim")
def fixture_cp_simulator():
    s = simulator.HXSimulator(config.HX870Config, mode="CP")
    s.start()
    yield s
    s.stop()
    s.join(timeout=1)


@pytest.fixture(name="cp_890_sim")
def fixture_cp_simulator():
    s = simulator.HXSimulator(config.HX890Config, mode="CP")
    s.start()
    yield s
    s.stop()
    s.join(timeout=1)


@pytest.fixture(name="kill_sims")
def kill_simulator_threads_fixture():
    yield None
    simulator.HXSimulator.stop_instances()
    simulator.HXSimulator.join_instances()


@pytest.fixture(name="sim_870_config")
def fixture_config_simulator(cp_870_sim):
    yield config.HX870Config(protocol.GenericHXProtocol(cp_870_sim.tty))


# @pytest.mark.skip
# def test_cp_870_config_rw(cp_870_sim, kill_sims):
#     del kill_sims

#     p = GenericHXProtocol(cp_870_sim.tty)
#     p.cmd_mode()

#     random_bytes = bytearray(getrandbits(8) for _ in range(0x110))
#     p.write_config_memory(0x1000, random_bytes)
#     m = p.read_config_memory(0x1000, len(random_bytes))
#     assert m == random_bytes
