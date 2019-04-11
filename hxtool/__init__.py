# -*- coding: utf-8 -*-

import logging

from .device import enumerate

logger = logging.getLogger(__name__)


def get(args):
    """Select a single device according to arguments"""
    devices = enumerate(force_model=args.model, force_device=args.tty, add_simulator=args.simulator)

    if len(devices) == 0:
        logger.critical("No device detected. Connect device or try specifying --tty")
        return None

    if len(devices) > 1:
        logger.warning(f"Multiple devices detected, using {devices[0].tty}")

    return devices[0]
