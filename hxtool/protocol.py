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


class GPSModuleSilent(TimeoutError):
    """The GPS module answers at none of the speeds the radio can be switched to"""

    log_data: bytes | None = None  # the log, if it had been read completely before


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


def _check_transfer(what: str, offset: int, length: int, max_offset: int, max_length: int):
    """Address and length have fixed widths on the wire"""
    if not 0 <= offset <= max_offset:
        raise ProtocolError(f"{what} offset 0x{offset:x} out of range")
    if not 1 <= length <= max_length:
        raise ProtocolError(f"{what} transfer length {length} out of range (1-{max_length})")


def _transfer_data(reply: Message, offset: int, length: int) -> bytes:
    """The data of a read reply, which repeats the address and the length asked for"""
    try:
        reply_offset, reply_length, data = int(reply.args[0], 16), int(reply.args[1], 16), bytes.fromhex(reply.args[2])
    except (IndexError, ValueError) as e:
        raise ProtocolError(f"Unexpected data reply format from device: {str(reply).strip()}") from e
    if reply_offset != offset or reply_length != length or len(data) != length:
        raise ProtocolError(f"Unexpected data reply from device: requested {length} bytes at 0x{offset:04x}, "
                            f"got {len(data)} bytes labeled as {reply_length} bytes at 0x{reply_offset:04x}")
    return data


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
        self.flash_mode = False  # firmware flash mode, entered from CP mode, see FirmwareProtocol
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
        if self.flash_mode:
            logger.debug("Device is in firmware flash mode")

    def _detect_device_mode(self):

        # In CP mode, an HX device replies with "@" to "?" and ignores "P".
        # In firmware flash mode, which outlasts the connection that entered it, it ignores
        # both and answers the flash status request.
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
        elif not received and self._answers_flash_status():
            logger.debug("Response like HX hardware in firmware flash mode")
            self.hx_hardware, self.flash_mode = True, True
        elif not received and self.identified:
            logger.info("No response to handshake, assuming NMEA mode with GPS output off or asleep")
            self.hx_hardware, self.cp_mode, self.nmea_mode = True, False, True
        elif not received:
            logger.warning("No response, so probably not talking to HX hardware")
        else:
            logger.warning(f"Unexpected response {received!r}, so probably not talking to HX hardware")

    def _answers_flash_status(self) -> bool:
        try:
            self.request("#CFLSR", ["00"], "#CFLSD", timeout=0.5)
        except (TimeoutError, ProtocolError):
            return False
        return True

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

    def request(self, message_type, args=None, reply_type=None, terminator=False, timeout=None):
        """
        One exchange, in the pattern of every # request: the device acknowledges with #CMDOK,
        sends its data reply if the command has one (reply_type), and that reply is
        acknowledged back, or the device repeats it. Returns the data reply, or None.
        terminator: the vendor's firmware updater follows some commands with a ';' byte.
        timeout: seconds to wait for the acknowledgement, instead of the transport's.
        """
        self.write(bytes(Message(message_type, args)) + (b";" if terminator else b""))
        if timeout is not None:
            deadline = time() + timeout
            while not self.available():
                if time() >= deadline:
                    raise TimeoutError(f"No answer to {message_type}")
                sleep(0.01)
        r = self.receive()
        if r.type == "#CMDUN":
            raise ProtocolError(f"Device does not know the command {message_type}")
        if r.type != "#CMDOK":
            raise ProtocolError(f"Device did not acknowledge {message_type}: {str(r).strip()}")
        if reply_type is None:
            return None
        d = self.receive()
        if d.type != reply_type:
            raise ProtocolError(f"Unexpected reply to {message_type}: {str(d).strip()}")
        self.send("#CMDOK")
        return d

    def get_firmware_version(self):
        cvrdq = self.request("#CVRRQ", reply_type="#CVRDQ")
        r = self.receive()  # the radio answers the acknowledgement of this reply
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
            radio_status = self.request("#CEPSR", ["00"], "#CEPSD").args[0]
            if radio_status != "00":
                logger.debug("Waiting for radio, state=%s", radio_status)
        if radio_status != "00":
            raise TimeoutError("Device not ready")

    # The address and length fields of config memory transfers are two and one byte wide.
    # That is the wire format's limit; the radios' own is lower: an HX870 returns garbled
    # data for reads longer than 0x40 bytes (its reply buffer wraps), which is why the
    # models' CHUNK_SIZE, the vendor tool's transfer size, is what transfers should use.
    MAX_OFFSET = 0xffff
    MAX_TRANSFER = 0xff

    def read_config_memory(self, offset, length):
        _check_transfer("Config memory", offset, length, self.MAX_OFFSET, self.MAX_TRANSFER)
        if self.poll_before_read or self._written:
            self.wait_for_ready()
            self._written = False
        d = self.request("#CEPRD", [f"{offset:04X}", f"{length:02X}"], "#CEPDT")
        return _transfer_data(d, offset, length)

    def write_config_memory(self, offset, data):
        _check_transfer("Config memory", offset, len(data), self.MAX_OFFSET, self.MAX_TRANSFER)
        self.wait_for_ready()
        self._written = True
        self.request("#CEPWR", [f"{offset:04X}", f"{len(data):02X}", data.hex().upper()])


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
    # The radio does not pass $PMTK251 on but runs a switch sequence of its own, about a
    # second long, during which it drops every $PMTK sentence from the host. On the HX870:
    # - The switch is not acknowledged. After one in five to twelve the module is deaf:
    #   the firmware cuts the line feed off its own switch command, and the module only
    #   executes it when the next complete sentence arrives. Switching down, up and down
    #   again brings both back to the default speed.
    # - At the high speed a short sentence that directly follows another one is dropped by
    #   the radio: the dump's header line now and then, replies to the sync often. The
    #   dump's data lines come through.
    # - A switch to 9600 at 9600 does no harm; a switch to 115200 at 115200 leaves the
    #   module silent until it is switched down.
    # - The module keeps its speed when the radio is switched off, and the radio only
    #   looks for it at these two speeds. Another speed is only ever requested to find a
    #   module that answers at neither (ensure_ready).
    # Details in the README, "GPS module speed".
    DEFAULT_BAUDRATE = 9600
    FAST_BAUDRATE = 115200
    # Every speed the radio accepts: the two it looks for itself first, then the rest
    SPEEDS = (9600, 115200, 57600, 38400, 19200, 14400, 4800)
    SWITCH_SETTLE = 1.5  # seconds; the radio's switch sequence takes up to 1.1

    def set_baudrate(self, rate: int):
        """Ask the radio to switch the GPS module's speed and wait for its switch sequence to end."""
        self.send("$PMTK", ["251", str(rate)])
        sleep(self.SWITCH_SETTLE)
        self.p.conn.flush_input(expected=True)  # the module may send a system message

    def ensure_ready(self):
        """
        Make sure the GPS module answers, at its default speed if it had to be looked for.
        A module that is merely busy, sending the rest of a log dump nobody reads any more,
        is waited for. A silent one is looked for at every speed the radio can be switched
        to, the likely ones first, and brought back to the default speed. That also finds
        a module the radio itself has lost: it only looks at the first two when it starts.
        """
        if self._sync_when_idle():
            return
        logger.warning("GPS module does not answer, looking for it")
        for rate in self.SPEEDS:
            self.set_baudrate(rate)
            if not self._answers():
                continue
            if rate != self.DEFAULT_BAUDRATE:
                logger.warning(f"GPS module found at {rate} baud, switching it back to {self.DEFAULT_BAUDRATE}")
                self.set_baudrate(self.DEFAULT_BAUDRATE)
                if not self._answers():
                    # The radio cut its own command short. The module executes it as soon
                    # as the radio talks to it at its speed again.
                    self.set_baudrate(rate)
                    self.set_baudrate(self.DEFAULT_BAUDRATE)
                    self.sync()
            return
        self.set_baudrate(self.DEFAULT_BAUDRATE)  # where the radio's firmware expects its side
        raise GPSModuleSilent("GPS module does not answer at any speed")

    def _answers(self, attempts=2) -> bool:
        """Sync, more than once: above the default speed the radio now and then drops the reply"""
        return any(self._sync_when_idle() for _ in range(attempts))

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
        With fast, the module is switched to the high speed for the transfer. That is quicker
        and unstable: the transfer fails now and then, and it is not repeated. Whatever
        happens, also on an interrupt, the module is switched back afterwards and checked
        to answer; if it has fallen silent for good, GPSModuleSilent carries the log that
        was read, if it was read completely.
        """
        self.ensure_ready()
        if not fast:
            return self._read_log_lines(progress)
        log_data = None
        self.set_baudrate(self.FAST_BAUDRATE)
        try:
            log_data = self._read_log_lines(progress)
            return log_data
        finally:
            self.set_baudrate(self.DEFAULT_BAUDRATE)
            try:
                self.ensure_ready()
            except GPSModuleSilent as silent:
                silent.log_data = log_data
                raise

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


class FirmwareProtocol:
    """
    Firmware flash access over the #CFL* command family, as the vendor's firmware updaters
    for the HX870 and the HX890 use it. The wire level only: what lies where in the flash
    is the model's knowledge, see hxtool.firmware.

    The radio is put into flash mode by a handshake (#CMDNR, #CFLID, #CFLMC 01) that it
    grants once per power-on. Flash mode outlasts the connection (a new connection finds
    the radio in it, without the flash ID) and is left by reboot() (#CFLMC 03) or
    poweroff() (#CFLMC 02); the radio then is no longer in CP mode.

    Read on an HX870 with firmware 02.04 and an HX891BT with firmware 1.00: handshake,
    #CFLRR / #CFLRD (the counterpart of #CFLWR that the updater builds but never sends) and
    reboot. Erase and write follow the updater and have not been run against a radio.
    """

    # The updater pauses a second around the mode changes and polls the flash status
    # before every transfer, backing off from 20 ms while the flash is busy.
    MODE_SETTLE = 1.0
    STATUS_BACKOFF = 0.02

    # How long the HX890 updater waits for the radio to acknowledge the slow commands:
    # the acknowledgement comes when the flash operation is done.
    ERASE_TIMEOUT = 10
    BLANK_CHECK_TIMEOUT = 5
    WRITE_TIMEOUT = 8

    # Address and length fields of the transfers are three and one byte wide
    MAX_OFFSET = 0xffffff
    MAX_TRANSFER = 0xff

    # Bits of the flash status byte, as the HX890 updater names them
    STATUS_BITS = {
        0x01: "blank error",
        0x02: "erase error",
        0x04: "program error",
        0x08: "read error",
        0x10: "ID error",
        0x20: "area error",
        0x40: "unknown",
        0x80: "busy",
    }

    def __init__(self, proto: GenericHXProtocol):
        self.p = proto         # its flash_mode says whether the radio is in flash mode
        self.flash_id = None   # the flash ID the radio named itself by in the handshake

    def _status_of(self, message_type, args, terminator=False, timeout=None) -> str:
        """
        A command the radio answers with the flash status (#CFLSD) when it is done.
        Returns the status byte as two hex digits; '00' is ready.
        """
        d = self.p.request(message_type, args, "#CFLSD", terminator=terminator, timeout=timeout)
        if not d.args:
            raise ProtocolError(f"Flash status without a value: {str(d).strip()}")
        return d.args[0]

    def _done(self, message_type, args, terminator=False, timeout=None):
        """A command that has failed unless the flash status it is answered with is ready"""
        flash_status = self._status_of(message_type, args, terminator, timeout)
        if flash_status != "00":
            raise ProtocolError(f"{message_type} failed, flash status {flash_status} "
                                f"({self.describe_status(flash_status)})")

    @classmethod
    def describe_status(cls, flash_status: str) -> str:
        """The bits of a flash status byte by name, e.g. 'program error, ID error'"""
        try:
            value = int(flash_status, 16)
        except ValueError:
            return "unreadable"
        return ", ".join(name for bit, name in cls.STATUS_BITS.items() if value & bit) or "ready"

    # Flash mode

    def enter_flash_mode(self):
        """Put the radio into flash mode, unless it is already. Possible once per power-on."""
        if self.p.flash_mode:
            return
        logger.debug("Entering firmware flash mode")
        # The updater names itself and offers the flash IDs of its model in turn. The radio
        # answers with its own ID, which is the one it accepts, so that one is offered.
        named = self.p.request("#CMDNR", ["STANDARD HORIZON"], "#CMDND", terminator=True)
        if not named.args:
            raise ProtocolError(f"Radio did not name its flash ID: {str(named).strip()}")
        self.flash_id = named.args[0]
        logger.debug(f"Radio names itself {self.flash_id!r}")
        # The ID field is ten bytes, padded with NUL. (The updater computes the checksum over
        # '!' padding and substitutes NUL afterwards; the radio accepts the checksum over the
        # bytes sent, as done here.)
        self._done("#CFLID", [self.flash_id.ljust(10, "\x00")], terminator=True)
        sleep(self.MODE_SETTLE)
        self._done("#CFLMC", ["01"], terminator=True)
        self.p.flash_mode = True
        self.p.sync()
        self.p.sync()

    def reboot(self):
        """
        Restart the radio by leaving flash mode, entering it first if need be. The radio
        comes up in its normal mode, so this connection has nothing more to say to it.
        """
        self.enter_flash_mode()
        sleep(self.MODE_SETTLE)
        self.p.request("#CFLMC", ["03"], terminator=True)
        self.p.flash_mode = False

    def poweroff(self):
        """
        Switch the radio off from flash mode, entering it first if need be (#CFLMC 02, seen
        on an HX891BT). The radio does not answer: it is gone, a USB radio's port with it.
        """
        self.enter_flash_mode()
        sleep(self.MODE_SETTLE)
        self.p.write(bytes(Message("#CFLMC", ["02"])) + b";")
        self.p.flash_mode = False

    # Transfers, in flash mode

    def status(self) -> str:
        """Flash status byte as two hex digits; '00' is ready"""
        return self._status_of("#CFLSR", ["00"])

    def wait_for_ready(self, timeout=30):
        """Poll the status until the flash is ready, backing off as the updater does"""
        backoff, deadline = self.STATUS_BACKOFF, time() + timeout
        while True:
            flash_status = self.status()
            if flash_status == "00":
                return
            if time() >= deadline:
                raise TimeoutError(f"Flash not ready, status {flash_status} "
                                   f"({self.describe_status(flash_status)})")
            logger.debug(f"Flash not ready, status {flash_status} ({self.describe_status(flash_status)})")
            sleep(backoff)
            backoff *= 2

    def read(self, offset: int, length: int) -> bytes:
        """One #CFLRR / #CFLRD transfer"""
        _check_transfer("Firmware flash", offset, length, self.MAX_OFFSET, self.MAX_TRANSFER)
        d = self.p.request("#CFLRR", [f"{offset:06X}", f"{length:02X}"], "#CFLRD")
        return _transfer_data(d, offset, length)

    def write(self, offset: int, data: bytes):
        """One #CFLWR transfer, after the status poll the updater makes before each"""
        _check_transfer("Firmware flash", offset, len(data), self.MAX_OFFSET, self.MAX_TRANSFER)
        self.wait_for_ready()
        self._done("#CFLWR", [f"{offset:06X}", f"{len(data):02X}", data.hex().upper()], timeout=self.WRITE_TIMEOUT)

    def erase(self):
        """Erase the firmware area and check it is blank, as the updater does before writing"""
        self._done("#CFLER", ["000000"], terminator=True, timeout=self.ERASE_TIMEOUT)
        self._done("#CFLCB", ["000000"], terminator=True, timeout=self.BLANK_CHECK_TIMEOUT)
        self.wait_for_ready()


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
