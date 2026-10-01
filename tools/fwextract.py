#!/usr/bin/env python3
"""
Extract the firmware image from a Standard Horizon firmware updater (e.g. "Firmware Update HX870_V204.exe").

The .NET updaters for the HX870 carry the firmware as Motorola S-records in which six hex digits are swapped
(0 with F, 4 with 7, 5 with 6). This reads the records out of the program file, undoes the swap and writes
the image as the radio's flash sees it, plus where it goes.

Nothing is executed and no radio is involved.
"""
import argparse
import re
import sys

SWAP = str.maketrans("0F4756", "F07465")
RECORD = re.compile(r"S[0-9A-F]{9,}")
ADDRESS_BYTES = {"1": 2, "2": 3, "3": 4}


def scrambled_records(program: bytes) -> list[str]:
    """The S-record strings in the file, as UTF-16 (.NET string literals) or plain ASCII"""
    utf16 = [m.group().decode("utf-16-le") for m in re.finditer(rb"(?:S\x00)(?:[0-9A-F]\x00){9,}", program)]
    ascii_ = [m.group().decode("ascii") for m in re.finditer(rb"S[0-9A-F]{9,}", program)]
    return max(utf16, ascii_, key=len)


def parse(record: str) -> tuple[str, int, bytes]:
    """(type, address, data) of one S-record; raises ValueError if it is not one"""
    if not RECORD.fullmatch(record) or len(record) % 2:
        raise ValueError(f"not an S-record: {record}")
    kind = record[1]
    body = bytes.fromhex(record[2:])
    if body[0] != len(body) - 1:
        raise ValueError(f"length mismatch: {record}")
    if (sum(body[:-1]) ^ 0xff) & 0xff != body[-1]:
        raise ValueError(f"checksum mismatch: {record}")
    width = ADDRESS_BYTES.get(kind, 2 if kind in "05" else {"7": 4, "8": 3, "9": 2}.get(kind, 2))
    return kind, int.from_bytes(body[1:1 + width], "big"), body[1 + width:-1]


def extract(program: bytes) -> tuple[int, bytes, str]:
    """(load address, image, header text). Gaps between records are filled with 0xFF, as erased flash."""
    chunks, header = {}, ""
    for scrambled in scrambled_records(program):
        kind, address, data = parse(scrambled.translate(SWAP))
        if kind == "0":
            header = data.decode("ascii", "replace").strip()
        elif kind in ADDRESS_BYTES:
            chunks[address] = data
    if not chunks:
        raise ValueError("no firmware records found")
    start = min(chunks)
    end = max(address + len(data) for address, data in chunks.items())
    image = bytearray(b"\xff" * (end - start))
    for address, data in chunks.items():
        image[address - start:address - start + len(data)] = data
    return start, bytes(image), header


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("updater", help="the firmware updater program (.exe)")
    parser.add_argument("image", help="file to write the firmware image to")
    args = parser.parse_args()
    with open(args.updater, "rb") as f:
        program = f.read()
    try:
        start, image, header = extract(program)
    except ValueError as e:
        print(f"{args.updater}: {e}", file=sys.stderr)
        return 1
    with open(args.image, "wb") as f:
        f.write(image)
    version = image[:11].decode("ascii", "replace").strip()
    print(f"{args.image}: {len(image)} bytes for 0x{start:08X}..0x{start + len(image) - 1:08X}, "
          f"header {header!r}, version {version!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
