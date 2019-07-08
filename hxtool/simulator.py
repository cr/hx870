# -*- coding: utf-8 -*-

from binascii import hexlify, unhexlify
from logging import getLogger
from os import ttyname, read, write, close, set_blocking
# FIXME: Importing pty fails on Windows
from pty import openpty
from threading import Event, Thread
from time import time

from .protocol import Message

logger = getLogger(__name__)


class HXSimulator(Thread):

    instances = []
    loop_delay_default = 1 / 38400

    @classmethod
    def register(cls, instance):
        cls.instances.append(instance)

    @classmethod
    def stop_instances(cls):
        for instance in cls.instances:
            if instance.is_alive():
                instance.stop()

    @classmethod
    def join_instances(cls):
        for instance in cls.instances:
            instance.join()

    def __init__(self, mode: str, config: bytearray or None = None,
                 loop_delay: float = None, nmea_delay: float = 3.0):
        super().__init__()
        HXSimulator.register(self)
        self.id = HXSimulator.instances.index(self)
        assert mode in ["CP", "NMEA"], "Invalid simulator mode"
        self.mode = mode
        self.c = config or bytearray(b"\xff" * 0x8000)
        self.master, self.slave = openpty()
        self.tty = ttyname(self.slave)
        self.name = f"HXSimulator-{self.id} [{self.tty}]"
        self.stop_running = Event()
        self.loop_delay = loop_delay or self.loop_delay_default
        self.nmea_delay = nmea_delay
        # FIXME: This will fail on Windows (probably on import)
        set_blocking(self.master, False)
        self.ignore_cmdok = False

    def run(self):
        if self.stop_running.is_set():
            raise Exception("HXSimulator can not be restarted")
        if self.mode == "NMEA":
            self.__run_nmea_mode()
        elif self.mode == "CP":
            self.__run_cp_mode()
        else:
            raise Exception("Invalid simulator mode")

    def stop(self):
        self.stop_running.set()

    def __run_nmea_mode(self):
        logger.debug("Starting simulator thread in NMEA mode")
        message = b""
        next_message_time = time() + self.nmea_delay
        while not self.stop_running.wait(self.loop_delay):
            try:
                b = read(self.master, 1)
            except BlockingIOError:
                b = b""
            if len(b) > 0:
                # We have input and all NMEA messages start with $
                if len(message) > 0:
                    # If we are receiving part of a message, append
                    # input to message buffer until newline received.
                    message += b
                    if message.endswith(b"\r\n"):
                        # If line is complete, process message
                        self.__process_nmea_message(message)
                        message = b""
                elif b == b"$":
                    message = b
                elif b == b"P":
                    # Reply with P to P to signal NMEA mode
                    logger.debug("NMEA simulator responding to ping")
                    write(self.master, b"P")
                else:
                    # Ignore all other bytes outside of messages
                    logger.debug(f"NMEA simulator ignoring unexpected input {b}")
            else:
                # No input, so check whether it's time to send
                # a dummy NMEA message.
                now = time()
                if now >= next_message_time:
                    write(self.master, b"$GPLL,,,,\r\n")
                    next_message_time = now + self.nmea_delay

        logger.debug("NMEA simulator thread finished")

    def __process_nmea_message(self, msg):
        logger.debug(f"NMEA simulator processing message {msg}")

    def __run_cp_mode(self):
        logger.debug("Starting simulator thread in CP mode")
        message = b""
        while not self.stop_running.wait(self.loop_delay):
            try:
                b = read(self.master, 1)
            except BlockingIOError:
                b = b""
            if len(b) > 0:
                logger.debug(f"CP mode got {b}")
                # We have input and all NMEA messages start with $
                if len(message) > 0:
                    # If we are receiving part of a message, append
                    # input to message buffer until newline received.
                    message += b
                    if message.endswith(b"\r\n"):
                        # If line is complete, process message
                        if message.startswith(b"0"):
                            # The real HX870 doesn't react to the 0ACMD:002
                            logger.debug(f"CP simulator ignoring message {message}")
                        else:
                            self.__process_cp_message(message)
                        message = b""
                elif b == b"0":
                    # Beginning of 0ACMD:002 message?
                    message = b
                elif b == b"#":
                    # Beginning of a #-style command
                    message = b
                elif b == b"?":
                    # Reply with @ to ? to signal CP mode
                    logger.debug("CP simulator responding to ping")
                    write(self.master, b"@")
                else:
                    # Ignore all other bytes outside of messages
                    logger.debug(f"CP simulator ignoring unexpected input {b}")

        logger.debug("CP simulator thread finished")

    def __process_cp_message(self, msg):
        logger.debug(f"CP simulator processing message {msg}")
        msg = Message(parse=msg)
        if not msg.validate():
            write(self.master, bytes(Message("#CMDER")))
            return
        if msg.type == "#CMDOK":
            if self.ignore_cmdok:
                self.ignore_cmdok = False
            else:
                write(self.master, bytes(Message("#CMDOK")))
        elif msg.type == "#CMDSY":
            write(self.master, bytes(Message("#CMDOK")))
        elif msg.type == "#CVRRQ":
            write(self.master, bytes(Message("#CMDOK")))
            write(self.master, bytes(Message("#CVRDQ", ["23.42"])))
        elif msg.type == "#CEPSR":
            write(self.master, bytes(Message("#CMDOK")))
            write(self.master, bytes(Message("#CEPSD", ["00"])))
            self.ignore_cmdok = True
        elif msg.type == "#CEPRD":
            write(self.master, bytes(Message("#CMDOK")))
            offset = int(msg.args[0], 16)
            size = int(msg.args[1], 16)
            data = hexlify(self.c[offset:offset + size]).decode("ascii").upper()
            write(self.master, bytes(Message("#CEPDT", [msg.args[0], msg.args[1], data])))
            # Ignore next CMDOK
            self.ignore_cmdok = True
        elif msg.type == "#CEPWR":
            offset = int(msg.args[0], 16)
            size = int(msg.args[1], 16)
            data = unhexlify(msg.args[2])
            if len(data) == size:
                self.c[offset:offset + size] = data
                write(self.master, bytes(Message("#CMDOK")))
                if len(self.c) != 1 << 15:
                    logger.critical("CP simulator internal memory corruption after write")
            else:
                write(self.master, bytes(Message("#CMDER")))
        else:
            write(self.master, bytes(Message("#CMDER")))
