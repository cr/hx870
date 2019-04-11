#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import atexit
import coloredlogs
import logging
import os
import pkg_resources as pkgr
import sys

from . import cli
from .simulator import HXSimulator

coloredlogs.DEFAULT_LOG_FORMAT = "%(asctime)s %(levelname)s %(message)s"
coloredlogs.install(level="INFO")
logger = logging.getLogger(__name__)


def get_args(argv=None):
    """
    Argument parsing
    :return: Argument parser object
    """
    if argv is None:
        argv = sys.argv[1:]

    pkg_version = pkgr.require("hxtool")[0].version

    parser = argparse.ArgumentParser(prog="hxtool")
    parser.add_argument("--version", action="version", version="%(prog)s " + pkg_version)

    parser.add_argument("--debug",
                        help="enable debug logging",
                        action="store_true")

    parser.add_argument("-t", "--tty",
                        help="force path or port for serial device",
                        type=str,
                        action="store")

    parser.add_argument("-m", "--model",
                        help="force device model",
                        type=str.upper,
                        choices=["HX870", "HX890"],
                        action="store")

    parser.add_argument("--simulator",
                        help="enable simulator devices",
                        action="store_true")

    # Set up subparsers, one for each command
    subparsers = parser.add_subparsers(help="sub command", dest="command")
    commands_list = cli.list_commands()
    for command_name in commands_list:
        command_class = commands_list[command_name]
        sub_parser = subparsers.add_parser(command_name, help=command_class.help)
        command_class.setup_args(sub_parser)

    return parser.parse_args(argv)


@atexit.register
def at_exit():
    logger.debug("Waiting for backround threads")
    HXSimulator.stop_instances()
    HXSimulator.join_instances()
    logger.debug("Backround threads finished")


# This is the entry point used in setup.py
def main():
    global logger

    args = get_args()

    if args.debug:
        coloredlogs.DEFAULT_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
        coloredlogs.install(level="DEBUG")

    logger.debug("Command arguments: %s" % args)

    result = 20

    try:
        result = cli.run(args)

    except KeyboardInterrupt:
        sys.stdout.write("\n")
        sys.stdout.flush()
        logger.critical("User abort")
        result = 5

    except OSError as e:
        logger.critical(f"Connection lost ({e})")
        result = 10

    finally:
        at_exit()

    if result != 0:
        logger.error("Command failed")

    logger.debug("Leaving main()")
    return result
