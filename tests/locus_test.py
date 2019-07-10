# -*- coding: utf-8 -*-

from binascii import unhexlify
import pytest

import hxtool.locus as locus


def test_header_parser():
    data_5s = unhexlify("0100010B7F0000000500000000007A0B")
    data_60s = unhexlify("0100010B7F0000003C0000000000430B")
    data_5min = unhexlify("0100010B7F0000002C0100000000530A")
    data_invalid = unhexlify("0100010B7F0000002C010000000053FF")

    header_5s = locus.LocusHeader(data_5s, verify=True)
    header_60s = locus.LocusHeader(data_60s, verify=True)
    header_5min = locus.LocusHeader(data_5min, verify=True)

    _ = locus.LocusHeader(data_invalid, verify=False)
    with pytest.raises(locus.LocusError):
        _ = locus.LocusHeader(data_invalid, verify=True)
    _ = locus.LocusHeader(data_5s + b"\xff"*16, verify=True)  # too much data is okay
    with pytest.raises(locus.LocusError):
        _ = locus.LocusHeader(data_5s[:-1], verify=True)  # insufficient data shall raise

    assert header_5s.IntervalSetting == 5, "Correct 5s speed setting"
    assert header_60s.IntervalSetting == 60, "Correct 60s speed setting"
    assert header_5min.IntervalSetting == 300, "Correct 5min speed setting"

    assert header_5s.LogContent == 0x7f, "Correct log content"
    assert header_5s.LoggingType == 1, "Correct log type"
    assert header_5s.LoggingMode == 11, "Correct log content"


def test_waypoint_parser():
    data = unhexlify("0992245D02200952422861574130000D0027019D")
    data_invalid = unhexlify("0992245D02200952422861574130000D002701FF")

    wp = locus.LocusWaypoint(0x7f, data, verify=True)

    _ = locus.LocusWaypoint(0x7f, data_invalid, verify=False)
    with pytest.raises(locus.LocusError):
        _ = locus.LocusWaypoint(0x7f, data_invalid, verify=True)

    for key in locus.locus_content_descriptor(0x7f)["attributes"]:
        assert key in wp

    assert wp["utc_time"] == 1562677769, "waypoint timestamp is correct"
    assert wp["fix_type"] == 2, "waypoint fix type is correct"
    assert abs(wp["latitude"] - 52.50891) < 1E-5, "waypoint latitude is close enough"
    assert abs(wp["longitude"] - 13.46122) < 1E-5, "waypoint longitude is close enough"
    assert wp["height"] == 48, "waypoint height is correct"
    assert wp["speed"] == 13, "waypoint speed is correct"
    assert wp["heading"] == 295, "waypoint heading is correct"


