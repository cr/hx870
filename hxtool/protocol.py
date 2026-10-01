from functools import reduce
from logging import getLogger
from time import time, sleep

from . import tty as hxtty
from .progress import Progress

logger = getLogger(__name__)


class ProtocolError(Exception):
    pass


class InternalError(Exception):
    pass


class Message:
    """
    Generic HX Message Object
    """

    UNARY_TYPES = ["#CMDOK", "#CMDER", "#CMDUN", "#CMDSM", "#CMDSY"]  # no args and no checksum

    def __init__(self, message_type: str | None = None, args: list[str] | None = None,
                 parse: bytes | str | None = None):

        self.type = message_type
        self.args = args or []
        self.checksum_recv = None

        if parse is not None:
            if type(parse) is bytes:
                try:
                    parse = parse.decode("ascii")
                except UnicodeDecodeError as e:
                    raise ProtocolError(f"Invalid message `{parse}`") from e
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
                if parsed.count("*") != 1:
                    raise ProtocolError(f"Invalid message `{parse}`")
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
            return f"{reduce(lambda x, y: x ^ y, check):02X}"
        elif self.type.startswith("$"):
            check = (self.type[1:] + ",".join(self.args)).encode("ascii")
            return f"{reduce(lambda x, y: x ^ y, check):02X}"
        else:
            return None

    def _str_no_check(self):
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
        yield from bytes(self)

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


def _is_text(data: bytes) -> bool:
    """Printable ASCII lines, as a partial NMEA sentence looks like"""
    return len(data) > 0 and all(0x20 <= b < 0x7f or b in b"\r\n" for b in data)


