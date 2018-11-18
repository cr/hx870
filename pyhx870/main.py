#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import coloredlogs
import logging
import os
import pkg_resources as pkgr
import sys

from . import cli

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

    pkg_version = pkgr.require("pyhx870")[0].version

    parser = argparse.ArgumentParser(prog="pyhx870")
    parser.add_argument("--version", action="version", version="%(prog)s " + pkg_version)

    parser.add_argument("-d", "--debug",
                        help="enable debug logging",
                        action="store_true")

    parser.add_argument("-t", "--tty",
                        help="force path to tty device",
                        type=os.path.abspath,
                        action="store")

    # Set up subparsers, one for each command
    subparsers = parser.add_subparsers(help="sub command", dest="command")
    commands_list = cli.list_commands()
    for command_name in commands_list:
        command_class = commands_list[command_name]
        sub_parser = subparsers.add_parser(command_name, help=command_class.help)
        command_class.setup_args(sub_parser)

    return parser.parse_args(argv)


# This is the entry point used in setup.py
def main():
    global logger

    args = get_args()

    if args.debug:
        coloredlogs.DEFAULT_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
        coloredlogs.install(level="DEBUG")

    logger.debug("Command arguments: %s" % args)

    try:
        result = cli.run(args)

    except KeyboardInterrupt:
        sys.stdout.write("\n")
        sys.stdout.flush()
        logger.critical("User abort")
        return 5

    except OSError as e:
        logger.critical("Connection lost")
        return 10

    if result != 0:
        logger.error("Command failed")
    return result