SAMPLE_DAT = unhexlify(
    b'0100010b7f0000000500000000007a0b0000000000000000000000000000000f'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffff00fc8c1c'
    b'0992245d02200952422861574130000d0027019d0e92245d0246095242715d57'
    b'412e000a001e01b91392245d021e095242715b574128000600da00351892245d'
    b'02a70852421f5a574124000c00c900fc1d92245d023f08524276595741240007'
    b'00c3000a2292245d02b70752428158574125000c00c6004b2792245d02380752'
    b'42ae57574124000900c200e12c92245d02080752426b57574124000000c30017'
    b'3192245d02080752427e57574123000000c300183692245d02080752427e5757'
    b'4123000000c3001f3b92245d02080752427e57574123000000c300124092245d'
    b'02080752427e57574123000000c300694592245d02e306524238575741230004'
    b'00c600c14a92245d027e065242b856574124000900c400da4f92245d020c0652'
    b'42e355574123000a00c400f15492245d028b055242e554574124000b00c4006f'
    b'5992245d020f055242f953574125000a00c500fc5e92245d02910452420e5357'
    b'4124000b00c500936392245d020c0452420a52574123000c00c300306892245d'
    b'027f035242f350574121000c00c400b16d92245d02f8025242d54f57411f000b'
    b'00c500337292245d027f025242e54e57411e000a00c4009b7792245d02090252'
    b'42b04d57411d000a00cb00b27c92245d029f0152427b4c57411d000900cc00e2'
    b'8192245d023e015242724b57411c000800c900b58692245d02de0052426b4a57'
    b'411d000800cf004c8b92245d0293005242cd4957411d000200cd00a19092245d'
    b'0291005242fd4957411e000000cc00889592245d0291005242004a57411e0000'
    b'00cc00739a92245d0291005242004a57411e000000cc007c9f92245d02910052'
    b'42004a57411e000000cc0079a492245d0291005242004a57411e000000cc0042'
    b'a992245d0291005242004a57411e000000cc004fae92245d0291005242ff4957'
    b'411e000100cc00b5b392245d026e0052425d4957411f000500f800c4b892245d'
    b'02a6005242724657411f000f002a01febd92245d02f60052424a4257411e000e'
    b'0027019ac292245d023c0152421b3e57411d000e00250102c792245d027e0152'
    b'42fd3957411c000e002601a6cc92245d02c4015242053657411a000e002601e6'
    b'd192245d0208025242fc3157411a000e002701cbd692245d024d025242002e57'
    b'4119000c0026016adb92245d027b0252427c2b574119000700260123e092245d'
    b'02a9025242152957411a0008002b01a0e592245d02bc025242e4275741190002'
    b'00240149ea92245d02c402524277275741180000002801a2ef92245d02ca0252'
    b'428627574118000000280158f492245d02db02524239275741180003006601a0'
    b'f992245d02480352426f28574118000c00190017fe92245d02e2035242622a57'
    b'4117000b001900bd0393245d025d045242b52b5741170008001400210893245d'
    b'02bc045242ae2c5741180007001700d40d93245d02fa0452425e2d5741180003'
    b'001600631293245d0216055242cd2d57411a00000018000d1793245d02130552'
    b'42d22d57411b0000001800131c93245d0213055242d22d57411b000000180018'
    b'2193245d0213055242d22d57411b0000001800252693245d0213055242d22d57'
    b'411b0000001800222b93245d0219055242f22d57411b0002002900363093245d'
    b'0279055242e82e57411b000a000a007f3593245d0207065242343057411a000d'
    b'001800d13a93245d0299065242ad3157411a000b001700d13f93245d020b0752'
    b'42be3257411a0009001400564493245d02600752429733574118000500140060'
    b'4993245d0278075242c6335741190000001600224e93245d0280075242d83357'
    b'41190003001800ce5393245d02d40752423d35574119000a002100545893245d'
    b'023f08524263365741170008001400df5d93245d02b40852428f37574117000c'
    b'001400b86293245d0249095242c938574118000c001100386793245d02d00952'
    b'42c239574119000b000e00b76c93245d02450a5242653a5741190009000b0089'
    b'7193245d028a0a5242ae3a57411a0004000500907693245d02a50a5242cc3a57'
    b'411b0002000b00d37b93245d02f00a52423a3b57411d00090011006b8093245d'
    b'02740b52421e3c57411e000b000c002a8593245d02e40b5242073d57411f0007'
    b'000f00a98a93245d02280c5242993d5741210004000d00cc8f93245d025a0c52'
    b'42ff3d5741220004000c00df9493245d02c00c5242b33e5741230009000c001d'
    b'9993245d02490d52429a3f574123000c000d00b49e93245d02ec0d5242c94057'
    b'4123000d000c003aa393245d02610e524284415741240009000d00c7a893245d'
    b'02770e524296425741280007006000a4ad93245d02400e5242b14557412d000b'
    b'007200adb293245d02f60d52425a49574131000d007600feb793245d02a40d52'
    b'423e4d574135000e007700cfbc93245d024c0d52425251574138000e00770051'
    b'c193245d02150d5242b454574136000c0066008bc693245d02f20c52422e5857'
    b'4136000a006900f5cb93245d02cc0c52427f5b574136000e00690090d093245d'
    b'029f0c5242d75f574138000e0068007bd593245d02610c5242e863574139000e'
    b'007b0091da93245d02ff0b5242526757413a000d007d00bfdf93245d02830b52'
    b'42a969574138000c009800d5e493245d021b0b5242e06a5741350003008e0028'
    b'e993245d02180b5242296b5741320000008e00eaee93245d02180b52422e6b57'
    b'41320000008e00eaf393245d02170b5242366b5741320000008e00e0f893245d'
    b'02170b5242396b5741320000008e00e4fd93245d02170b5242396b5741320000'
    b'008e00e10294245d020c0b5242616b5741320006009600440794245d028b0a52'
    b'42646d5741320010009500d10c94245d02e609524231705741320010008d00e4'
    b'1194245d024e0952423d73574131000e008e00401694245d02d7085242af7557'
    b'4130000b008c004d1b94245d0279085242b97757412f000a008c00e42094245d'
    b'0224085242c47957412e000a008a00f62594245d02c2075242c07b57412d000a'
    b'008d00182a94245d02720752425e7d57412a0006008b00322f94245d023b0752'
    b'42c67e5741280005008700e83494245d0210075242797f574127000700940078'
    b'3994245d02da06524278815741260006008a005f3e94245d02bb065242ad8257'
    b'41260000006f000c4394245d02b8065242c1825741260000006f001e4894245d'
    b'02b8065242c1825741260000006f00154d94245d02b8065242c1825741260000'
    b'006f00105294245d02b8065242c1825741260000006f000f5794245d02b70652'
    b'42cc825741260000006f00085c94245d02b7065242d0825741260000006f001f'
    b'6194245d02b7065242db825741260000006f00296694245d02b7065242df8257'
    b'41260000006f002a6b94245d02b7065242df825741260000006f00277094245d'
    b'02b7065242df825741260000006f003cffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    b'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff')


def test_locus_parser():
    loc = locus.Locus(SAMPLE_DAT, verify=True)
    assert len(loc) == 124
    assert abs(loc[0]["latitude"] - 52.50891) < 1E-5, "log's first waypoint latitude is close enough"
    with pytest.raises(IndexError):
        _ = loc[124]
    for wp in loc:
        assert type(wp) is locus.LocusWaypoint
        assert "latitude" in wp
        assert "longitude" in wp
        assert "height" in wp
