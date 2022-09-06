# -*- coding: utf-8 -*-

from binascii import hexlify, unhexlify
from functools import reduce
from logging import getLogger
from time import time, sleep
from typing import List

from . import tty as hxtty

logger = getLogger(__name__)


class ProtocolError(Exception):
    pass


class Message(object):
    """
    Generic HX Message Object
    """

    UNARY_TYPES = ["#CMDOK", "#CMDER", "#CMDUN", "#CMDSM", "#CMDSY"]  # no args and no checksum

    def __init__(self, message_type: str = None, args: List[str] = None, parse: bytes or str = None):

        self.type = message_type
        self.args = args or []
        self.checksum_recv = None

        if parse is not None:
            if type(parse) is bytes:
                parse = parse.decode("ascii")
            if parse.startswith("#"):
                # CP mode command message
                parsed = parse.rstrip("\r\n").split("\t")
                self.type = parsed[0]
                if len(parsed) > 1:
                    self.checksum_recv = parsed[-1]
                if len(parsed) > 2:
                    self.args = parsed[1:-1]
            elif parse.startswith("$"):
                # NMEA sentence
                parsed = parse.rstrip("\r\n")
                self.type = parsed[:5]
                args, self.checksum_recv = parsed[5:].split("*")
                self.args = args.split(",")
            else:
                raise ProtocolError(f"Invalid message `{parse}`")

    def validate(self, checksum=None):
        if checksum is None:
            checksum = self.checksum
        if self.checksum_recv is None:
            return True
        return checksum == self.checksum_recv

    @property
    def checksum(self):
        if self.type in self.UNARY_TYPES:
            return None
        elif self.type.startswith("#"):
            check = ("\t".join([self.type] + self.args) + "\t").encode("ascii")
            return "%02X" % reduce(lambda x, y: x ^ y, filter(lambda x: x != "!", check))
        elif self.type.startswith("$"):
            check = (self.type[1:] + ",".join(self.args)).encode("ascii")
            return "%02X" % reduce(lambda x, y: x ^ y, filter(lambda x: x != "!", check))
        else:
            return None

    def __str_no_check(self):
        if self.type.startswith("#"):
            return "\t".join([self.type] + self.args)
        elif self.type.startswith("$"):
            return self.type + ",".join(self.args)
        else:
            raise ProtocolError(f"Invalid message type `{self.type}`")

    def __str__(self):
        if self.type.startswith("#"):
            if self.type in self.UNARY_TYPES:
                msg = [self.type]
            else:
                # Received checksum has precedence over calculated
                check = self.checksum_recv or self.checksum
                msg = [self.type] + self.args + [check]
            return "\t".join(msg) + "\r\n"
        elif self.type.startswith("$"):
            # Received checksum has precedence over calculated
            check = self.checksum_recv or self.checksum
            return (self.type + ",".join(self.args) + "*" + check) + "\r\n"

    def __bytes__(self):
        return str(self).encode("ascii")

    def __repr__(self):
        return repr(bytes(self))

    def __iter__(self):
        for b in bytes(self):
            yield b

    def __eq__(self, other):
        if str(self) != str(other):
            return False
        else:
            if self.checksum_recv == other.checksum_recv:
                return True
            else:
                if self.checksum_recv is None or other.checksum_recv is None:
                    return True
                else:
                    return False

    @classmethod
    def parse(cls, messages):
        if type(messages) is bytes:
            messages = messages.decode('ascii')
        for message in messages.split("\r\n"):
            if len(message) > 0:
                yield cls(parse=message)


