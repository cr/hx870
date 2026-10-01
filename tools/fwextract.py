#!/usr/bin/env python3
"""
Extract the firmware image from a Standard Horizon firmware updater (e.g. "Firmware Update HX870_V204.exe").

The .NET updaters for the HX870 carry the firmware as Motorola S-records in which six hex digits are swapped
(0 with F, 4 with 7, 5 with 6). The native updater for the HX890 carries it as a table of blocks, each byte
XORed with a key of 128 bytes that stands before the table. This reads the image out of the program file,
decodes it and writes it twice: as S-records, which say where the image goes and which `hxtool firmware`
takes, and as a flat binary for a disassembler, with the addresses that needs printed.

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


def format_record(kind: int, address: int, data: bytes = b"") -> str:
    width = ADDRESS_BYTES.get(str(kind), 2 if kind == 0 else 4)
    body = bytes([width + len(data) + 1]) + address.to_bytes(width, "big") + data
    return f"S{kind}{body.hex().upper()}{(sum(body) ^ 0xff) & 0xff:02X}"


# The HX890 updater's block table. A block record starts with the address of the block's first S-record as six
# hex digits with bit 7 set, padded with 0x80; then, little endian, the block's start at +0x0C, its end
# (exclusive) at +0x1C and its length at +0x20; the content from +0x34, and the next record after it. A 0xFF
# ends the table. The key is the 128 bytes before the first record, applied anew to every block. The flash
# commands carry the low 24 bits of the MCU's addresses, so the blocks lie at 0xFF000000 above their starts.
BLOCK_NAME = re.compile(rb"[\xb0-\xb9\xc1-\xc6]{6}\x80{4}")
KEY_LENGTH = 0x80
BLOCK_CONTENT = 0x34
MCU_BASE = 0xff000000
ROW = 16


def extract_blocks(program: bytes) -> tuple[list[str], dict[int, bytes], str, int | None]:
    """extract() for the block table of the HX890 updater; the records are made up, 16 bytes to each"""
    table = BLOCK_NAME.search(program)
    if not table or table.start() < KEY_LENGTH:
        raise ValueError("no firmware records found")
    position = table.start()
    key = program[position - KEY_LENGTH:position]
    chunks = {}
    while position + BLOCK_CONTENT <= len(program) and program[position] != 0xff:
        start, end, length = (int.from_bytes(program[position + field:position + field + 4], "little")
                              for field in (0x0c, 0x1c, 0x20))
        content = program[position + BLOCK_CONTENT:position + BLOCK_CONTENT + length]
        if end - start != length or len(content) != length:
            raise ValueError(f"block table at 0x{table.start():X} is not as expected")
        chunks[MCU_BASE | start] = bytes(byte ^ key[n % KEY_LENGTH] for n, byte in enumerate(content))
        position += BLOCK_CONTENT + length
    # The image names its flash ID in the last 16 bytes of the firmware area
    last = chunks[max(chunks)]
    header = last[-16:].split(b"\x00")[0].decode("ascii", "replace") if last[-16:-10].isalnum() else ""
    records = [format_record(0, 0, header.encode("ascii"))]
    for address in sorted(chunks):
        records += [format_record(3, address + offset, chunks[address][offset:offset + ROW])
                    for offset in range(0, len(chunks[address]), ROW)]
    records.append(format_record(7, 0))
    return records, chunks, header, None


def extract(program: bytes) -> tuple[list[str], dict[int, bytes], str, int | None]:
    """(S-records, data by address, header text, entry address) of the firmware in an updater program"""
    records, chunks, header, entry = [], {}, "", None
    found = scrambled_records(program)
    if not found:
        return extract_blocks(program)
    for scrambled in found:
        record = scrambled.translate(SWAP)
        kind, address, data = parse(record)
        records.append(record)
        if kind == "0":
            header = data.decode("ascii", "replace").strip()
        elif kind in ADDRESS_BYTES:
            chunks[address] = data
        elif kind in "789":
            entry = address
    if not chunks:
        raise ValueError("no firmware records found")
    return records, chunks, header, entry


def segments(chunks: dict[int, bytes]) -> list[tuple[int, int]]:
    """(start, end-exclusive) of the runs of adjoining records"""
    runs: list[list[int]] = []
    for address in sorted(chunks):
        if runs and runs[-1][1] == address:
            runs[-1][1] = address + len(chunks[address])
        else:
            runs.append([address, address + len(chunks[address])])
    return [(start, end) for start, end in runs]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("updater", help="the firmware updater program (.exe)")
    parser.add_argument("image", help="name for the image files: IMAGE.srec and IMAGE.bin are written")
    args = parser.parse_args(argv)
    with open(args.updater, "rb") as f:
        program = f.read()
    try:
        records, chunks, header, entry = extract(program)
    except ValueError as e:
        print(f"{args.updater}: {e}", file=sys.stderr)
        return 1

    # The binary runs from the first byte to the last. Gaps between records are 0xFF, as erased flash.
    start = min(chunks)
    end = max(address + len(data) for address, data in chunks.items())
    image = bytearray(b"\xff" * (end - start))
    for address, data in chunks.items():
        image[address - start:address - start + len(data)] = data

    base = args.image.removesuffix(".bin").removesuffix(".srec")
    with open(f"{base}.srec", "w", encoding="ascii", newline="\n") as f:
        f.write("\n".join(records) + "\n")
    with open(f"{base}.bin", "wb") as f:
        f.write(image)

    runs = segments(chunks)
    version = bytes(image[:11]).decode("ascii", "replace").strip()
    print(f"{base}.srec: {len(records)} records, header {header!r}, version {version!r}")
    print(f"{base}.bin: {len(image)} bytes for 0x{start:08X}..0x{end - 1:08X}, "
          + (f"entry 0x{entry:08X}" if entry is not None else "no entry address"))
    print(f"  {sum(e - s for s, e in runs)} bytes of data in {len(runs)} segments, the rest is 0xFF:")
    for run_start, run_end in runs:
        print(f"    0x{run_start:08X}..0x{run_end - 1:08X} ({run_end - run_start} bytes)")
    print(f"  to load it where it lies: rizin -a rx -b 32 -m 0x{start:08x} {base}.bin")
    return 0


if __name__ == "__main__":
    sys.exit(main())
