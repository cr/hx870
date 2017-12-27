# -*- coding: utf-8 -*-

import os

class ConfigFile(object):

    MAGIC = b'\x03\x67'

    def __init__(self, file_name):
        self.m = None
        self.p = None

        if file_name is None or not os.path.isfile(file_name):
            self.clear()
        else:
            self.read(file_name)

    def read(self, file_name):
        if not file_name.lower().endswith(".dat"):
            raise Exception("unexpected .DAT file extension")
        if os.stat(file_name).st_size != (1<<15):
            raise Exception("unexpected .DAT file size")
        with open(file_name, "rb") as f:
            self.m = f.read();
        if self.m[0:2] != self.MAGIC or self.m[-2:] != self.MAGIC:
            raise Exception("unexpected .DAT file magic")

    def clear(self):
        self.m = bytes([0xff] * (2<<15))
        self.p = {}
