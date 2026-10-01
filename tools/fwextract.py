#!/usr/bin/env python3
"""
Extract the firmware image from a Standard Horizon firmware updater (e.g. "Firmware Update HX870_V204.exe").

The .NET updaters for the HX870 carry the firmware as Motorola S-records in which six hex digits are swapped
(0 with F, 4 with 7, 5 with 6). This reads the records out of the program file, undoes the swap and writes
the image twice: as S-records, which say where the image goes and which `hxtool firmware` takes, and as a
flat binary for a disassembler, with the addresses that needs printed.

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


def extract(program: bytes) -> tuple[list[str], dict[int, bytes], str, int | None]:
    """(S-records, data by address, header text, entry address) of the firmware in an updater program"""
    records, chunks, header, entry = [], {}, "", None
    for scrambled in scrambled_records(program):
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