class GenericHXProtocol:

    # Line settings of the vendor tool, from USB captures of its sessions: it sets
    # 115200 baud and never asserts DTR. The rate is nominal on a USB CDC link, but
    # the radio has none until the host sets one.
    baudrate = 115200
    control_lines = False

    # The vendor tool asks for the radio's status before every read and write. The USB
    # radios answer reads correctly without that (HX870 firmware 02.04 and HX891BT
    # firmware 1.00, whole dumps compared), at twice the speed. A write and the first
    # read after one still wait for the radio to be ready.
    poll_before_read = False
    _written = False  # a write happened since the last status poll

    def __init__(self, tty=None, identified=False):
        """
        identified: the port is known to belong to an HX radio (USB metadata, or the
        user forced the model), so silence means NMEA mode with a quiet GPS rather
        than unknown hardware
        """
        self.conn = None
        self.connected = False
        self.identified = identified
        self.hx_hardware = False
        self.cp_mode = False
        self.nmea_mode = False
        self.nmea_output_seen = False
        self._connect(tty)

    def _connect(self, tty):
        self.conn = hxtty.GenericHXTTY(tty, baudrate=self.baudrate, control_lines=self.control_lines)
        self._detect_device_mode()
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

    def _detect_device_mode(self):

        # In CP mode, an HX device replies with "@" to "?" and ignores "P".
        # In NMEA mode, some firmware replies with "P" to "P" (seen on HX891BT),
        # some ignores it (seen on HX870). Either way the GPS module sends NMEA
        # sentences, unless GPS output is disabled or the module is asleep
        # (power save). Whatever arrives may start in the middle of a sentence,
        # so everything received within the timeout is classified as a whole.

        self.conn.flush_input(expected=True)  # old NMEA output, if any
        self.conn.flush_output()

        self.conn.write(b"P?")
        received = b""
        sentence_seen = None
        deadline = time() + self.conn.default_timeout
        while time() < deadline:
            try:
                received += self.conn.read(1)
            except TimeoutError:
                break
            if b"@" in received:
                break
            if b"$" in received and sentence_seen is None:
                # GPS output. In NMEA mode that is all there is; in CP mode the module may be
                # streaming too, and the answer to "?" is still to come.
                sentence_seen = time()
                deadline = min(deadline, sentence_seen + 0.5)

        if b"@" in received:
            logger.debug("Response like HX hardware in CP mode")
            self.hx_hardware, self.cp_mode, self.nmea_mode = True, True, False
        elif received == b"P":
            logger.debug("Response like HX hardware in NMEA mode, no GPS output yet")
            self.hx_hardware, self.cp_mode, self.nmea_mode = True, False, True
        elif b"$" in received or _is_text(received):
            logger.debug("NMEA output like HX hardware in NMEA mode")
            self.hx_hardware, self.cp_mode, self.nmea_mode = True, False, True
            self.nmea_output_seen = True
            self.conn.flush_input(expected=True)
        elif not received and self.identified:
            logger.info("No response to handshake, assuming NMEA mode with GPS output off or asleep")
            self.hx_hardware, self.cp_mode, self.nmea_mode = True, False, True
        elif not received:
            logger.warning("No response, so probably not talking to HX hardware")
        else:
            logger.warning(f"Unexpected response {received!r}, so probably not talking to HX hardware")

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

    def receive(self, ignore_full_stop=True, ignore_text_messages=True, ignore_system_messages=True, nmea=False):
        # GPS module starts sputtering "FULL_STOP" log messages in comms when log is full.
        # Some firmware versions seem to restart the GPS module at unexpected moments, resulting
        # in spurious system and text messages. These are also ignored per default.
        # The GPS module's output arrives on the same line as the replies to commands. Unless
        # a GPS sentence is what the caller waits for (nmea), sentences are skipped, as is
        # the tail of a sentence that was already under way when the port was opened.
        while True:
            line = self.read_line()
            if not line.startswith(b"#") and (not nmea or not line.startswith(b"$")) \
                    and (line.startswith(b"$") or b"*" in line):
                logger.debug(f"Skipping GPS output {line!r}")
                continue
            m = Message(parse=line)
            if not m.validate():
                raise ProtocolError(f"Checksum mismatch in message from device: {str(m).strip()}")
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

    # The flash ID could be requested with #CMDNR / #CFLID, but that only works once
    # after the radio is turned on (the official flasher suspends the USB port first),
    # so the flash ID is read from config memory instead, see GenericHXConfig.flash_id()

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

    # The address and length fields of config memory transfers are two and one byte wide.
    # That is the wire format's limit; the radios' own is lower: an HX870 returns garbled
    # data for reads longer than 0x40 bytes (its reply buffer wraps), which is why the
    # models' CHUNK_SIZE, the vendor tool's transfer size, is what transfers should use.
    MAX_TRANSFER = 0xff

    def _check_transfer(self, offset, length):
        if not 0 <= offset <= 0xffff:
            raise ProtocolError(f"Config memory offset 0x{offset:x} out of range")
        if not 1 <= length <= self.MAX_TRANSFER:
            raise ProtocolError(f"Config memory transfer length {length} out of range (1-{self.MAX_TRANSFER})")

    def read_config_memory(self, offset, length):
        self._check_transfer(offset, length)
        if self.poll_before_read or self._written:
            self.wait_for_ready()
            self._written = False
        self.send("#CEPRD", [f"{offset:04X}", f"{length:02X}"])
        r = self.receive()  # expect #CMDOK
        if r.type != "#CMDOK":
            raise ProtocolError("Device did not acknowledge read")
        d = self.receive()  # expect #CEPDT
        if d.type != "#CEPDT":
            raise ProtocolError("Device did not reply with data")
        self.send("#CMDOK")
        try:
            reply_offset, reply_length, data = int(d.args[0], 16), int(d.args[1], 16), bytes.fromhex(d.args[2])
        except (IndexError, ValueError) as e:
            raise ProtocolError(f"Unexpected data reply format from device: {str(d).strip()}") from e
        if reply_offset != offset or reply_length != length or len(data) != length:
            raise ProtocolError(f"Unexpected data reply from device: requested {length} bytes at 0x{offset:04x}, "
                                f"got {len(data)} bytes labeled as {reply_length} bytes at 0x{reply_offset:04x}")
        return data

    def write_config_memory(self, offset, data):
        self._check_transfer(offset, len(data))
        self.wait_for_ready()
        self._written = True
        data_string = data.hex().upper()
        self.send("#CEPWR", [f"{offset:04X}", f"{len(data):02X}", data_string])
        r = self.receive()  # expect #CMDOK
        if r.type != "#CMDOK":
            raise ProtocolError("Device did not acknowledge write")


