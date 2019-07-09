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
        return str(self).encode('ascii')

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

    def is_full_stop(self):
        # These may be interspersed in comms and must be easily ignorable
        return self.type == "$PMTK" and self.args == ["LOG", "FULL_STOP"]


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
        #   - "P" if it is in NEMA mode, and
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

    def receive(self, ignore_full_stop=True):
        # Radio starts sputtering $PMTK "FULL_STOP" sentences in comms when log is full.
        # Some firmware versions seem to restart the GPS chip at unexpected moments, resulting
        # in spurious boot-up messages. These are always ignored.
        while True:
            m = Message(parse=self.read_line())
            if ignore_full_stop and m.is_full_stop():
                logger.debug("Ignoring FULL_STOP warning from radio")
                continue
            if m.type == "$PMTK" and m.args == ["010", "001"]:
                logger.debug("Ignoring GPS chipset startup message 010,001")
                continue
            if m.type == "$PMTK" and m.args == ["011", "MTKGPS"]:
                logger.debug("Ignoring GPS chipset text message 011,MTKGPS")
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
        return self.read_config_memory(0x100, 10).rstrip(b"\xff").decode("ascii")

    def check_flash_id(self, flash_id: list):
        # This function would normally use the use the low-level implementation
        # in get_flash_id, but the command it uses only works once after the
        # device is turned on.
        # Hence this function uses the more reliable method of reading the flash ID
        # directly from its offset in config memory.
        fid = self.get_flash_id()
        if fid in flash_id:
            logger.debug(f"Device reported expected flash ID {fid}")
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
                logger.debug("Waiting for radio, state=%s" % radio_status)
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

    def read_gps_log_status(self) -> dict:
        # StatusLog command to radio
        self.send("$PMTK", ["183"])

        # Radio replies with log status, but listen for full stop warning
        s = self.receive(ignore_full_stop=False)
        if s.type != "$PMTK" or len(s.args) < 2 or s.args[0] != "LOG":
            raise ProtocolError(f"Unexpected response to StatusLog from device: {s}")
        # Status might be preceeded by full log warning
        full_stop = False
        if s.args[1] == "FULL_STOP":
            full_stop = True
            s = self.receive()
        if s.type != "$PMTK" or len(s.args) != 11 or s.args[0] != "LOG":
            raise ProtocolError(f"Unexpected response to StatusLog from device: {s}")

        # Radio acknowledges StatusLog command
        r = self.receive()
        if r.type != "$PMTK" or len(r.args) != 3 or r.args != ["001", "183", "3"]:
            raise ProtocolError(f"Unexpected StatusLog acknowledgement from device: {r}")

        return {
            "pages_used": int(s.args[1]),
            "unknown_header_02": int(s.args[2]),
            "unknown_header_03": int(s.args[3], 16),
            "unknown_header_04": int(s.args[4]),
            "initial_log_interval": int(s.args[5]),
            "unknown_a": int(s.args[6]),
            "unknown_b": int(s.args[7]),
            "unknown_c": int(s.args[8]),
            "slots_used": int(s.args[9]),
            "usage_percent": int(s.args[10]),
            "full_stop": full_stop
        }

    def read_gps_log(self, progress=False) -> bytes:
        self.wait_for_ready()
        raw_log_data = b''

        # Set up log transmission
        # This is something the original log reader does under unknown circumstances,
        # but it just makes the radio behave weirdly until reboot.
        # Log transfer works well without setup on HX870.
        # self.send("$PMTK", ["251", "115200"])
        # _ = self.receive()  # Perhaps wait for some response? Doesn't always come.

        # ReadLog command to radio
        self.send("$PMTK", ["622", "1"])

        # Radio replies with log header
        r = self.receive()
        # Radio might war again about full log, ignore
        if r.type != "$PMTK" or len(r.args) != 3 or r.args[0] != "LOX" or r.args[1] != "0":
            raise ProtocolError(f"Unexpected log header from device: {r}")
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
                raise ProtocolError(f"Unexpected log line from device: {r}")
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
            raise ProtocolError(f"Unexpected ReadLog acknowledgement from device: {r}")

        return raw_log_data

    def erase_gps_log(self):
        # EraseLog command to radio
        self.send("$PMTK", ["184", "1"])

        # Radio acknowledges StatusLog command
        r = self.receive()
        if r.type != "$PMTK" or len(r.args) != 3 or r.args != ["001", "184", "3"]:
            raise ProtocolError(f"Unexpected EraseLog acknowledgement from device: {r}")
