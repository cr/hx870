# -*- coding: utf-8 -*-

import logging
import serial


logger = logging.getLogger(__name__)


class HX870TTY(object):
    """
    Serial communication for Standard Horizon HX870 maritime radios
    """

    def __init__(self, tty):
        """
        Serial connection class for HX870 handsets

        :param device: TTY device to use
        """
        self.tty = tty
        self.s = serial.Serial(tty, timeout=1)
        logger.info("Connected to `%s`" % self.s.name)

    def write(self, data):
        logger.debug("OUT: %s" % repr(data))
        return self.s.write(data)

    def read(self, *args, **kwargs):
        result = self.s.read(*args, **kwargs)
        logger.debug("  IN: %s" % repr(result))
        if len(result) == 0:
            raise TimeoutError("HX870 read() timeout")
        return result

    def read_all(self, *args, **kwargs):
        result = self.s.read_all(*args, **kwargs)
        if len(result) == 0:
            raise TimeoutError("HX870 read_all() timeout")
        logger.debug("  IN: %s" % repr(result))
        return result

    def read_line(self, *args, **kwargs):
        result = self.s.readline(*args, **kwargs)
        if len(result) == 0:
            raise TimeoutError("H870TTY read_line() timeout")
        logger.debug("  IN: %s" % repr(result))
        return result

    def available(self):
        return self.s.in_waiting

    def flush_input(self):
        if self.s.in_waiting > 0:
            logger.warning("Flushing %d bytes from input buffer" % self.s.in_waiting)
        return self.s.flushInput()

    def flush_output(self):
        if self.s.out_waiting > 0:
            logger.warning("Flushing %d bytes from output buffer" % self.s.out_waiting)
        return self.s.flushOutput()
