#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Extract data from pcap dumps with
# tshark -r $PCAPFILE -2 -R "usb.device_address == 6 && usb.transfer_type == 3" -T fields -e usb.endpoint_address.direction -e usb.capdata

import binascii
import os
import subprocess as sp
import sys

if not len(sys.argv) == 3:
    sys.stderr.write("usage: %s print|dump <file_name>\n" % os.path.basename(sys.argv[0]))
    sys.exit(1)

mode = sys.argv[1]
file_name = sys.argv[2]

valid_modes = ["print", "dump"]
if mode not in valid_modes:
    sys.stderr.write("ERROR: invalid mode\n")
    sys.exit(5)

if not os.path.isfile(file_name):
    sys.stderr.write("ERROR: file does not exist\n")
    sys.exit(6)

try:
    proc = sp.Popen([
        "tshark",
        "-r", file_name,
        "-2",
        "-R", "usb.transfer_type == 3",
        "-T", "fields",
        "-e", "usb.device_address",
        "-e", "usb.endpoint_address.direction",
        "-e", "usb.capdata"], stdout=sp.PIPE, stderr=sp.PIPE)
    output, err = proc.communicate()

except FileNotFoundError:
    sys.stderr.write("ERROR: `tshark` command not found. Please install Wireshark command line tools.\n")
    sys.exit(7)

if proc.returncode != 0:
    sys.stderr.write("ERROR: `tshark` command failed:\n")
    sys.stderr.write(err)
    sys.exit(8)

protocol = []
for l in output.decode("utf-8").split("\n"):
    if len(l) == 0:
        continue
    x = l.strip().split("\t")
    s = binascii.unhexlify(x[2].replace(":", "")).decode("utf-8")
    protocol.append((x[0], x[1], s))

if mode == "print":
    for dev, direction, string in protocol:
        print("%s %s%s" % (dev, "> " if direction == "0" else "  < ", repr(string)[1:-1]))

elif mode == "dump":
    start_address = None
    prev_address = None
    for dev, direction, string in protocol:
        for cmd in string.split("\n"):
            if cmd.startswith("#CFLWR") or cmd.startswith("#CEPDT"):
                c = cmd.split("\t")
                address = int(c[1], 16)
                length = int(c[2], 16)
                if start_address is None:
                    start_address = address
                    sys.stderr.write("INFO: start address 0x%08x\n" % start_address)
                if prev_address is not None:
                    if address != prev_address + length:
                        sys.stderr.write("WARNING: non-continguous address, new address 0x%08x\n" % address)
                data = binascii.unhexlify(c[3])
                sys.stdout.buffer.write(data)
                prev_address = address

