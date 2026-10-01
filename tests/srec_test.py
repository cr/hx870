import pytest

from hxtool.srec import Image, Segment, SRecordError

# Records as the vendor's HX870 updater holds them: a header, 32 bit addresses, an entry address
VENDOR = "\r\n".join([
    "S00E0000414D3035374E20206D6F74E9",
    "S315FFF40000202030322E303420202020414D30353719",
    "S309FFF400104E000102A2",
    "S309FFF40100DEADBEEFCA",
    "S705FFFD4D842D",
]) + "\r\n"


def test_parse_vendor_records():
    image = Image.from_srec(VENDOR)

    assert image.header == "AM057N  mot"
    assert image.entry == 0xfffd4d84
    assert image.segments == [
        Segment(0xfff40000, b"  02.04    AM057N\x00\x01\x02"),  # adjoining records are one segment
        Segment(0xfff40100, bytes.fromhex("deadbeef")),
    ]
    assert image.size == 24


def test_parse_takes_bytes_and_other_address_widths():
    image = Image.from_srec(b"S1051000AABB85\nS5030001FB\nS9031000EC\n")
    assert image.segments == [Segment(0x1000, b"\xaa\xbb")] and image.entry == 0x1000 and image.header == ""


def test_later_record_overlays_an_earlier_one():
    image = Image([Segment(0x100, b"\x01\x02\x03\x04"), Segment(0x102, b"\xaa\xbb\xcc")])
    assert image.segments == [Segment(0x100, b"\x01\x02\xaa\xbb\xcc")]


@pytest.mark.parametrize("text, complaint", [
    ("S309FFF40100DEADBEEFCB\n", "line 1: checksum"),
    ("S00E0000414D3035374E20206D6F74E9\nS30AFFF40100DEADBEEFC9\n", "line 2: length"),
    ("S409FFF40100DEADBEEFCA\n", "line 1: not an S-record"),
    ("hello\n", "line 1: not an S-record"),
    ("", "no S-records"),
    (b"  02.04    AM057N\x00\xff\xfe", "not S-records"),
])
def test_what_is_not_s_records_is_refused(text, complaint):
    with pytest.raises(SRecordError, match=complaint):
        Image.from_srec(text)


def test_header_and_terminator_alone_are_an_empty_image():
    image = Image.from_srec("S00A0000414D3035374E324B\nS70500000000FA\n")
    assert image.segments == [] and image.size == 0 and image.header == "AM057N2" and image.entry == 0


def test_write_s_records():
    image = Image([Segment(0xfff40100, bytes.fromhex("deadbeef"))], header="AM057N  mot", entry=0xfffd4d84)
    assert image.to_srec() == "S00E0000414D3035374E20206D6F74E9\nS309FFF40100DEADBEEFCA\nS705FFFD4D842D\n"

    # 16 bytes to a record, as the vendor's; no entry address known is written as 0
    lines = Image([Segment(0xfff40000, bytes(range(40)))]).to_srec().splitlines()
    assert [line[:4] for line in lines] == ["S003", "S315", "S315", "S30D", "S705"]
    assert lines[-1] == "S70500000000FA"


def test_round_trip():
    image = Image.from_srec(VENDOR)
    again = Image.from_srec(image.to_srec())
    assert (again.segments, again.header, again.entry) == (image.segments, image.header, image.entry)


def test_binary_views():
    image = Image.from_binary(b"\x01\x02\x03", 0xfff40000)
    assert image.segments == [Segment(0xfff40000, b"\x01\x02\x03")]

    image = Image([Segment(0x100, b"\x01\x02"), Segment(0x106, b"\x03")])
    assert image.to_binary() == b"\x01\x02\xff\xff\xff\xff\x03", "gaps are erased flash"
    assert image.read(0xfe, 6) == b"\xff\xff\x01\x02\xff\xff"
    assert Image().to_binary() == b""


def test_erased_rows_are_dropped():
    data = b"\x11" * 16 + b"\xff" * 40 + b"\x22" * 8
    image = Image([Segment(0x1008, data)], header="AM057N2", entry=5).without_erased()

    assert image.segments == [
        # Rows are aligned to 16 bytes, and one with data keeps its erased bytes: 0x1008..0x101f
        Segment(0x1008, b"\x11" * 16 + b"\xff" * 8),
        Segment(0x1040, b"\x22" * 8),
    ]
    assert (image.header, image.entry) == ("AM057N2", 5)
    assert Image.from_binary(b"\xff" * 64, 0).without_erased().segments == []