class GenericHXProtocol(object):

    def __init__(self, tty=None):
        self.conn = None
        self.connected = False
        self.hx_hardware = False
        self.cp_mode = False
        self.nmea_mode = False
        self.__connect(tty)

    def __connect(self, tty):
        self.conn = hxtty.GenericHXTTY(tty)
        self.__detect_device_mode()
        self.connected = True
        if self.hx_hardware:
            logger.debug("Device responds like HX style hardware")
        else:
            logger.debug("Device behaves not like HX style hardware")
        if self.cp_mode:
            logger.debug("Device is in CP mode")
            logger.debug("Switching to command mode")
            self.cmd_mode()
            self.sync()
        if self.nmea_mode:
            logger.debug("Device is in NMEA mode")

    def __detect_device_mode(self):

        # In NMEA mode, an HX device replies with "P" to "P", and with nothing to "?"
        # In CP mode, an HX device replies with "@" to "?", and with nothing to "P"
        # Hence an HX device will reply to "?P" with
        #   - "P" if it is in NMEA mode, and
        #   - "?" if it is in CP mode

        self.conn.flush_input()
        self.conn.flush_output()

        self.conn.write(b"P?")
        try:
            r = self.conn.read(1)
        except TimeoutError:
            logger.warning("No response, so probably not talking to HX hardware")
            self.hx_hardware = False
            self.nmea_mode = False
            self.cp_mode = False
            return

        if r == b"P" or r == b"$":
            # There's sometimes a race condition where the firmware sends
            # a NMEA message before it replies with "P", so flush.
            if r == b"$":
                logger.debug("Probable race condition with NMEA message detected, assuming NMEA mode")
                self.conn.flush_input()
            logger.debug("Response like HX hardware in NMEA mode")
            self.hx_hardware = True
            self.nmea_mode = True
            self.cp_mode = False

            return

        if r == b"@":
            logger.debug("Response like HX hardware in CP mode")
            self.hx_hardware = True
            self.nmea_mode = False
            self.cp_mode = True
            return

    def available(self):
        return self.conn.available()

    def write(self, data):
        return self.conn.write(data)

    def read(self, *args, **kwargs):
        return self.conn.read(*args, **kwargs)

    def read_all(self, *args, **kwargs):
        return self.conn.read_all(*args, **kwargs)

    def read_line(self, *args, **kwargs):
        return self.conn.read_line(*args, **kwargs)

    def send(self, message_type, args=None):
        self.write(Message(message_type, args))

    def receive(self, ignore_full_stop=True, ignore_text_messages=True, ignore_system_messages=True):
        # GPS module starts sputtering "FULL_STOP" log messages in comms when log is full.
        # Some firmware versions seem to restart the GPS module at unexpected moments, resulting
        # in spurious system and text messages. These are also ignored per default.
        while True:
            m = Message(parse=self.read_line())
            if ignore_full_stop and m.type == "$PMTK" and m.args == ["LOG", "FULL_STOP"]:
                logger.debug(f"Ignoring GPS module FULL_STOP warning {str(m).strip()}")
                continue
            if ignore_system_messages and m.type == "$PMTK" and m.args[0] == "010":
                logger.debug(f"Ignoring GPS module system message {str(m).strip()}")
                continue
            if ignore_text_messages and m.type == "$PMTK" and m.args[0] == "011":
                logger.debug(f"Ignoring GPS module text message {str(m).strip()}")
                continue
            return m

    def cmd_mode(self):
        logger.debug("Sending command mode request")
        # The HX870 doesn't seem to care. It responds to #CMDSY without this.
        self.write(b"0ACMD:002\r\n")

    def sync(self, flush_output=False, flush_input=True):
        if flush_output:
            self.conn.flush_output()
        if flush_input:
            self.conn.flush_input()
        self.write(Message("#CMDSY"))
        r = self.receive()  # expect #CMDOK
        if r.type != "#CMDOK":
            logger.debug("Device failed to sync, trying harder")
            self.conn.flush_output()
            sleep(0.1)
            self.conn.flush_input()
            self.write(Message("#CMDSY"))
            r = self.receive()  # expect #CMDOK
            if r.type != "#CMDOK":
                logger.debug("Device failed to sync, giving up")
                raise ProtocolError("Device failed to sync")

    def get_firmware_version(self):
        self.send("#CVRRQ")
        r = self.receive()  # expect #CMDOK
        if r.type != "#CMDOK":
            raise ProtocolError("Device did not acknowledge firmware version request")
        cvrdq = self.receive()  # expect #CVRDQ
        if cvrdq.type != "#CVRDQ":
            raise ProtocolError("Device did not reply with firmware version")
        self.send("#CMDOK")  # acknowledge reply
        r = self.receive()  # expect #CMDOK
        if r.type != "#CMDOK":
            raise ProtocolError("Device did not acknowledge firmware version ack")
        return cvrdq.args[0]

    def get_flash_id(self):
        # For some reason my radio sometimes responds with #CMDER. It only seems to work the
        # first time after the radio is turned on.
        # The official flasher put the USB port into SUSPEND mode before sending the command,
        # so that requires further investigation.

        # # It normally goes like this
        # self.send("#CMDNR", ["STANDARD HORIZON"])
        # r = self.receive()  # expect #CMDOK
        # if r.type != "#CMDOK":
        #     raise ProtocolError("Device did not acknowledge flash ID request")
        # cmdnd = self.receive()  # expect #CMDND
        # if cmdnd.type != "#CMDND":
        #     raise ProtocolError("Device did not reply with flash ID")
        # cmdnd = self.receive()  # expect #CMDND
        # if cmdnd.type != "#CMDND":
        #     raise ProtocolError("Device did not reply with flash ID twice")
        # self.send("#CFLID", [cmdnd.args[0]])
        # cmdok = self.receive()  # expect #CMDOK or #CMDER
        # if cmdok.type != "#CMDOK":
        #     raise ProtocolError("Device did not acknowledge flash CFLID command")
        # cflsd = self.receive()  # expect #CFLSD
        # if cflsd.type != "#CFLSD":  # or cflsd.args[0] != "00":
        #     raise ProtocolError("Device did not acknowledge with CFLSD")
        # cflsd = self.receive()  # expect #CFLSD
        # if cflsd.type != "#CFLSD":  # or cflsd.args[0] != "00":
        #     raise ProtocolError("Device did not acknowledge with CFLSD twice")
        # if cflsd.args[0] != "00":
        #     raise ProtocolError("Device did not acknowledge reported flash ID with status 00")
        # self.sync()
        # return cmdnd.args[0]

        # But this implements the check via a direct config flash read that works nonetheless:
        return self.read_config_memory(0x100, 10).rstrip(b"\x00\xff").decode("ascii")

    def check_flash_id(self, flash_id: list):
        # This function would normally use the use the low-level implementation
        # in get_flash_id, but the command it uses only works once after the
        # device is turned on.
        # Hence this function uses the more reliable method of reading the flash ID
        # directly from its offset in config memory.
        fid = self.get_flash_id()
        if fid in flash_id:
            logger.debug("Device reported expected flash ID %s", fid)
            return True
        else:
            logger.warning(f"Flash ID mismatch. Device reported {fid}, expected {flash_id}")
            return False

    def wait_for_ready(self, timeout=1):
        timeout_time = time() + timeout
        radio_status = None
        while radio_status != "00" and time() < timeout_time:
            self.send("#CEPSR", ["00"])
            r = self.receive()  # expect #CMDOK
            if r.type != "#CMDOK":
                raise ProtocolError("Device did not acknowledge status request")
            r = self.receive()  # expect #CEPSD
            if r.type != "#CEPSD":
                raise ProtocolError("Device did not return status")
            radio_status = r.args[0]
            if radio_status != "00":
                logger.debug("Waiting for radio, state=%s", radio_status)
            self.send("#CMDOK")
        if radio_status != "00":
            raise TimeoutError("Device not ready")

    def read_config_memory(self, offset, length):
        self.wait_for_ready()
        self.send("#CEPRD", ["%04X" % offset, "%02X" % length])
        r = self.receive()  # expect #CMDOK
        if r.type != "#CMDOK":
            raise ProtocolError("Device did not acknowledge read")
        d = self.receive()  # expect #CEPDT
        if d.type != "#CEPDT":
            raise ProtocolError("Device did not reply with data")
        self.send("#CMDOK")
        return unhexlify(d.args[2])

    def write_config_memory(self, offset, data):
        self.wait_for_ready()
        data_string = hexlify(data).decode("ascii").upper()
        self.send("#CEPWR", ["%04X" % offset, "%02X" % len(data), data_string])
        r = self.receive()  # expect #CMDOK
        if r.type != "#CMDOK":
            raise ProtocolError("Device did not acknowledge write")


