"""
Firmware images as Motorola S-records, the form the vendor's updaters hold them in.
An image is a set of address segments, so it says itself where in the flash it goes.
"""

import re
from typing import NamedTuple
from collections.abc import Iterable

RECORD = re.compile(r"S[0-35-9](?:[0-9A-Fa-f]{2})+")
ADDRESS_BYTES = {0: 2, 1: 2, 2: 3, 3: 4, 5: 2, 6: 3, 7: 4, 8: 3, 9: 2}
DATA, COUNT, ENTRY = (1, 2, 3), (5, 6), (7, 8, 9)
ERASED = 0xff


class SRecordError(ValueError):
    pass


class Segment(NamedTuple):
    """A run of bytes at an address"""
    address: int
    data: bytes


def parse_record(record: str) -> tuple[int, int, bytes]:
    """(type, address, data) of one S-record"""
    if not RECORD.fullmatch(record):
        raise SRecordError("not an S-record")
    kind = int(record[1])
    body = bytes.fromhex(record[2:])
    width = ADDRESS_BYTES[kind]
    if body[0] != len(body) - 1 or len(body) < width + 2:
        raise SRecordError("length mismatch")
    if ~sum(body[:-1]) & 0xff != body[-1]:
        raise SRecordError("checksum mismatch")
    return kind, int.from_bytes(body[1:1 + width], "big"), body[1 + width:-1]


def format_record(kind: int, address: int, data: bytes = b"") -> str:
    width = ADDRESS_BYTES[kind]
    body = bytes([width + len(data) + 1]) + address.to_bytes(width, "big") + data
    return f"S{kind}{body.hex().upper()}{~sum(body) & 0xff:02X}"


class Image:
    """
    A firmware image: segments in address order (adjoining ones merged; where two overlap,
    the one at the higher address overlays the other), the text of the header record, and
    the entry address.
    """

    def __init__(self, segments: Iterable[Segment] = (), header: str = "", entry: int | None = None):
        self.header = header
        self.entry = entry
        merged: list[tuple[int, bytearray]] = []
        for address, data in sorted(segments, key=lambda segment: segment[0]):
            if not data:
                continue
            if merged and address <= merged[-1][0] + len(merged[-1][1]):
                offset = address - merged[-1][0]
                merged[-1][1][offset:offset + len(data)] = data
            else:
                merged.append((address, bytearray(data)))
        self.segments = [Segment(address, bytes(data)) for address, data in merged]

    @property
    def size(self) -> int:
        """Bytes of data in the image"""
        return sum(len(segment.data) for segment in self.segments)

    # S-records

    @classmethod
    def from_srec(cls, text: str | bytes) -> "Image":
        if isinstance(text, bytes):
            try:
                text = text.decode("ascii")
            except UnicodeDecodeError as e:
                raise SRecordError("not S-records, but binary data") from e
        segments, header, entry, records = [], "", None, 0
        for number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                kind, address, data = parse_record(line.strip())
            except SRecordError as e:
                raise SRecordError(f"line {number}: {e}") from e
            records += 1
            if kind == 0:
                header = data.decode("ascii", "replace").rstrip("\x00 ")
            elif kind in DATA:
                segments.append(Segment(address, data))
            elif kind in ENTRY:
                entry = address
        if not records:
            raise SRecordError("no S-records")
        return cls(segments, header, entry)

    def to_srec(self, row: int = 16) -> str:
        """The image as S-records with 32 bit addresses, row bytes to a record"""
        lines = [format_record(0, 0, self.header.encode("ascii", "replace"))]
        for address, data in self.segments:
            lines += [format_record(3, address + offset, data[offset:offset + row])
                      for offset in range(0, len(data), row)]
        lines.append(format_record(7, self.entry or 0))
        return "\n".join(lines) + "\n"

    # Flat binary

    @classmethod
    def from_binary(cls, data: bytes, address: int) -> "Image":
        """A flat image that lies at address"""
        return cls([Segment(address, data)])

    def to_binary(self) -> bytes:
        """From the first byte to the last, gaps filled as erased flash"""
        if not self.segments:
            return b""
        start = self.segments[0].address
        return self.read(start, self.segments[-1].address + len(self.segments[-1].data) - start)

    def read(self, address: int, length: int) -> bytes:
        """The bytes at address, erased flash where the image has none"""
        result = bytearray([ERASED]) * length
        for start, data in self.segments:
            low, high = max(start, address), min(start + len(data), address + length)
            if low < high:
                result[low - address:high - address] = data[low - start:high - start]
        return bytes(result)

    def without_erased(self, row: int = 16) -> "Image":
        """The image without the rows (aligned to row bytes) that are nothing but erased flash"""
        kept = []
        for address, data in self.segments:
            position, end = address, address + len(data)
            while position < end:
                row_end = min(end, (position // row + 1) * row)
                row_data = data[position - address:row_end - address]
                if row_data.strip(bytes([ERASED])):
                    kept.append(Segment(position, row_data))
                position = row_end
        return Image(kept, self.header, self.entry)
