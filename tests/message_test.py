# -*- coding: utf-8 -*-

import pytest

from hxtool.protocol import Message, ProtocolError


def test_unary_cmd_message_parser():
    m = Message(parse="#CMDOK\r\n")
    assert m.type == "#CMDOK", "Unary message type is parsed fine"
    assert type(m.args) is list and len(m.args) == 0, "Unary message args parsed fine"
    assert m.checksum_recv is None, "Unary message checksum parsed fine"
    assert m.checksum is None, "Unary message checksum is calculated fine"
    assert m.validate(), "Unary message checksum is valid"
    assert m == Message(parse="#CMDOK"), "Unary message parsing needs no newline"
    assert m == Message(parse=b"#CMDOK\r\n"), "Unary message string and bytes parsing equally"
    assert str(m) == "#CMDOK\r\n", "Parsed unary message rebuilds fine"


def test_cmd_message_parser():
    msg = "#CEPDT\t0100\t0A\t414D3035374E32FFFFFF\t11\r\n"
    m = Message(parse=msg)
    assert m.type == "#CEPDT", "Message type is parsed fine"
    assert m.args == ["0100", "0A", "414D3035374E32FFFFFF"], "Message args parsed fine"
    assert m.checksum_recv == "11", "Message checksum parsed fine"
    assert m.checksum == "11", "Message checksum is calculated fine"
    assert m.validate(), "Message checksum is valid"
    assert m == Message(parse=msg.rstrip("\r\n")), "Message parsing without newline"
    assert m == Message(parse=msg.encode("ascii")), "Message string and bytes parsing equally"
    assert str(m) == msg, "Parsed message rebuilds fine"


def test_unary_cmd_message_builder():
    m = Message("#CMDOK")
    assert m.type == "#CMDOK", "Built unary message has right type"
    assert m.args == [], "Built unary message has no args"
    assert m.checksum_recv is None, "Built unary message has no received checksum"
    assert m.checksum is None, "Built unary message has no checksum"
    assert m.validate(), "Built unary message validates"
    assert str(m) == "#CMDOK\r\n", "Built unary message rebuilds fine"

    # Testing unary message with checksum
    m = Message("#CVRRQ")
    assert m.checksum == "6E", "Unary message with checksum gets checksum"
    assert m.validate(), "Unary message with checksum validates"


def test_cmd_message_builder():
    msg = "#CEPDT\t0100\t0A\t414D3035374E32FFFFFF\t11\r\n"
    m = Message("#CEPDT", ["0100", "0A", "414D3035374E32FFFFFF"])
    assert m.type == "#CEPDT", "Built message has right type"
    assert m.args == ["0100", "0A", "414D3035374E32FFFFFF"], "Built message has right args"
    assert m.checksum_recv is None, "Built message has no received checksum"
    assert m.checksum == "11", "Built message has right calculated checksum"
    assert m.validate(), "Built message validates"
    assert str(m) == msg, "Built message rebuilds fine"


def test_message_equality():
    msg_a = "#CEPDT\t0100\t0A\t414D3035374E32FFFFFF\t11\r\n"
    msg_b = "#CEPDX\t0100\t0A\t414D3035374E32FFFFFF\t1D\r\n"
    msg_c = "#CEPDT\t1100\t0A\t414D3035374E32FFFFFF\t10\r\n"
    msg_d = "#CEPDT\t0100\t0A\t414D3035374E32FFFFFF\t22\r\n"  # Broken message

    a = Message(parse=msg_a)
    b = Message(parse=msg_b)
    c = Message(parse=msg_c)
    d = Message(parse=msg_d)
    e = Message(parse=msg_a.lower())

    assert a != b, "Messages not equal with different type"
    assert a != c, "Messages not equal with different args"
    assert a != d, "Messages not equal with different checksum"
    assert a != e, "Messages not equal with different case"

    m = Message("#CEPDT", ["0100", "0A", "414D3035374E32FFFFFF"])
    assert a.type == m.type
    assert a.args == m.args
    assert a.checksum == m.checksum
    assert a.checksum == "11"
    assert a.checksum_recv == "11"
    assert m.checksum_recv is None
    assert a == m, "Parsed message equals built"


def test_broken_cmd_message_parsing():
    msg = "#CEPDT\t0100\t0A\t414D3035374E32FFFFFF\t22\r\n"
    assert not Message(parse=msg).validate(), "Broken checksum is not valid"

    m = Message(parse="#CMDDT\t0100\t44")  # Broken Checksum
    assert not m.validate(), "Message with broken checksum parses, but does not validate"

    with pytest.raises(ProtocolError):
        Message(parse="FOOBAR")  # Invalid message

    # TODO: test unary type with args