class MediaTekProtocol(object):

    def __init__(self, proto: GenericHXProtocol):
        self.p = proto

    def send(self, *args, **kwargs):
        return self.p.send(*args, **kwargs)

    def receive(self, *args, **kwargs):
        return self.p.receive(*args, **kwargs)

    def sync(self, timeout=5):
        timeout_time = time() + timeout
        while time() < timeout_time:
            self.p.send("$PMTK", ["000"])
            while time() < timeout_time:
                try:
                    r = self.p.receive()
                except TimeoutError:
                    break
                if r.type == "$PMTK" and r.args == ["001", "0", "3"]:
                    return
        raise TimeoutError("GPS module won't sync. Please reboot the handset")

    def set_baudrate(self, rate: int):
        # Set up log transmission baudrate
        #
        # This is a tricky one:
        # * If you set it to 9600, the GPS module normally acknowledges the command and life goes on,
        #   but slowly.
        # * If you set it to 115200, the module sometimes responds with a non-standard system message "003",
        #   and transfer continues at high speed. But it might also just acknowledge the wrong command 225 instead.
        #   It might also stop responding completely, but behavior is highly unpredictable.
        # * If you set it to any other value, the module stops responding completely until you remove the battery.
        #
        # self.send("$PMTK", ["251", "115200"])
        # r = self.receive()
        # if r.type != "$PMTK" or r.args != ["001", "225", "3"]:
        #     raise ProtocolError(f"Unexpected response after setting output baudrate: {r}")
        #
        # Massive syncing before and after setting baudrate works most reliably, but it also fails intermittently,
        # sometimes making the GPS module hang until reboot.

        self.sync()
        self.p.send("$PMTK", ["251", str(rate)])
        try:
            _ = self.receive()  # may or may not ACK
        except TimeoutError:
            pass
        self.sync()
        self.sync()

    def read_log_status(self) -> dict:

        # StatusLog command to radio
        self.send("$PMTK", ["183"])

        # Radio replies with log status, but listen for full stop warning
        s = self.receive(ignore_full_stop=False)
        if s.type != "$PMTK" or len(s.args) < 2 or s.args[0] != "LOG":
            raise ProtocolError(f"Unexpected response to StatusLog from device: {str(s).strip()}")
        # Status might be preceeded by full log warning
        full_stop = False
        if s.args[1] == "FULL_STOP":
            full_stop = True
            s = self.receive()
        if s.type != "$PMTK" or len(s.args) != 11 or s.args[0] != "LOG":
            raise ProtocolError(f"Unexpected response to StatusLog from device: {str(s).strip()}")

        # Radio acknowledges StatusLog command
        r = self.receive()
        if r.type != "$PMTK" or len(r.args) != 3 or r.args != ["001", "183", "3"]:
            raise ProtocolError(f"Unexpected StatusLog acknowledgement from device: {str(r).strip()}")

        return {
            "pages_used": int(s.args[1]),  # aka Serial#
            "logging_type": int(s.args[2]),  # 0: overlap, 1: full stop
            "logging_mode": int(s.args[3], 16),  # 0x8: interval logging
            "log_content": int(s.args[4]),  # bitmap describing available fields per slot
            "interval_setting": int(s.args[5]),  # seconds, if interval mode
            "distance_setting": int(s.args[6]),  # if distance mode, else 0
            "speed_setting": int(s.args[7]),  # if speed mode, else 0
            "logging_enabled": int(s.args[8]),  # 0: enabled, 1: disabled
            "slots_used": int(s.args[9]),
            "usage_percent": int(s.args[10]),
            "full_stop": full_stop
        }

    def read_log(self, progress=False) -> bytes:
        raw_log_data = b''
        self.sync()

        # The radio behaves so erratically that the best option for now is not setting the baudrate at all
        # and sticking with the slow, but reliable, default 9600.
        # self.set_baudrate(115200)

        # ReadLog command to radio
        self.send("$PMTK", ["622", "1"])

        # Radio replies with log header
        r = self.receive()
        # Radio might war again about full log, ignore
        if r.type != "$PMTK" or len(r.args) != 3 or r.args[0] != "LOX" or r.args[1] != "0":
            raise ProtocolError(f"Unexpected log header from device: {str(r).strip()}")
        number_of_lines = int(r.args[2])
        received_line_numbers = []

        # What follows is a flash memory dump of the log data
        # LOX messages with first arg "1" indicate a log dump line
        # LOX message with first arg "2" indicates end of log
        last_progress_report = time()
        if progress:
            logger.info(f"0 / {number_of_lines} blocks (0%)")
        while True:
            r = self.receive()
            if r.type != "$PMTK" or len(r.args) < 2 or r.args[0] != "LOX" or r.args[1] not in ("1", "2"):
                raise ProtocolError(f"Unexpected log line from device: {str(r).strip()}")
            if len(r.args) == 2 and r.args[1] == "2":
                # Received log footer
                break
            # Received log line with raw data
            received_line_numbers.append(int(r.args[2]))
            raw_waypoint_data = r.args[3:]
            for word in raw_waypoint_data:
                raw_log_data += unhexlify(word)
            if progress and time() - last_progress_report > 4:
                percent_done = int(100.0 * len(received_line_numbers) / number_of_lines)
                logger.info(f"{len(received_line_numbers)} / {number_of_lines} blocks ({percent_done}%)")
                last_progress_report = time()

        if progress:
            logger.info(f"{number_of_lines} / {number_of_lines} blocks (100%)")

        # Did we receive the log in order and completely?
        if received_line_numbers != list(range(number_of_lines)):
            raise ProtocolError(f"Unexpected log dump sequence from device")

        # Radio acknowledges ReadLog command
        r = self.receive()
        if r.type != "$PMTK" or len(r.args) != 3 or r.args != ["001", "622", "3"]:
            raise ProtocolError(f"Unexpected ReadLog acknowledgement from device: {str(r).strip()}")

        # If you don't switch back to 9600bd, the GPS module sometimes behaves strangely until reboot.
        # Sometimes, switching back will make the module hang until reboot.
        #
        # self.mtk_sync()
        # self.send("$PMTK", ["251", "9600"])
        # try:
        #     r = self.receive()  # may or may not ACK
        # except TimeoutError:
        #     continue
        # self.mtk_sync()
        # self.mtk_sync()

        return raw_log_data

    def erase_log(self):
        # EraseLog command to radio
        self.send("$PMTK", ["184", "1"])

        # Radio acknowledges StatusLog command
        r = self.receive()
        if r.type != "$PMTK" or len(r.args) != 3 or r.args != ["001", "184", "3"]:
            raise ProtocolError(f"Unexpected EraseLog acknowledgement from device: {str(r).strip()}")
