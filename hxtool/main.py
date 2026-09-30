#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from argparse import ArgumentParser
from logging import getLogger
from sys import exit, argv, stdout

import coloredlogs
from importlib.metadata import version

import hxtool.cli
from hxtool.protocol import ProtocolError
from hxtool.simulator import HXSimulator

logger = getLogger(__name__)


def get_args(args=None):
    """
    Argument parsing
    :return: Argument parser object
    """

    pkg_version = version("hxtool")

    parser = ArgumentParser(prog="hxtool")
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
                        choices=hxtool.device.models.keys(),
                        action="store")

    parser.add_argument("--simulator",
                        help="enable simulator devices",
                        action="store_true")

    # Set up subparsers, one for each command
    subparsers = parser.add_subparsers(help="sub command", dest="command")
    commands_list = hxtool.cli.list_commands()
    for command_name in commands_list:
        command_class = commands_list[command_name]
        sub_parser = subparsers.add_parser(command_name, help=command_class.help)
        command_class.setup_args(sub_parser)

    return parser.parse_args(args or argv[1:])


def at_exit():
    logger.debug("Waiting for backround threads")
    HXSimulator.stop_instances()
    HXSimulator.join_instances()
    logger.debug("Backround threads finished")


# This is the entry point used in pyproject.toml
def main(main_args=None):
    args = get_args(main_args)

    # Logging is configured here and not at import, so that the package stays quiet as a library
    if args.debug:
        coloredlogs.install(level="DEBUG", fmt="%(asctime)s %(levelname)s %(name)s %(message)s")
    else:
        coloredlogs.install(level="INFO", fmt="%(asctime)s %(levelname)s %(message)s")

    logger.debug("Command arguments: %s" % args)

    try:
        result = hxtool.cli.run(args)

    except KeyboardInterrupt:
        stdout.write("\n")
        stdout.flush()
        logger.critical("User abort")
        result = 5

    except ProtocolError as e:
        logger.critical(f"Protocol error ({e})")
        result = 10

    except TimeoutError as e:
        logger.critical(f"Device timeout ({e})")
        result = 10

    except OSError as e:
        logger.critical(f"Connection lost ({e})")
        result = 10

    finally:
        at_exit()

    if result != 0:
        logger.error("Command failed")

    logger.debug("Leaving main()")
    return result


if __name__ == "__main__":
    exit(main())