def test_message_checksums():
    assert Message("#CMDOK").checksum is None
    assert Message("#CMDOK").checksum_recv is None
    assert Message("#CMDOK").validate()
    assert Message(parse="#CMDOK").checksum is None
    assert Message(parse="#CMDOK").checksum_recv is None
    assert Message(parse="#CMDOK").validate()

    assert Message("#CVRRQ").checksum == "6E"
    assert Message("#CVRRQ").checksum_recv is None
    assert Message("#CVRRQ").validate()
    assert Message(parse="#CVRRQ\t6E").checksum == "6E"
    assert Message(parse="#CVRRQ\t6E").checksum_recv == "6E"
    assert Message(parse="#CVRRQ\t6E").validate()

    assert Message(parse="#CVRRQ\t6F").checksum == "6E"
    assert Message(parse="#CVRRQ\t6F").checksum_recv == "6F"
    assert not Message(parse="#CVRRQ\t6F").validate()
    # Received checksum should have precedence over calculated
    assert str(Message(parse="#CVRRQ\t6F")) == "#CVRRQ\t6F\r\n"

    assert Message("#CEPDT", ["0100", "0A", "414D3035374E32FFFFFF"]).checksum == "11"
    assert Message("#CEPDT", ["0100", "0A", "414D3035374E32FFFFFF"]).checksum_recv is None
    assert Message("#CEPDT", ["0100", "0A", "414D3035374E32FFFFFF"]).validate()
    assert Message(parse="#CEPDT\t0100\t0A\t414D3035374E32FFFFFF\t11").checksum == "11"
    assert Message(parse="#CEPDT\t0100\t0A\t414D3035374E32FFFFFF\t11").checksum_recv == "11"
    assert Message(parse="#CEPDT\t0100\t0A\t414D3035374E32FFFFFF\t11").validate()

    assert Message(parse="#CEPDT\t0100\t0A\t414D3035374E32FFFFFF\t22").checksum == "11"
    assert Message(parse="#CEPDT\t0100\t0A\t414D3035374E32FFFFFF\t22").checksum_recv == "22"
    assert not Message(parse="#CEPDT\t0100\t0A\t414D3035374E32FFFFFF\t22").validate()

    assert Message("$PMTK", ["183"]).checksum == "38"
    assert Message("$PMTK", ["183"]).checksum_recv is None
    assert Message("$PMTK", ["183"]).validate()
    assert Message(parse="$PMTK183*38").checksum == "38"
    assert Message(parse="$PMTK183*38").checksum_recv == "38"
    assert Message(parse="$PMTK183*38").validate()

    assert Message(parse="$PMTK183*99").checksum == "38"
    assert Message(parse="$PMTK183*99").checksum_recv == "99"
    assert not Message(parse="$PMTK183*99").validate()

    assert Message("$PMTK", ["001", "622", "3"]).checksum == "36"
    assert Message("$PMTK", ["001", "622", "3"]).checksum_recv is None
    assert Message("$PMTK", ["001", "622", "3"]).validate()
    assert Message(parse="$PMTK001,622,3*36").checksum == "36"
    assert Message(parse="$PMTK001,622,3*36").checksum_recv == "36"
    assert Message(parse="$PMTK001,622,3*36").validate()

    assert Message(parse="$PMTK001,622,3*99").checksum == "36"
    assert Message(parse="$PMTK001,622,3*99").checksum_recv == "99"
    assert not Message(parse="$PMTK001,622,3*99").validate()


def test_nmea_sentence_parser():
    m = Message(parse="$PMTK183*38\r\n")
    assert m.type == "$PMTK"
    assert m.args == ["183"]
    assert m.checksum_recv == "38"
    assert m.checksum == "38"
    assert m.validate()

    m = Message(parse="$PMTK001,183,3*3A\r\n")
    assert m.type == "$PMTK"
    assert m.args == ["001", "183", "3"]
    assert m.checksum_recv == "3A"
    assert m.checksum == "3A"
    assert m.validate()
    assert m == Message(parse="$PMTK001,183,3*3A")


def test_nmea_sentence_builder():
    m = Message("$PMTK", ["001", "183", "3"])
    assert m.type == "$PMTK"
    assert m.args == ["001", "183", "3"]
    assert m.checksum_recv is None
    assert m.checksum == "3A"
    assert m.validate()
    assert m == Message(parse="$PMTK001,183,3*3A")
    assert str(m) == "$PMTK001,183,3*3A\r\n"


def test_nmea_lowercase_edge_case():
    # We have observed this one strange NMEA sentence on the line
    # containing one lowercase letter. Internal meddling with the
    # case would result in an invalid checksum, as is must be
    # calculated with that letter's lowercase byte representation.
    msg = "$PMTKLOG,1,1,b,127,60,0,0,1,1,0*26\r\n"
    assert Message(parse=msg).checksum == "26", "Lowercase NMEA edge case is observed"
