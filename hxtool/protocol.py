# -*- coding: utf-8 -*-

from binascii import hexlify, unhexlify
from functools import reduce
import logging
import time

from . import usb as hxusb
from . import tty as hxtty

logger = logging.getLogger(__name__)


class ProtocolError(Exception):
    pass


class Message(object):
    """
    Generic HX Message Object
    """

    UNARY_TYPES = ["#CMDOK", "#CMDER", "#CMDUN", "#CMDSM", "#CMDSY"]  # no args and no checksum

    def __init__(self, message_type=None, args=None, parse=None):

        self.type = message_type
        self.args = [] if args is None else args
        self.checksum_recv = None

        if parse is not None:
            if type(parse) is bytes:
                parse = parse.decode("ascii")
            parsed = parse.rstrip("\r\n").split("\t")
            self.type = parsed[0]
            if len(parsed) > 1:
                self.checksum_recv = parsed[-1]
            if len(parsed) > 2:
                self.args = parsed[1:-1]

    def validate(self, checksum=None):
        if checksum is None:
            checksum = self.checksum
        return checksum == self.checksum_recv

    @property
    def checksum(self):
        if self.type is None or not self.type.startswith("#") or self.type in self.UNARY_TYPES:
            return None
        check = ("\t".join([self.type] + self.args) + "\t").encode("ascii").upper()
        return "%02X" % reduce(lambda x, y: x ^ y, filter(lambda x: x != "!", check))

    def __str__(self):
        chk = self.checksum
        check = [] if chk is None else [chk]
        msg = [self.type] + self.args + check
        return "\t".join(msg).upper() + "\r\n"

    def __bytes__(self):
        return str(self).encode('ascii')

    def __repr__(self):
        return repr(bytes(self))

    def __iter__(self):
        for b in bytes(self):
            yield b

    def __eq__(self, other):
        return self.type == other.type and self.args == other.args

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

    def receive(self):
        return Message(parse=self.read_line())

    def cmd_mode(self):
        logger.debug("Sending command mode request")
        self.write(b"P")
        self.write(b"0")
        self.write(Message("ACMD:002"))

    def sync(self, flush_output=True, flush_input=True):
        if flush_output:
            self.conn.flush_output()
        if flush_input:
            self.conn.flush_input()
        self.write(Message("#CMDSY"))
        r = self.receive()  # expect #CMDOK
        if r.type != "#CMDOK":
            logger.debug("Device failed to sync, trying harder")
            self.conn.flush_output()
            time.sleep(0.1)
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
        timeout_time = time.time() + timeout
        radio_status = None
        while radio_status != "00" and time.time() < timeout_time:
            self.send("#CEPSR", ["00"])
            r = self.receive()  # expect #CMDOK
            if r.type != "#CMDOK":
                raise ProtocolError("Device did not acknowledge status request")
            r = self.receive()  # expect #CEPSD
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
        data_string = hexlify(data).decode("ascii")
        self.send("#CEPWR", ["%04X" % offset, "%02X" % len(data), data_string])
        r = self.receive()  # expect #CMDOK
        if r.type != "#CMDOK":
            raise ProtocolError("Device did not acknowledge write")
