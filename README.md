# hxtool

Here's my collection of experimental Python code and reverse engineering notes
for hacking the Standard Horizon HX-style maritime radios by Yaesu. Currently supported
are the *HX870* and *HX890* model series. The code also works on FT750-style aviation
radios, which share the same hardware platform, to some degree as well, but that
functionality is not exposed on the command line frontend, yet.

## Disclaimer

> **It is very easy to completely screw up your radio with low-level tooling like this,**
> **so BE EXTREMELY CAREFUL and get help from your geek friend if you're out of your depth.**
> **The software probably contains mistakes that can permanently damage your radio.**
> **Although it has been used a lot on my personal radio, I cannot guarantee**
> **that it works on yours. Use it AT YOUR OWN RISK!**

## Installation

The code is hardly documented and largely user-unfriendly and I am feeling
slightly awful about it. However, you may install the command line tool into your
(preferably virtual) *Python 3.6+* environment via
`pip install git+https://github.com/cr/hx870`. Then see `hxtool --help` for usage
information.

`hxtool` works on *Linux*, *Mac OS*, and *Windows 10* (and probably older ones, too) and it
has been extensively tested with the HX870 radio without any ill effects when used appropriately.

The HX890 portion has only been tested sporadically, and be mindful of the disclaimer above.

## Config DAT file dump format

