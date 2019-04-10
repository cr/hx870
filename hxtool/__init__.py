# -*- coding: utf-8 -*-

import logging

logger = logging.getLogger(__name__)

from .device import enumerate


def get(args):
    """Select a single device according to arguments"""
    devices = enumerate(force_model=args.model, force_device=args.tty)

    if len(devices) == 0:
        logger.error("No device detected. Connect device or specify --device")
        return None

    if len(devices) > 1:
        logger.warning(f"Multiple devices detected, using {devices[0].tty}")

    return devices[0]
