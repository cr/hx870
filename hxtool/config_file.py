# -*- coding: utf-8 -*-

from os import path, stat


class ConfigFile(object):
    """
    Container for an HX870 config memory image as the vendor's .DAT file
    stores it: the 32 KiB image, framed by the config magic 0x0367 (871) at
    both ends. See hx870dat.bt for the layout of the image itself.

    Reading checks extension, size and magic only. Parsing the content
    into fields (`p`) is not implemented, and nothing in hxtool uses this
    class yet; it is kept as the record of the file format.
    """

    MAGIC = b'\x03\x67'

    def __init__(self, file_name, size=(1 << 15)):
        self.m = None
        self.p = None
        self.size = size

        if file_name is None or not path.isfile(file_name):
            self.clear()
        else:
            self.read(file_name)

    def read(self, file_name):
        if not file_name.lower().endswith(".dat"):
            raise Exception("unexpected .DAT file extension")
        if stat(file_name).st_size != self.size:
            raise Exception("unexpected .DAT file size")
        with open(file_name, "rb") as f:
            self.m = f.read()
        if self.m[0:2] != self.MAGIC or self.m[-2:] != self.MAGIC:
            raise Exception("unexpected .DAT file magic")

    def clear(self):
        self.m = bytes([0xff] * self.size)
        self.p = {}
