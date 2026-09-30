# -*- coding: utf-8 -*-

from binascii import hexlify, unhexlify
from logging import getLogger
from os import read, write, close
from threading import Event, Thread
from time import time

from .protocol import Message
from .config import GenericHXConfig
from .locus import Locus, LocusHeader

logger = getLogger(__name__)


class SimulatorError(Exception):
    pass


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

    def __init__(self, device_type: GenericHXConfig, mode: str, config: bytearray = None,
                 loop_delay: float = None, nmea_delay: float = 1.0, nmea_partial: bool = False,
                 nmea_ping: bool = False):
        """
        nmea_delay: seconds between NMEA sentences, or None for a radio whose GPS is silent
        nmea_partial: start the NMEA stream in the middle of a sentence
        nmea_ping: reply with "P" to "P" in NMEA mode, as the HX891BT does (the HX870 does not)
        """
        # The simulator is built on pseudo terminals, which don't exist on
        # all platforms (Windows). Importing them here keeps the module
        # importable everywhere.
        try:
            from os import ttyname, set_blocking
            from pty import openpty
        except ImportError as e:
            raise SimulatorError("Simulator is not supported on this platform") from e

        super().__init__()
        HXSimulator.register(self)
        self.id = HXSimulator.instances.index(self)
        self.type = device_type
        assert mode in ["CP", "NMEA"], "Invalid simulator mode"
        self.mode = mode
        if config:
            self.c = config
            assert len(config) == self.type.CONFIG_SIZE, "Invalid config size"
        else:
            # Populate config memory like a radio's: magic at both ends, flash ID
            self.c = bytearray(b"\xff" * self.type.CONFIG_SIZE)
            magic = self.type.CONFIG_MAGIC.to_bytes(2, "big")
            self.c[0:2] = magic
            self.c[-2:] = magic
            fid = self.type.FLASH_ID[0].encode("ascii")
            fid_offset = self.type.FLASH_ID_OFFSET
            self.c[fid_offset:fid_offset+len(fid)] = fid

        self.master, self.slave = openpty()
        self.tty = ttyname(self.slave)
        self.name = f"HXSimulator-{self.id} [{self.tty}]"
        self.stop_running = Event()
        self.loop_delay = loop_delay or self.loop_delay_default
        self.nmea_delay = nmea_delay
        self.nmea_partial = nmea_partial
        self.nmea_ping = nmea_ping
        set_blocking(self.master, False)
        self.ignore_cmdok = False
        # Fault injection for tests. Maps a reply type to the fault applied
        # to every reply of that type, e.g. {"#CEPDT": "checksum"}.
        self.faults = {}
        # Raw content of the GPS logger flash, a multiple of 4k sectors
        self.gps_log = b""

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
        try:
            close(self.master)
        except OSError:
            pass
        try:
            close(self.slave)
        except OSError:
            pass

    def __run_nmea_mode(self):
        logger.debug("Starting simulator thread in NMEA mode")
        message = b""
        sentence = b"$GPLL,,,,\r\n"
        if self.nmea_partial:
            # The host may open the port while a sentence is on the wire
            write(self.master, sentence[3:])
        next_message_time = time() + self.nmea_delay if self.nmea_delay is not None else None
        while not self.stop_running.wait(self.loop_delay):
            for b in self.__input():
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
                elif b == b"P" and self.nmea_ping:
                    logger.debug("NMEA simulator responding to ping")
                    write(self.master, b"P")
                else:
                    # Ignore all other bytes outside of messages
                    logger.debug(f"NMEA simulator ignoring unexpected input {b}")
            # Is it time to send a dummy NMEA message?
            now = time()
            if next_message_time is not None and now >= next_message_time:
                write(self.master, sentence)
                next_message_time = now + self.nmea_delay

        logger.debug("NMEA simulator thread finished")

    def __input(self):
        """Whatever the host has sent since the last look, one byte at a time"""
        try:
            data = read(self.master, 4096)
        except BlockingIOError:
            return
        except OSError:  # Simulator likely closed, tty died
            return
        for i in range(len(data)):
            yield data[i:i + 1]

    def __process_nmea_message(self, msg):
        logger.debug(f"NMEA simulator processing message {msg}")

    def __run_cp_mode(self):
        logger.debug("Starting simulator thread in CP mode")
        message = b""
        while not self.stop_running.wait(self.loop_delay):
            for b in self.__input():
                # Messages start with 0, # or $ and end with a newline
                if len(message) > 0:
                    # If we are receiving part of a message, append
                    # input to message buffer until newline received.
                    message += b
                    if message.endswith(b"\r\n"):
                        # If line is complete, process message
                        if message.startswith(b"0"):
                            # The real HX870 doesn't react to the 0ACMD:002
                            logger.debug(f"CP simulator ignoring message {message}")
                        elif message.startswith(b"$"):
                            self.__process_gps_message(message)
                        else:
                            self.__process_cp_message(message)
                        message = b""
                elif b == b"0":
                    # Beginning of 0ACMD:002 message?
                    message = b
                elif b == b"#":
                    # Beginning of a #-style command
                    message = b
                elif b == b"$":
                    # Beginning of a sentence for the GPS module
                    message = b
                elif b == b"?":
                    # Reply with @ to ? to signal CP mode
                    logger.debug("CP simulator responding to ping")
                    write(self.master, b"@")
                else:
                    # Ignore all other bytes outside of messages
                    logger.debug(f"CP simulator ignoring unexpected input {b}")

        logger.debug("CP simulator thread finished")

    def __reply(self, message_type, args=None):
        fault = self.faults.get(message_type)
        if fault == "drop":
            # The reply never makes it to the host
            return
        if message_type == "#CEPDT" and fault in ("address", "length", "truncate"):
            # Replies that are well-formed, but do not match the request
            offset, length, data = args
            if fault == "address":
                offset = "%04X" % (int(offset, 16) ^ 0x0040)
            elif fault == "length":
                length = "%02X" % (int(length, 16) ^ 0x01)
            elif fault == "truncate":
                data = data[:-2]
            args = [offset, length, data]
        msg = Message(message_type, args)
        if fault == "checksum":
            # Received checksum has precedence when the message is serialized
            msg.checksum_recv = "%02X" % (int(msg.checksum, 16) ^ 0xff)
        # The pty is non-blocking and holds little data, so long replies
        # need to wait for the host to catch up
        data = bytes(msg)
        while len(data) > 0 and not self.stop_running.is_set():
            try:
                data = data[write(self.master, data):]
            except BlockingIOError:
                self.stop_running.wait(self.loop_delay)

    def __process_gps_message(self, msg):
        logger.debug(f"CP simulator processing GPS message {msg}")
        msg = Message(parse=msg)
        if msg.type != "$PMTK" or not msg.validate():
            return
        command = msg.args[0]
        if command == "000":
            self.__reply("$PMTK", ["001", "0", "3"])
        elif command == "605":
            self.__reply("$PMTK", ["705", "AXN_2.31_3339_13101700", "5632", "PA6H", "1.0"])
        elif command == "183":
            pages = (len(self.gps_log) + 0xfff) // 0x1000
            slots = len(Locus(self.gps_log))
            if pages > 0:
                header = LocusHeader(self.gps_log)
                content, interval = header.LogContent, header.IntervalSetting
            else:
                content, interval = 127, 5
            self.__reply("$PMTK", ["LOG", str(pages), "1", "b", str(content), str(interval), "0", "0", "1",
                                   str(slots), str(100 * slots // 6432)])
            self.__reply("$PMTK", ["001", "183", "3"])
        elif command == "622":
            # Dump the log as lines of up to 24 words of 4 bytes each
            lines = [self.gps_log[i:i + 96] for i in range(0, len(self.gps_log), 96)]
            self.__reply("$PMTK", ["LOX", "0", str(len(lines))])
            for number, line in enumerate(lines):
                words = [hexlify(line[i:i + 4]).decode("ascii").upper() for i in range(0, len(line), 4)]
                self.__reply("$PMTK", ["LOX", "1", str(number)] + words)
            self.__reply("$PMTK", ["LOX", "2"])
            self.__reply("$PMTK", ["001", "622", "3"])
        elif command == "184":
            self.gps_log = b""
            self.__reply("$PMTK", ["001", "184", "3"])

    def __process_cp_message(self, msg):
        logger.debug(f"CP simulator processing message {msg}")
        msg = Message(parse=msg)
        if not msg.validate():
            self.__reply("#CMDER")
            return
        if msg.type == "#CMDOK":
            if self.ignore_cmdok:
                self.ignore_cmdok = False
            else:
                self.__reply("#CMDOK")
        elif msg.type == "#CMDSY":
            self.__reply("#CMDOK")
        elif msg.type == "#CVRRQ":
            self.__reply("#CMDOK")
            self.__reply("#CVRDQ", ["23.42"])
        elif msg.type == "#CEPSR":
            self.__reply("#CMDOK")
            self.__reply("#CEPSD", ["00"])
            self.ignore_cmdok = True
        elif msg.type == "#CEPRD":
            self.__reply("#CMDOK")
            offset = int(msg.args[0], 16)
            size = int(msg.args[1], 16)
            data = hexlify(self.c[offset:offset + size]).decode("ascii").upper()
            self.__reply("#CEPDT", [msg.args[0], msg.args[1], data])
            # Ignore next CMDOK
            self.ignore_cmdok = True
        elif msg.type == "#CEPWR":
            offset = int(msg.args[0], 16)
            size = int(msg.args[1], 16)
            data = unhexlify(msg.args[2])
            if len(data) == size:
                self.c[offset:offset + size] = data
                self.__reply("#CMDOK")
                if len(self.c) != self.type.CONFIG_SIZE:
                    logger.critical("CP simulator internal memory corruption after write")
            else:
                self.__reply("#CMDER")
        else:
            self.__reply("#CMDER")
