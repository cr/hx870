#!/usr/bin/env python3

# Extract data from USB pcap dumps of the vendor tool talking to a radio, with
# tshark -r $PCAPFILE -2 -R "usb.device_address == 6 && usb.transfer_type == 3" \
#     -T fields -e usb.endpoint_address.direction -e usb.capdata

import os
import subprocess as sp
import sys

if not len(sys.argv) == 3:
    sys.stderr.write(f"usage: {os.path.basename(sys.argv[0])} print|dump <file_name>\n")
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
    sys.stderr.write(err.decode("utf-8", errors="replace"))
    sys.exit(8)

protocol = []
for line in output.decode("utf-8").split("\n"):
    if len(line) == 0:
        continue
    x = line.strip().split("\t")
    s = bytes.fromhex(x[2].replace(":", "")).decode("utf-8")
    protocol.append((x[0], x[1], s))

if mode == "print":
    for dev, direction, string in protocol:
        print(f"{dev} {'> ' if direction == '0' else '  < '}{repr(string)[1:-1]}")

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
                    sys.stderr.write(f"INFO: start address 0x{start_address:08x}\n")
                if prev_address is not None:
                    if address != prev_address + length:
                        sys.stderr.write(f"WARNING: non-continguous address, new address 0x{address:08x}\n")
                data = bytes.fromhex(c[3])
                sys.stdout.buffer.write(data)
                prev_address = address