class MediaTekProtocol:

    def __init__(self, proto: GenericHXProtocol):
        self.p = proto

    def send(self, *args, **kwargs):
        return self.p.send(*args, **kwargs)

    def receive(self, *args, **kwargs):
        return self.p.receive(*args, nmea=True, **kwargs)

    def sync(self, timeout=5):
        timeout_time = time() + timeout
        while time() < timeout_time:
            self.p.send("$PMTK", ["000"])
            while time() < timeout_time:
                try:
                    r = self.receive()
                except TimeoutError:
                    break
                if r.type == "$PMTK" and r.args == ["001", "0", "3"]:
                    return
        raise TimeoutError("GPS module won't sync. Please reboot the handset")

    # The GPS module talks to the radio at 9600 baud, which is what the radio's firmware
    # expects outside of a log transfer, and what limits a transfer to about 960 characters
    # per second. At 115200 baud the log arrives five to six times faster.
    #
    # What the module needs, measured on an HX870 and an HX891BT with the port opened as
    # the vendor software does (115200 baud line coding, DTR low):
    # - A switch is not acknowledged. For about a second after it the module takes no
    #   command, and a command sent in that time can leave it deaf.
    # - At the high speed, replies to short commands like the sync cannot be relied on;
    #   a log dump comes through complete.
    # - Switched to the speed it already has, the module goes deaf. Switching to the high
    #   speed and back brings a deaf module back.
    DEFAULT_BAUDRATE = 9600
    FAST_BAUDRATE = 115200
    SWITCH_SETTLE = 1.5  # seconds to leave the module alone after a switch

    def set_baudrate(self, rate: int):
        """Switch the GPS module's speed. Only call this when its current speed is the other one."""
        self.send("$PMTK", ["251", str(rate)])
        sleep(self.SWITCH_SETTLE)
        self.p.conn.flush_input(expected=True)  # the module may send a system message

    def ensure_ready(self):
        """
        Make sure the GPS module answers at its default speed. It does not when an earlier
        transfer was cut short at the high speed, or when it was left deaf. A module that is
        merely busy, sending the rest of a log dump nobody reads any more, is waited for.
        """
        if self._sync_when_idle():
            return
        logger.warning("GPS module does not answer, restoring its speed")
        self.set_baudrate(self.DEFAULT_BAUDRATE)  # from the high speed
        if self._sync_when_idle():
            return
        self.set_baudrate(self.FAST_BAUDRATE)  # from deaf
        self.set_baudrate(self.DEFAULT_BAUDRATE)
        self.sync()

    def _sync_when_idle(self, patience=180) -> bool:
        """
        Sync with the module. As long as it is heard sending something else, keep listening
        and try again once it falls silent. False if nothing is heard from it at all.
        """
        give_up = time() + patience
        while time() < give_up:
            self.send("$PMTK", ["000"])
            heard = False
            while True:
                try:
                    r = self.receive()
                except TimeoutError:
                    break
                except ProtocolError:
                    heard = True
                    continue
                if r.type == "$PMTK" and r.args == ["001", "0", "3"]:
                    return True
                heard = True
            if not heard:
                return False
            logger.debug("GPS module was busy, syncing again")
        return False

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

    def read_log(self, progress: Progress | None = None, fast: bool = False) -> bytes:
        """
        Read the raw GPS log; progress is called with (lines received, lines total).
        With fast, the module is switched to the high speed for the transfer and always
        switched back afterwards, also when the transfer fails or is interrupted. Not
        every model's module takes that well, see the device classes' gps_fast_log.
        """
        self.ensure_ready()
        if not fast:
            return self._read_log_lines(progress)
        self.set_baudrate(self.FAST_BAUDRATE)
        try:
            return self._read_log_lines(progress)
        except (TimeoutError, ProtocolError) as e:
            # Now and then the module is deaf after the switch, or drops a line
            logger.warning(f"Fast log transfer failed ({e}), reading at the default speed")
        finally:
            self.set_baudrate(self.DEFAULT_BAUDRATE)
            self.ensure_ready()
        return self._read_log_lines(progress)

    def _read_log_lines(self, progress: Progress | None = None) -> bytes:
        raw_log_data = b''

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
        if progress:
            progress(0, number_of_lines)
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
                raw_log_data += bytes.fromhex(word)
            if progress:
                progress(len(received_line_numbers), number_of_lines)

        # Did we receive the log in order and completely?
        if received_line_numbers != list(range(number_of_lines)):
            raise ProtocolError("Unexpected log dump sequence from device")

        # Radio acknowledges ReadLog command
        r = self.receive()
        if r.type != "$PMTK" or len(r.args) != 3 or r.args != ["001", "622", "3"]:
            raise ProtocolError(f"Unexpected ReadLog acknowledgement from device: {str(r).strip()}")

        return raw_log_data

    def erase_log(self):
        # EraseLog command to radio
        self.send("$PMTK", ["184", "1"])

        # Radio acknowledges StatusLog command
        r = self.receive()
        if r.type != "$PMTK" or len(r.args) != 3 or r.args != ["001", "184", "3"]:
            raise ProtocolError(f"Unexpected EraseLog acknowledgement from device: {str(r).strip()}")


