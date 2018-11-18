# -*- coding: utf-8 -*-

from binascii import hexlify, unhexlify
from functools import reduce
import logging
import time

from . import usb as hxusb
from . import tty as hxtty
from .memory import unpack_waypoint

logger = logging.getLogger(__name__)


class ProtocolError(Exception):
    pass


class Message(object):
    """
    HX870 Message Object
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


class HX870(object):

    def __init__(self, tty=None):
        self.conn = None
        self.cp_mode = False
        self.connect(tty)

    def connect(self, tty=None):
        if tty is None:
            self.conn = hxusb.HX870USB()
        else:
            self.conn = hxtty.HX870TTY(tty)

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
        self.write(b"P")
        self.write(b"0")
        self.write(Message("ACMD:002"))

    def sync(self, flush_output=False, flush_input=True):
        if flush_output:
            self.conn.flush_output()
        if flush_input:
            self.conn.flush_input()
        self.write(Message("#CMDSY"))
        r = self.receive()  # expect #CMDOK
        if r.type != "#CMDOK":
            logger.debug("Radio failed to sync, trying harder")
            self.conn.flush_output()
            time.sleep(0.1)
            self.conn.flush_input()
            self.write(Message("#CMDSY"))
            r = self.receive()  # expect #CMDOK
            if r.type != "#CMDOK":
                logger.debug("Radio failed to sync, giving up")
                raise ProtocolError("Radio failed to sync")

    def init(self):
        self.cmd_mode()
        try:
            self.sync()
            self.cp_mode = True
        except ProtocolError:
            self.cp_mode = False

    def get_firmware_version(self):
        self.send("#CVRRQ")
        r = self.receive()  # expect #CMDOK
        if r.type != "#CMDOK":
            raise ProtocolError("Radio did not acknowledge firmware version request")
        cvrdq = self.receive()  # expect #CVRDQ
        if cvrdq.type != "#CVRDQ":
            raise ProtocolError("Radio did not reply with firmware version")
        self.send("#CMDOK")
        r = self.receive()  # expect #CMDOK
        if r.type != "#CMDOK":
            raise ProtocolError("Radio did not acknowledge firmware version ack")
        return cvrdq.args[0]

    def get_flash_id(self):
        self.send("#CMDNR", ["STANDARD HORIZON"])
        r = self.receive()  # expect #CMDOK
        if r.type != "#CMDOK":
            raise ProtocolError("Radio did not acknowledge flash ID request")
        cmdnd = self.receive()  # expect #CMDND
        if cmdnd.type != "#CMDND":
            raise ProtocolError("Radio did not reply with flash ID")

    def wait_for_ready(self, timeout=1):
        timeout_time = time.time() + timeout
        radio_status = None
        while radio_status != "00" and time.time() < timeout_time:
            self.send("#CEPSR", ["00"])
            r = self.receive()  # expect #CMDOK
            if r.type != "#CMDOK":
                raise ProtocolError("Radio did not acknowledge status request")
            r = self.receive()  # expect #CEPSD
            radio_status = r.args[0]
            if radio_status != "00":
                logger.debug("Waiting for radio, state=%s" % radio_status)
            self.send("#CMDOK")
        if radio_status != "00":
            raise TimeoutError("Radio not ready")

    def read_config_memory(self, offset, length):
        self.wait_for_ready()
        self.send("#CEPRD", ["%04X" % offset, "%02X" % length])
        r = self.receive()  # expect #CMDOK
        if r.type != "#CMDOK":
            raise ProtocolError("Radio did not acknowledge read")
        d = self.receive()  # expect #CEPDT
        if d.type != "#CEPDT":
            raise ProtocolError("Radio did not reply with data")
        self.send("#CMDOK")
        return unhexlify(d.args[2])

    def config_read(self):
        config_data = b''
        for address in range(0x0000, 0x8000, 0x40):
            config_data += self.read_config_memory(address, 0x40)
        return config_data

    def waypoints_read(self):
        wp_data = b''
        for address in range(0x4300, 0x5c00, 0x40):
            wp_data += self.read_config_memory(address, 0x40)
        wp_list = []
        for wp_id in range(1, 201):
            offset = (wp_id - 1) * 32
            wp = unpack_waypoint(wp_data[offset:offset+32])
            if wp is not None:
                wp_list.append(wp)
        return wp_list

    def write_config_memory(self, offset, data):
        self.wait_for_ready()
        data_string = hexlify(data).decode("ascii")
        self.send("#CEPWR", ["%04X" % offset, "%02X" % len(data), data_string])
        r = self.receive()  # expect #CMDOK
        if r.type != "#CMDOK":
            raise ProtocolError("Radio did not acknowledge write")

    def config_write(self, data, check_region=True):
        if len(data) != 0x8000:
            raise ProtocolError("Unexpected config data size")
        magic = self.read_config_memory(0x0000, 2)
        magic_end = self.read_config_memory(0x7ffe, 2)
        if magic != data[:2] or magic_end != data[-2:]:
            raise ProtocolError("Unexpected config magic in device")
        region = self.read_config_memory(0x010f, 1)
        region_is_us = region == b'0xff'
        data_is_us = data[0x010f] == b'0xff'
        if region_is_us != data_is_us:
            if check_region:
                logger.error("Region mismatch")
                raise ProtocolError("Region mismatch")
            logger.warning("Ignoring region mismatch. Flashing anyway")

        self.write_config_memory(0x0002, data[0x0002:0x000f])
        self.write_config_memory(0x0010, data[0x0010:0x0040])
        for offset in range(0x0040, 0x7fc0, 0x40):
            self.write_config_memory(offset, data[offset:offset+0x40])
        self.write_config_memory(0x7fc0, data[0x7fc0:0x7ffe])

    def read_mmsi(self):
        data = hexlify(self.read_config_memory(0x00b0, 6)).decode().upper()
        mmsi = data[0:10]
        status = data[10:12]
        return mmsi, status

    def write_mmsi(self, mmsi: str=None, status: str=None):
        if mmsi is None:
            mmsi = "FFFFFFFFFF"
            if status is None:
                status = "00"
        else:
            if not mmsi.isdecimal():
                raise ProtocolError("Invalid MMSI format")
            if status is None:
                status = "02"
        if len(mmsi) == 9:
            mmsi += "0"
        if len(mmsi) != 10:
            raise ProtocolError("Invalid MMSI length")
        if status.upper() not in ["00", "01", "02", "FF"]:
            raise ProtocolError("Invalid MMSI status")
        data = unhexlify(mmsi + status)
        self.write_config_memory(0x00b0, data)

    def read_atis(self):
        data = hexlify(self.read_config_memory(0x00b6, 6)).decode().upper()
        atis = data[0:10]
        status = data[10:12]
        return atis, status

    def write_atis(self, atis: str=None, status: str=None):
        if atis is None:
            atis = "FFFFFFFFFF"
            if status is None:
                status = "00"
        else:
            if not atis[0] == "9" or not atis.isdecimal():
                raise ProtocolError("Invalid ATIS format")
            if status is None:
                status = "01"
        if len(atis) != 10:
            raise ProtocolError("Invalid ATIS length")
        if status.upper() not in ["00", "01", "02", "FF"]:
            raise ProtocolError("Invalid ATIS status")
        data = unhexlify(atis + status)
        self.write_config_memory(0x00b6, data)