This work extends on [Arne Johannessen's work](https://johannessen.github.io/hx870/).
It is still incomplete and currently only documented in form of a
[010 Editor template](hx870dat.bt).

If you can C and figure out their custom lingo for defining bitfields, you'll have
no trouble reading it.

## Experimantal support for GPS log

GPS logs can now be exported and erased. Supported output formats are GPX, JSON, and raw log bytes.
`hxtool gpslog` should dump some log content to screen if radio is in programming mode.
See `hxtool gpslog --help` for usage info.

## HX870 USB protocol

The hardware exposes three USB endpoints, EP0, EP1, and EP2. EP0 is a control endpoint.
URB_BULK data is sent from EP1 and received on EP2. Advertises itself as AT command interface,
hence device is captured by the USB Serial kernel driver on Linux and Mac OS X.

Radio is exposed as /dev/tty.usbmodem1411 on Mac OS X.

### Protocol handshake sequence

* `P` - Sent by host without trailing \r\n, unacknowledged
* `0` - Sent by host without trailing \r\n, unacknowledged
* `ACMD:002\r\n` - StartCP, sent by host in the beginning, unacknowledged
* `#CMDSY\r\n` - Sync command, radio acknowledges with #CMDOK\r\n

### #CMD message format

Tab-separated message fields, concluded by checksum and \r\n. Example:

`b'#CEPRD\tARG\tARG\t...ARG\tCHECKSUM\r\n'`

Checksum is XOR reduce over raw bytes until and including the last \t.

There are messages with and without arguments. All messages with arguments have a checksum,
and most messages (there are exceptions) without arguments do not.

Unary messages with checksum observed: #CVRRQ

Radio starts repeating messages if you don't acknowledge with #CMDOK or similar, so timing is important.

### #CMD messages

* `#CCPWC` - Appears in firmware 02.03

* `#CDFCB`
* `#CDFER`
* `#CDFIN`
* `#CDFRR`
* `#CDFSR`
* `#CDFWR`

* `#CEPDT ADDRESS4 LENGTH <HEXBYTES>` - Reply from radio after CEPRD
* `#CEPRD ADDRESS4 LENGTH` - Read from config flash
* `#CEPSD 00` or `01` - Radio status, 00 if ready to receive new writes, 01 if not ready
* `#CEPSR 00` - Radio replies with flash status #CEPSR message
* `#CEPWR ADDRESS4 LENGTH <HEXBYTES>` - Write to config flash

* `#CIORD` - Appears in firmware 02.03

* `#CFLCB 000000` - CheckBlank
* `#CFLER 000000` - FlashErase
* `#CFLID AM057N\0\0\0\0` or `AM057N2\0\0\0` - FlashID, firmware flasher tries both during hardware detection/setup
* `#CFLMC 01` - CommandMd, sent by firmware flasher before #CFLER
* `#CFLMC 03` - CommandMdr, sent by firmware flasher after last #CFLWR
* `#CFLRD` - Appears in firmware 02.03, perhaps firmware flash read? Radio says #CMDUN
* `#CFLSD 10` - Radio status response observed during hardware detection
* `#CFLSR 00` - CheckStatus
* `#CFLWR ADDRESS6 LENGTH <HEXBYTES>` - Write to firmware flash

* `#CMDER` - CmdError
* `#CMDNR STANDARD\x20HORIZON` - CommandNr, radio answers with #CMDND
* `#CMDND AM057N` or `AM057N2` - Radio reply after #CMDNR request
* `#CMDOK` - CmdStatusOK, message Acknowledgement
* `#CMDSM` - CmdCheckSum error
* `#CMDSY` - Sync, sent by host, acknowledged by radio with #CMDOK
* `#CMDUN` - CmdUnknown

* `#CRPWC`

* `#CSTDQ`
* `#CSTRQ`

* `#CVRDQ 02.03` - Reply with firmware version
* `#CVRRQ` - Radio replies with firmware version in #CVRDQ message


### NMEA-style messages

Implemented as standard-compliant proprietary $P NMEA sentences.

`b'$PMTKarg,arg,...,arg*checksum\r\n'`

Checksum is XOR reduce over the raw bytes between $ and *.

#### `$PMTK` Messages

* `$PMTK251,115200*1F` - Sent to radio before GPS Log Transfer

* `$PMTK183*38` - StatusLog, sent to radio
* `$PMTKLOG,FULL_STOP*3E` Interspersed warning by radio after log commands
* `$PMTKLOG,8,1,b,127,5,0,0,1,1430,22*1B` - Radio reply to StatusLog
  * `8`: number 4k flash pages used by log (expect to be transfered)
  * `1`: unknown from raw log header offset 2
  * `b`: unknown from raw log header offset 3
  * `127`: unknown from raw log header offset 4:6
  * `5`: logger interval (in seconds) when log was started
  * `0`: unknown
  * `0`: unknown
  * `1`: unknown
  * `1430`: number of log slots used (max. 6432)
  * `22`: log usage percentage
* `$PMTK001,183,3*3A` - Radio ACK of StatusLog
* `$PMTK622,1*29` - ReadLog, sent to radio
* `$PMTKLOX,0,43*6E` - Radio response with data
  * Expect 43 `LOX,1` log lines
* `$PMTKLOX,1,0,0100010B,7F000000,...,FFFFFFF*27` - Log data
* `$PMTKLOX,1,1,FFFFFFFF,FFFFFFFF,...,FFFFFFF*59` - Log data
* `$PMTKLOX,1,2,FFFFFFFF,FFFFFFFF,...,FFFFFFF*5A` - Log data
* `...`
* `$PMTKLOX,1,42,FFFFFFFF,FFFFFFFF,...,FFFFFFF*6E` - Log data
* `$PMTKLOX,2*47` - From radio, end of log
* `$PMTK001,622,3*36` - Radio ACK of ReadLog

* `$PMTK184,1*22` - EraseLog
* `$PMTK001,184,3*3D` - Radio ACK EraseLog

* `$PMTK...` - numArray
* `$PMTK0..$PMTK8`


#### `$PMTK` sentences appearing in firmware 02.03:

* `PMTK183*`
* `PMTK184,0*`
* `PMTK185,1*`
* `PMTK186,1*`
* `PMTK187,1,1*`
* `PMTK225,0*`
* `PMTK251,0*`
* `PMTK301,0*`
* `PMTK313,0*`
* `PMTK386,0*`
* `PMTK605*`
* `PMTK622,0*`


#### Strings appearing in YCE01 firmware flasher

* `OK` - AnswerOK, not seen from HX870
* `ERROR` - AnswerERROR, not seen from HX870

These haven't been observed on the line, yet.

### Factory reset

After factory reset, the following values are present at offset 0x0110 in config flash:

`17 12 26 18  53 52 18 88  80 4E 00 06  11 76 21 45`

After a full reboot, those values are replaced by all FF.

## Testing notes

 - `pytest -v` - running the test suite
 - `pytest --cov=hxtool --cov-report=term` - running test coverage