class GX1400Protocol(GenericHXProtocol):

    # A real serial link: the radio's own rate, and the lines as serial adapters expect them
    baudrate = 38400
    control_lines = True
    poll_before_read = True  # as the vendor tool does; skipping it is unverified on this model

    def _connect(self, tty):
        self.conn = hxtty.GenericHXTTY(tty, baudrate=self.baudrate, control_lines=self.control_lines)
        self.connected = True
        logger.debug("Attempting GX1400 sync")
        try:
            self.sync()
        except TimeoutError:
            logger.warning("No response, so probably not talking to GX1400")
            self.hx_hardware = False
            self.cp_mode = False
            return

        logger.debug("Sync successful, assuming GX1400 hardware and CP mode")
        self.hx_hardware = True
        self.cp_mode = True

        # On the GX1400, there doesn't appear to be a distinction between
        # CP mode and command mode. The device is immediately ready for use.
        # However, since it's a generic serial link, there is no way to know
        # in advance whether or not the connected device is in fact a GX1400.

        # NMEA mode is currently not detected. The device can be configured to
        # send NMEA data at 38400 baud, so adding this feature here may not be
        # too difficult. But given that NMEA data comes in from the GX1400 over
        # a regular serial link rather than USB, dedicated NMEA software is
        # probably more suited than hxtool for reading it anyway.


class ReadMagicProtocol(GenericHXProtocol):

    def __init__(self, tty=None, baudrate=38400):
        self.hx_hardware = False
        try:
            logger.debug(f"Trying `{tty}` sync at {baudrate} baud")
            self.conn = hxtty.GenericHXTTY(tty, baudrate=baudrate)
            self.sync()
            self.hx_hardware = True
        except TimeoutError:
            logger.debug("No response, so probably wrong baudrate or not a supported device")
            return
        except ProtocolError:
            logger.debug("Unexpected response, so probably not a supported device")
            return
        except OSError as e:
            logger.debug(f"OS error: {e} (ignoring, so we can look at other devices)")
            return
