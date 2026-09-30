# -*- coding: utf-8 -*-

from argparse import ArgumentError, ArgumentTypeError
from binascii import hexlify, unhexlify
from logging import getLogger
import os
import re

import hxtool
from .base import CliCommand

logger = getLogger(__name__)


def default_length():
    try:
        length = os.environ.get("HXTOOL_PEEK_LENGTH", "1")
        return hexadecimal_number(length)
    except (ArgumentTypeError, ValueError):
        return 1


def hexadecimal_number(string):
    number = int(string, 16)
    if number < 0:
        raise ArgumentTypeError("must be positive")
    return number


def hexadecimal_data(string):
    return unhexlify(bytes(re.sub(r"\A0x", "", string), 'utf-8'))


class PokeCommand(CliCommand):

    name = "poke"
    help = "Read/write hex bytes in the device memory (advanced feature, use caution)"

    @staticmethod
    def setup_args(parser) -> None:

        parser.add_argument('offset',
                            type=hexadecimal_number,
                            help="hex address to poke/peek")

        parser.add_argument('data',
                            nargs='?',
                            type=hexadecimal_data,
                            help="data to poke (when omitted: peek, don't poke)")

        parser.add_argument("-l", "--length",
                            type=hexadecimal_number,
                            help="hex number of bytes to poke/peek")

    def run(self):
        hx = hxtool.get(self.args)
        if hx is None:
            return 10

        if not hx.comm.cp_mode:
            logger.critical("Handset not in CP mode (MENU + ON)")
            return 11

        offset = self.args.offset
        data = self.args.data
        length = self.args.length

        if data is None:
            # peek
            if length is None:
                length = default_length()
        else:
            # poke
            if length is None:
                length = len(data)
            elif len(data) > length:
                data = data[0:length]
                logger.warning(f"Truncating data to "
                               f"{'0x%x' % length} byte{'s' if length != 1 else ''}")
            elif len(data) < length:
                raise ArgumentError(None, f"Data to poke is shorter than {'0x%x' % length} bytes")

        if length > hx.config.CHUNK_SIZE:
            raise ArgumentError(None,
                                f"Can't {'peek' if data is None else 'poke'} "
                                f"more than {'0x%X' % hx.config.CHUNK_SIZE} bytes at once "
                                f"on {type(hx).__name__}")
        if offset + length > hx.config.CONFIG_SIZE:
            raise ArgumentError(None,
                                f"Can't {'peek' if data is None else 'poke'} "
                                f"past the end of the {type(hx).__name__}'s memory "
                                f"at offset {'0x%X' % hx.config.CONFIG_SIZE}")

        hx.comm.sync()

        if data is None:
            print(hexlify(hx.comm.read_config_memory(offset, length)).decode())
        else:
            logger.info(f"Writing {hexlify(data)} to device at offset {'0x%04x' % offset}")
            hx.comm.write_config_memory(offset, data)

        logger.info("Operation successful")
        return 0
