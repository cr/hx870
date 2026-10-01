from collections import Counter
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
        # What the host has sent, by message type; for tests
        self.received = Counter()
        # Raw content of the GPS logger flash, a multiple of 4k sectors
        self.gps_log = b""
        # The GPS module's UART speed (None: out of step with the radio, deaf) and the speeds
        # it was switched to. Modelled on an HX870 and an HX891BT:
        # - the radio's firmware expects 9600;
        # - at the high speed, replies to PMTK000 cannot be relied on (never sent here),
        #   while a log dump comes through;
        # - a switch is not acknowledged, and for gps_settle seconds after it the module
        #   takes no command;
        # - switched to the speed it already has, the module goes deaf; only a switch to
        #   the high speed brings it back.
        self.gps_baudrate = 9600
        self.gps_baudrates = []
        self.gps_settle = 0.05
        self._gps_switched_at = 0.0
        # Seconds per line of a log dump at the default speed (a real dump of one 4k sector
        # takes ten seconds, and the module is busy until it is through)
        self.gps_line_delay = 0.0
        self._gps_busy_until = 0.0  # the module is in the middle of a paced dump
        self._gps_pending = []  # (due time, what to do then), in order

    def run(self):
        if self.stop_running.is_set():
            raise Exception("HXSimulator can not be restarted")
        if self.mode == "NMEA":
            self._run_nmea_mode()
        elif self.mode == "CP":
            self._run_cp_mode()
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

    def _run_nmea_mode(self):
        logger.debug("Starting simulator thread in NMEA mode")
        message = b""
        sentence = b"$GPLL,,,,\r\n"
        if self.nmea_partial:
            # The host may open the port while a sentence is on the wire
            write(self.master, sentence[3:])
        next_message_time = time() + self.nmea_delay if self.nmea_delay is not None else None
        while not self.stop_running.wait(self.loop_delay):
            for b in self._input():
                # We have input and all NMEA messages start with $
                if len(message) > 0:
                    # If we are receiving part of a message, append
                    # input to message buffer until newline received.
                    message += b
                    if message.endswith(b"\r\n"):
                        # If line is complete, process message
                        self._process_nmea_message(message)
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

    def _input(self):
        """Whatever the host has sent since the last look, one byte at a time"""
        try:
            data = read(self.master, 4096)
        except BlockingIOError:
            return
        except OSError:  # Simulator likely closed, tty died
            return
        for i in range(len(data)):
            yield data[i:i + 1]

    def _process_nmea_message(self, msg):
        logger.debug(f"NMEA simulator processing message {msg}")

    def _run_cp_mode(self):
        logger.debug("Starting simulator thread in CP mode")
        message = b""
        while not self.stop_running.wait(self.loop_delay):
            for b in self._input():
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
                            self._process_gps_message(message)
                        else:
                            self._process_cp_message(message)
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
            # What the GPS module has to say by now
            while self._gps_pending and self._gps_pending[0][0] <= time():
                self._gps_pending.pop(0)[1]()

        logger.debug("CP simulator thread finished")

    def _reply(self, message_type, args=None):
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

    def _process_gps_message(self, msg):
        logger.debug(f"CP simulator processing GPS message {msg}")
        msg = Message(parse=msg)
        if msg.type != "$PMTK" or not msg.validate():
            return
        if time() - self._gps_switched_at < self.gps_settle:
            logger.debug("CP simulator: GPS module is still switching speed, command lost")
            return
        if time() < self._gps_busy_until:
            # The module takes the command when it is through with its dump
            self._gps_pending.append((self._gps_busy_until, lambda: self._gps_command(msg)))
            return
        self._gps_command(msg)

    def _gps_command(self, msg):
        match msg.args:
            case ["251", rate]:
                self.gps_baudrates.append(int(rate))
                self._gps_switched_at = time()
                if self.gps_baudrate is None:
                    self.gps_baudrate = 115200 if int(rate) == 115200 else None
                elif int(rate) == self.gps_baudrate:
                    self.gps_baudrate = None
                else:
                    self.gps_baudrate = int(rate)
            case _ if self.gps_baudrate is None:
                pass
            case ["000"] if self.gps_baudrate != 9600:
                pass
            case ["000"]:
                self._reply("$PMTK", ["001", "0", "3"])
            case ["605"]:
                self._reply("$PMTK", ["705", "MT3333_AXN5.1.9_MODULE_STD_F0", "343F", "MC-G", "1.0"])
            case ["183"]:
                pages = (len(self.gps_log) + 0xfff) // 0x1000
                slots = len(Locus(self.gps_log))
                if pages > 0:
                    header = LocusHeader(self.gps_log)
                    content, interval = header.LogContent, header.IntervalSetting
                else:
                    content, interval = 127, 5
                self._reply("$PMTK", ["LOG", str(pages), "1", "b", str(content), str(interval), "0", "0", "1",
                                      str(slots), str(100 * slots // 6432)])
                self._reply("$PMTK", ["001", "183", "3"])
            case ["622", *_]:
                # Dump the log as lines of up to 24 words of 4 bytes each
                lines = [self.gps_log[i:i + 96] for i in range(0, len(self.gps_log), 96)]
                replies = [["LOX", "0", str(len(lines))]]
                for number, line in enumerate(lines):
                    words = [line[i:i + 4].hex().upper() for i in range(0, len(line), 4)]
                    replies.append(["LOX", "1", str(number)] + words)
                replies += [["LOX", "2"], ["001", "622", "3"]]
                delay = self.gps_line_delay if self.gps_baudrate == 9600 else 0.0
                if delay == 0.0:
                    for reply in replies:
                        self._reply("$PMTK", reply)
                else:
                    start = time()
                    for n, reply in enumerate(replies):
                        self._gps_pending.append((start + n * delay, lambda reply=reply: self._reply("$PMTK", reply)))
                    self._gps_busy_until = start + len(replies) * delay
            case ["184", *_]:
                self.gps_log = b""
                self._reply("$PMTK", ["001", "184", "3"])

    def _process_cp_message(self, msg):
        logger.debug(f"CP simulator processing message {msg}")
        msg = Message(parse=msg)
        if not msg.validate():
            self._reply("#CMDER")
            return
        self.received[msg.type] += 1
        match msg.type, msg.args:
            case "#CMDOK", []:
                # The host's acknowledgement of a data reply gets no answer
                if self.ignore_cmdok:
                    self.ignore_cmdok = False
                else:
                    self._reply("#CMDOK")
            case "#CMDSY", []:
                self._reply("#CMDOK")
            case "#CVRRQ", []:
                self._reply("#CMDOK")
                self._reply("#CVRDQ", ["23.42"])
            case "#CEPSR", _:
                self._reply("#CMDOK")
                self._reply("#CEPSD", ["00"])
                self.ignore_cmdok = True
            case "#CEPRD", [offset, size]:
                self._reply("#CMDOK")
                start, length = int(offset, 16), int(size, 16)
                self._reply("#CEPDT", [offset, size, self.c[start:start + length].hex().upper()])
                self.ignore_cmdok = True
            case "#CEPWR", [offset, size, payload]:
                start, length, data = int(offset, 16), int(size, 16), bytes.fromhex(payload)
                if len(data) == length:
                    self.c[start:start + length] = data
                    self._reply("#CMDOK")
                    if len(self.c) != self.type.CONFIG_SIZE:
                        logger.critical("CP simulator internal memory corruption after write")
                else:
                    self._reply("#CMDER")
            case _:
                self._reply("#CMDER")
