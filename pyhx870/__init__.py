# -*- coding: utf-8 -*-

from distutils.spawn import find_executable
import logging
import os
import subprocess

from .protocol import HX870

logger = logging.getLogger(__name__)


def get(args=None) -> HX870 or None:

    # --tty argument overrides autodetection
    if args is not None:
        if args.tty is not None:
            if os.path.exists(args.tty):
                return HX870(tty=args.tty)
            else:
                return None

    # Mac OS X
    ioreg_exe = find_executable("ioreg")
    if ioreg_exe is not None:
        logger.debug(f"Found ioreg executable at {ioreg_exe}")
        cmd = [ioreg_exe, "-n", "HX870", "-rlw0"]
        p = subprocess.run(cmd, capture_output=True)
        if p.returncode != 0:
            logger.error(f"ioreg failed with returncode {p.returncode}")
            return None
        lines = p.stdout.decode().splitlines()
        if len(lines) == 0:
            return None
        try:
            line = next(filter(lambda l: "IODialinDevice" in l, lines))
        except StopIteration:
            return None
        dev = line.split("=")[1].strip(' "')
        logger.debug(f"ioreg reports HX870 at {dev}")
        if not dev.startswith("/dev"):
            return None
        return HX870(tty=dev)

    logger.critical("Unsupported operating system")
    return None
