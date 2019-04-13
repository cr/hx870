# -*- coding: utf-8 -*-

import logging

from . import cli
from . import device
from . import config
from . import config_file
from . import main
from . import memory
from . import protocol
from . import simulator
from . import tty

__all__ = [
    "cli",
    "device",
    "config",
    "config_file",
    "main",
    "memory",
    "protocol",
    "simulator",
    "tty"
]

logger = logging.getLogger(__name__)


def get(args):
    """Select a single device according to arguments"""
    devices = device.enumerate(force_model=args.model, force_device=args.tty, add_simulator=args.simulator)

    if len(devices) == 0:
        logger.critical("No device detected. Connect device or try specifying --tty")
        return None

    if len(devices) > 1:
        logger.warning(f"Multiple devices detected, using {devices[0].tty}")

    return devices[0]
