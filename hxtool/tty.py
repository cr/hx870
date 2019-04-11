# -*- coding: utf-8 -*-

import logging
import serial


logger = logging.getLogger(__name__)


class GenericHXTTY(object):
    """
    Serial communication for Standard Horizon HX maritime radios
    """

    def __init__(self, tty, timeout=1.5):
        """
        Serial connection class for HX870 handsets

        :param device: TTY device to use
        """
        self.tty = tty
        logger.debug(f"Connecting to {tty}")
        self.default_timeout = timeout
        if tty.upper() == "CP_SIM":
            self.s = SerialHXSimulator(mode="CP", timeout=timeout)
        elif tty.upper() == "NMEA_SIM":
            self.s = SerialHXSimulator(mode="NMEA", timeout=timeout)
        else:
            self.s = serial.Serial(tty, timeout=timeout)

    def write(self, data):
        logger.debug("OUT: %s" % repr(data))
        return self.s.write(data)

    def read(self, *args, **kwargs):
        result = self.s.read(*args, **kwargs)
        logger.debug("  IN: %s" % repr(result))
        if len(result) == 0:
            raise TimeoutError(f"{self.tty} read() timeout")
        return result

    def read_all(self):
        result = self.s.read_all()
        if len(result) == 0:
            raise TimeoutError(f"{self.tty} read_all() timeout")
        logger.debug("  IN: %s" % repr(result))
        return result

    def read_line(self, *args, **kwargs):
        result = self.s.readline(*args, **kwargs)
        if len(result) == 0:
            raise TimeoutError(f"{self.tty} read_line() timeout")
        logger.debug("  IN: %s" % repr(result))
        return result

    def available(self):
        return self.s.in_waiting

    def flush_input(self):
        if self.s.in_waiting > 0:
            logger.warning(f"{self.tty} flushing {self.s.in_waiting} bytes from input buffer")
        return self.s.flushInput()

    def flush_output(self):
        if self.s.out_waiting > 0:
            logger.warning(f"{self.tty} flushing {self.s.out_waiting} bytes from output buffer")
        return self.s.flushOutput()


class SerialHXSimulator(object):
    def __init__(self, mode, timeout=1.5):
        self.mode = mode
        self.timeout = timeout
        self.mem = b"\xff" * 0x8000
        self.output_buffer = b""
        self.input_buffer = b""

    @property
    def in_waiting(self):
        return len(self.input_buffer)

    @property
    def out_waiting(self):
        return len(self.output_buffer)

    def flushInput(self):
        self.input_buffer = b""

    def flushOutput(self):
        self.output_buffer = b""

    def read(self, size):
        r = self.input_buffer[:size]
        self.input_buffer = self.input_buffer[len(r):]
        return r

    def write(self, data):
        self.output_buffer += data

    def readline(self, *args, **kwargs):
        return b"\r\n"

    def read_all(self):
        r = self.input_buffer
        self.input_buffer = b""
        return r
