import importlib.util
from pathlib import Path

from hxtool.srec import Image, Segment

spec = importlib.util.spec_from_file_location("fwextract", Path(__file__).parent.parent / "tools" / "fwextract.py")
fwextract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fwextract)

FIRMWARE = Image([Segment(0xfff40000, b"  02.04    AM057N" + bytes(range(64))),
                  Segment(0xfff40100, b"\xde\xad\xbe\xef")], header="AM057N  mot", entry=0xfff40011)


def updater(image: Image) -> bytes:
    """A program file holding the records as the vendor's .NET updaters do: UTF-16 string literals, digits swapped"""
    literals = [record.translate(fwextract.SWAP).encode("utf-16-le") for record in image.to_srec().splitlines()]
    return b"MZ" + bytes(64) + b"".join(b"\x81\x15" + literal for literal in literals) + bytes(64)


def test_extracts_both_formats(tmp_path, capsys):
    program = tmp_path / "Firmware Update.exe"
    program.write_bytes(updater(FIRMWARE))

    assert fwextract.main([str(program), str(tmp_path / "fw")]) == 0

    # The S-records are the updater's own, and the library reads them
    assert (tmp_path / "fw.srec").read_text() == FIRMWARE.to_srec()
    image = Image.from_srec((tmp_path / "fw.srec").read_bytes())
    assert (image.segments, image.header, image.entry) == (FIRMWARE.segments, "AM057N  mot", 0xfff40011)
    # The binary runs from the first byte to the last, gaps as erased flash
    assert (tmp_path / "fw.bin").read_bytes() == FIRMWARE.to_binary()

    # A flat binary has no addresses in it, so the output gives what rizin needs
    out = capsys.readouterr().out
    assert "0xFFF40000..0xFFF40103" in out and "entry 0xFFF40011" in out and "version '02.04'" in out
    assert f"rizin -a rx -b 32 -m 0xfff40000 {tmp_path / 'fw.bin'}" in out
    assert "2 segments" in out and "0xFFF40100..0xFFF40103" in out


def test_image_name_with_an_extension_names_both_files(tmp_path):
    program = tmp_path / "updater.exe"
    program.write_bytes(updater(FIRMWARE))
    assert fwextract.main([str(program), str(tmp_path / "fw.bin")]) == 0
    assert (tmp_path / "fw.srec").exists() and (tmp_path / "fw.bin").exists()


def test_program_without_records(tmp_path, capsys):
    program = tmp_path / "updater.exe"
    program.write_bytes(b"MZ" + bytes(4096))
    assert fwextract.main([str(program), str(tmp_path / "fw")]) != 0
    assert "no firmware records" in capsys.readouterr().err
    assert not (tmp_path / "fw.srec").exists() and not (tmp_path / "fw.bin").exists()


def block_updater(blocks: dict[int, bytes]) -> bytes:
    """A program file holding the image as the native HX890 updater does: a key, then the table of blocks"""
    key = bytes((n * 37 + 11) & 0xff for n in range(0x80))
    table = b""
    for start, data in blocks.items():
        name = bytes(ord(digit) | 0x80 for digit in f"{start:06X}")
        record = bytearray(name.ljust(0x34, b"\x80"))
        for field, value in (0x0c, start), (0x1c, start + len(data)), (0x20, len(data)):
            record[field:field + 4] = value.to_bytes(4, "little")
        table += bytes(record) + bytes(byte ^ key[n % 0x80] for n, byte in enumerate(data))
    return b"MZ" + bytes(64) + b"Update Version : 02.00\x00" + key + table + b"\xff" * 64


def test_extracts_the_blocks_of_the_hx890_updater(tmp_path, capsys):
    blocks = {0xf40000: b"   2.00    \x00CBTC\x00" + bytes(range(0x90)),
              0xfeff80: b"\xff" * 0x70 + b"AM063N\x00" + b"\xff" * 9}
    program = tmp_path / "Firmware Update for HX890.exe"
    program.write_bytes(block_updater(blocks))

    assert fwextract.main([str(program), str(tmp_path / "fw")]) == 0

    # The library reads the records; the blocks lie where the MCU has them
    image = Image.from_srec((tmp_path / "fw.srec").read_bytes())
    assert image.segments == [Segment(0xff000000 | start, data) for start, data in blocks.items()]
    assert image.header == "AM063N"
    assert (tmp_path / "fw.bin").read_bytes() == image.to_binary()
    out = capsys.readouterr().out
    assert "header 'AM063N'" in out and "version '2.00'" in out and "2 segments" in out and "no entry address" in out
