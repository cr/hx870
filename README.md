# hxtool

Here's my collection of experimental Python code and reverse engineering notes
for hacking the Standard Horizon HX-style maritime radios by Yaesu. Currently supported
are the **HX870**, **HX890**, and **GX1400** model series.

Radios in "CP mode" are usually automatically detected when connected.
You can also manually select devices with the `--tty` or `--model` CLI options.

The GX1400 has no USB port and is connected to a RS-232 style serial port.
The GX1400 connector wiring is as follows. See the [SHsync](https://mbof.github.io/hx/) docs for a
[diagram of the DE-9 connector pin-out](https://github.com/mbof/hxsync/blob/main/gx.md#wiring-diagram).

* `RxD`: accessory cable white
* `TxD`: accessory cable yellow
* `GND`: accessory cable green + speaker cable shield

The code also works on FT750-style aviation
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
(preferably virtual) *Python 3.10+* environment via
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

## Experimental support for GPS log

GPS logs can now be exported and erased. Supported output formats are GPX, JSON, and raw log bytes.
`hxtool gpslog` should dump some log content to screen if radio is in programming mode.
See `hxtool gpslog --help` for usage info.

## Flashing a config image

`hxtool config --flash FILE` writes an image back, but leaves the device's identity alone:
the config magic is checked and never written, the flash ID is skipped, and so is device
state the firmware maintains (on the HX8xx the last-turned-off timestamp and position).
`--force` flashes despite a magic or region mismatch and writes that device state as well;
`--force-flashid` writes the flash ID from the image. Both together write everything but
the magic.

## Raw memory access

`hxtool poke <hex offset> [<hex data>] [-l <hex length>]` reads (peek) or writes (poke)
bytes of the config memory directly, at most one transfer chunk at a time. It skips the
dump-edit-flash cycle for small changes, and it corrupts the device just as easily.
See the disclaimer above.

## Firmware flash access

`hxtool firmware --readto FILE` reads the firmware into a file. Verified on an HX870 with
firmware 02.04, where the image read is byte for byte the one the vendor's updater carries,
and on an HX891BT with firmware 1.00 (a minute and a half for 704 kB).

`hxtool firmware --writefrom FILE` assesses an image against the model (it lies within the
firmware area, names a version, carries the model's flash ID, has content) and reports it
next to the version the radio runs. It writes nothing. An image that fails the assessment
gets a warning not to write it, and a non-zero exit status.

With `--really` the assessment is only advice: the flash is erased and the image written,
whatever the assessment said. The one thing `--really` cannot do is write an image that
leaves the firmware area. Writing follows the vendor's updater step by step but has not
been run against a radio yet.

A read or write leaves the radio in flash mode. There it answers the firmware commands and
nothing else: no config access, no GPS, and no answer to the `?` that tells CP mode, so
hxtool takes a radio left in flash mode for one in NMEA mode. `--reboot` restarts the radio
when the command went through (on its own: `hxtool firmware --reboot`), after which it is in
its normal mode, not CP mode. After a failure the radio is left as it is. Without `--reboot`,
switch the radio off and on.

The file is in Motorola S-records, the form the vendor's updaters hold their images in,
whatever its name. S-records carry the address of every byte, so the image itself says
where it goes, and a write sends only the chunks the image has bytes in; the rest of the
erased area is left alone. A read leaves erased flash out of the file. `--binary` is the
override, for both directions: the file is then the firmware area as it lies, from its
first byte, and the log says where that is (to load it there:
`rizin -a rx -b 32 -m 0xfff40000 FILE`).

The firmware area is 0xF40000..0xFEFFFF (0xFFF40000..0xFFFEFFFF to the MCU and in the
S-records; the flash commands carry the low 24 bits) on the HX870 and the HX890, per the
write maps of the vendor's updaters, and on the HX891BT, which has no updater: the image
read from one fills that area the same way. No HX890 has been read. The GX1400 has no
firmware functions in hxtool.

What the images of the HX870 (02.03, 02.04) and the HX891BT (1.00) have in common:

* The version, blank padded to eleven bytes, at the start of the area, followed by the
  table of `#` commands.
* One long run of code and data that ends with the start-up code (stack pointers, a call).
  The vendor's S-records name that as the entry address.
* A few small pieces of code from 0xFEEE00 on, and erased flash in between.
* A flash ID in the last 16 bytes of the area: `AM057N` on the HX870, and `AM063N`, the
  HX890's, on the HX891BT. The ID the radio names itself by (`AM057N2`, `AM070N`) is
  elsewhere in the image.

For users of the library: the model instance carries the firmware handler as `hx.firmware`
(`read_image()`, `check_image()`, `write_image()`), next to `hx.config` and `hx.gps`. It
knows where the model's firmware lies (`hxtool.firmware`). The flash session below it is
`hx.firmware.p`, a `FirmwareProtocol` with nothing model specific in it:
`enter_flash_mode()`, `read()`, `write()`, `erase()`, `reboot()`, `poweroff()`. An image is
an `hxtool.srec.Image`: address segments, read from and written to S-records or flat binary.
The radio grants the flash-mode handshake once per power-on; the session enters flash mode
when a transfer needs it and stays there, so a write and a read back fit into one session.
Flash mode outlasts the connection: on an HX870 and an HX891BT a second connection read the
whole area again without a handshake (a `FirmwareProtocol` made with `active = True`),
identical to the first read.
`hx.reboot()` ends flash mode by restarting the radio, and `hx.poweroff()` by switching it
off; both enter flash mode first if need be, and they are the known ways to restart or
switch off a radio in CP mode by software. `tools/fwextract.py` extracts the images from a
vendor updater.

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

### Line settings and timing

Observed in USB captures of the vendor software talking to an HX870, and verified on
an HX870 (firmware 02.04) and an HX891BT (firmware 1.00):

* The vendor software sets the CDC line coding to 115200 8N1 and never asserts DTR
  (RTS is high only briefly while the port is opened). Before the host sets a line
  coding, the radio reports one of all zeros. `hxtool` does the same now.
* A reply that is not acknowledged with `#CMDOK` is sent again after about 205 ms.
* Config memory is transferred in chunks of 0x40 bytes. Longer reads return garbled
  data (the HX870's reply buffer wraps), although the length field would allow 0xff.
* The vendor software sends `#CEPSR` before every read and write and waits for
  `#CEPSD 00`. The radios answer reads correctly without that, at about 4000 bytes/s
  instead of 2000; `hxtool` only polls before a write and before the first read after one.
* A session ends with the last `#CMDOK`; there is no command for leaving CP mode.
* The GPS log arrives at about 960 characters/s whatever the line coding: the GPS
  module's own UART runs at 9600 baud until it is switched with `$PMTK251`.

### How the vendor software does it

Read from the vendor's programming software: YCE03 1.0.0.24 and YCE15 2.0.1.0 for the
HX870, YCE20 3.0.0.0 for the HX890 and HX891BT. They are builds of one C# code base, and
their protocol code is the same except where noted.

* Port: 115200 8N1, read and write timeout 2000 ms. DTR and RTS are left alone.
* Every operation starts with `P`, `0`, `ACMD:002`, then `#CMDSY` twice. Config read and
  write then ask for the firmware version (`#CVRRQ`); a version of `--.--` is refused.
* A command is repeated up to 5 times, each with a 2000 ms wait for the reply
  (`global.ini`: `Timeout`, `RetryCount`, `RetryInterval`).
* `#CEPSR` is sent before every `#CEPRD` and `#CEPWR`. Any `#CEPSD` reply is answered with
  `#CMDOK`; on `#CEPSD 01` the poll is repeated after 40, 80, 160, ... ms.
* A `#CEPDT` reply must end in CR LF, have five fields and a correct checksum, else the
  read is repeated. The receive code takes whatever one read from the port returns as one
  message; it relies on the radio sending a message in one piece.
* Config read: all of the memory in 0x40-byte chunks, or only the fields a function needs.
* Config write: first the two magic bytes at offset 0 and at the end of the memory and
  the region byte at 0x010F are read. The write is refused unless both magics match the
  image. A differing region asks for confirmation; region 0xFF on either side is refused
  (YCE20: 0x10 as well). Then the write areas are sent in 0x40-byte chunks. Nothing is
  read back afterwards.
* The write areas are tables embedded in the program, one for a full write and one per
  function (set MMSI, set ATIS, the resets, clearing the DSC logs). Setting the MMSI
  writes 0x00B0..0x00B5 and 0x00CE, setting the ATIS code 0x00B6..0x00BB and 0x00CF
  (YCE03: without 0x00CE and 0x00CF).
  Never written: the magics, 0x000F, the model names at 0x0078, 0x0088, 0x0098 and
  0x00A8 (8 bytes each), the flash ID at 0x0100..0x010E, and 0x0280..0x02CF. YCE03 and
  YCE20 leave out more, among it the MMSI and ATIS code in a full write.
* GPS log transfer: `#CEPSR`, then `$PMTK251,115200`, a fixed wait of 3 seconds,
  `$PMTK183` (repeated up to 5 times on a timeout or when `$PMTK010,002` arrives), then
  `$PMTK622,1`. Data lines are checked by their checksum only; the header line is used
  for the progress bar alone, line numbers are not compared, and the transfer ends with
  `$PMTK001,622,3`. Five timeouts in a row end it with an error.
* The speed is never switched back. The vendor leaves the module at 115200 and relies
  on the radio finding it there at the next power-up.
* GPS log erase: `$PMTK184,1` at 9600 baud, done when `$PMTK001,184,3` arrives.
* A log record is 20 bytes: time (4, seconds since 1970), fix (1), latitude and longitude
  (4 each, float), height (2, m), speed (2, taken as m/s), heading (2), checksum (1).
  YCE20 exports GPX and maps the fix byte: bit 2 to `dgps`, bit 1 to `3d`, bit 6 to `2d`.

### GPS module speed

`$PMTK251,115200` switches the line between the radio and its GPS module to 115200 baud,
and a log transfer then runs five to six times faster. `hxtool gpslog` reads at 9600 baud
on every model. `--fast` switches up for the transfer and always back to 9600, which the
radio's firmware expects, and checks that the module answers there. It is unstable for
the reasons below: a failed fast transfer is an error and is not repeated at 9600, and if
the module answers at no speed afterwards, `hxtool` says so, saves the log if it had been
read completely, and asks for the radio to be restarted in CP mode.

How the radio handles it, read from the HX870's firmware 02.03 and confirmed by
measurement on 02.04:

* The radio does not pass `$PMTK251` on. It accepts the speeds `0` (the module's default),
  `4800`, `9600`, `14400`, `19200`, `38400`, `57600` and `115200` and then runs a sequence
  of its own: an empty sentence to wake the module, a wait of up to half a second,
  `PMTK251` at the old speed, its own UART to the new speed, `PMTK225,0` at the new speed,
  and a wait of up to half a second for the acknowledgement.
* While that sequence runs, about a second, every `$PMTK` sentence from the host is
  dropped without a reply. The switch itself is not acknowledged either. A switch to 9600
  while at 9600 does no harm (`$PMTK010,003` and `$PMTK001,225,3` show up); a switch to
  115200 while at 115200 leaves the module silent until it is switched down (5 of 5).
* The host cannot tell at which speed radio and module talk: as long as both agree,
  everything works at either speed, only faster and with the losses described below.
* All other `$PMTK` sentences are forwarded to the module with a freshly computed
  checksum. In the other direction the radio forwards PMTK sentences only; the module's
  position sentences are parsed by the radio itself, in CP mode too.
* In CP mode the radio's UART clock is 18 MHz, so its "115200" is 112500 baud (2.3 % slow)
  and its "9600" is 9534 baud. That is within what the link tolerates. In normal operation
  the clock is 12 MHz and "115200" comes out as 125000 baud, 8.5 % fast, which a module at
  115200 will not decode.
* The module keeps its speed when the radio is switched off. When it starts, the radio
  looks for the module at 115200 and 9600 only, and going by the code just read, only a
  start into CP mode can reach a module at 115200 (not tried). A module left at another
  speed is lost to the radio (no position fix) until the radio's side is stepped to that
  speed. `hxtool` does that whenever the module does not answer: it tries 9600 and
  115200, then 57600, 38400, 19200, 14400 and 4800, and switches a module it finds back
  to 9600.

What goes wrong at the high speed (HX870, several hundred switches):

* After one switch in five to twelve, depending on what the module is sending at the
  time, the module is deaf. The firmware switches its transmitter off one character too
  early when its task timer happens to fall into that millisecond, which cuts the line
  feed off its own `PMTK251`. The module then stays at the old speed and only executes the
  command when the next complete sentence arrives. Repeating the request does not help.
  Switching down and up again does: the dump then works at the high speed (11 of 11).
  Switching down, up and down brings both back to 9600.
* The first line of the dump, `$PMTKLOX,0,<lines>`, gets lost in up to one transfer in
  six. The radio has room for one received sentence at a time and drops the next one if
  its main loop has not taken the first yet. At 115200 the short header is dropped when
  it directly follows one of the module's position sentences. The data lines are long
  enough to get through; none was lost in about 400 transfers. For the same reason the
  reply to a short command like `$PMTK000` cannot be relied on at the high speed.
* After a complete fast transfer, the switch back to 9600 can leave the module silent for
  good: no speed brings an answer any more. Seen once on the HX870 (after about 450 pairs
  of switches; switching the radio off and on cured it) and once on the HX891BT (after
  its fourth fast transfer). Not understood. The vendor's software never switches back.
* The module cannot be stopped in the middle of a log dump: after an interrupted read it
  goes on sending for the rest of the dump (ten seconds per 4 kB sector at 9600 baud).
  Its output shares the line with the replies to `#` commands, so `hxtool` skips GPS
  sentences while it waits for such a reply, recognises CP mode although sentences stream
  in, and waits for a busy module instead of treating it as deaf.

HX891BT (firmware 1.00), and by assumption the HX890: the same failures, more often. After
a switch the module also reports a restart now and then (`$PMTK011,MTKGPS`). Not analysed;
the HX870's firmware restarts the module by itself when it receives a sentence with an
overlong field, which a speed mismatch can produce. The vendor's software reckons with a
restart: `$PMTK010,002` makes it repeat its request.

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
* `#CFLID AM057N\0\0\0\0` or `AM057N2\0\0\0` - FlashID, firmware flasher tries both during hardware detection/setup.
  A wrong ID is answered with `#CFLSD 10`, after which the radio replies `#CMDER` until `#CMDNR` is sent again;
  the right one with `#CFLSD 00`. The flasher follows every command with a `;` byte.
* `#CFLMC 01` - CommandMd, sent by firmware flasher before #CFLER. Enters flash mode: from then on the radio
  answers `#CMDSY` and the `#CFL` commands, and `#CMDUN` to the rest (`#CVRRQ`, `#CEPSR`, `#CMDNR`; HX891BT)
* `#CFLMC 02` - Switches the radio off, without an answer (HX891BT). Sent by the HX890 firmware flasher if
  `#CFLMC 03` is not acknowledged
* `#CFLMC 03` - CommandMdr, sent by firmware flasher after last #CFLWR. The radio restarts into its normal mode
* `#CFLRR ADDRESS6 LENGTH` - Read from firmware flash, answered with `#CMDOK` and `#CFLRD ADDRESS6 LENGTH
  <HEXBYTES>`, which the host acknowledges with `#CMDOK`. The vendor's updater can build the request
  and parse the reply but never sends it. Verified on an HX870 (firmware 02.04), 0x80 bytes per request.
* `#CFLRD` - Reply to `#CFLRR`. As a command the radio says #CMDUN
* `#CFLSD STATUS` - Flash status, `00` is ready. Bits: 01 blank error, 02 erase error, 04 program error,
  08 read error, 10 ID error (observed during hardware detection), 20 area error, 40 unknown, 80 busy
* `#CFLSL 00` - Sent by the HX890 firmware flasher for models with an AIS unit, not for the HX890
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


### Firmware update sequence

Read from the vendor's updater for the HX870 (a .NET program, versions 02.03 and 02.04).
Steps 2 to 4 and the read are verified on an HX870 with firmware 02.04 (`hxtool firmware
--readto`); the erase and write steps are not.

1. `P`, `0`, `ACMD:002`, `#CVRRQ` to show the installed version.
2. `#CMDNR STANDARD HORIZON`, answered with `#CMDOK` and `#CMDND <flash ID>`: the radio names
   its own ID (`AM057N2` on the HX870 here). The radio grants this once per power-on; a
   second `#CMDNR` gets `#CMDER`.
3. `#CFLID <flash ID>` (padded to ten bytes with NUL), answered with `#CMDOK` and `#CFLSD 00`;
   a wrong ID gets `#CFLSD 10`. The updater then pauses a second, repeats `#CMDNR` and tries
   its second ID.
4. A pause, `#CFLMC 01`, answered with `#CMDOK` and `#CFLSD 00`, then `#CMDSY` twice.
5. `#CFLER 000000` (erase), `#CFLCB 000000` (blank check), `#CFLSR 00` until `#CFLSD 00`.
6. The image for 0xF40000..0xFEFFFF in chunks of 0x80 bytes: `#CFLSR 00` until
   `#CFLSD 00`, then `#CFLWR ADDRESS6 80 <HEXBYTES>`, answered with `#CMDOK`.
   For a read, `#CFLRR ADDRESS6 80` instead, answered with `#CFLRD`.
7. A pause, `#CFLMC 03`, answered with `#CMDOK`. The radio reboots.

Each of the commands from step 2 on is followed by a `;` byte, except the status poll and
the transfers. Timeout 2000 ms, five attempts per command. The updater carries the image as
S-records with six hex digits swapped; `tools/fwextract.py` reads it out. It writes the
whole area, erased chunks included.

The radio acknowledges an erase, a blank check and a write when the flash operation is
done, with `#CMDOK` and `#CFLSD <status>` together.

hxtool follows this sequence, with two differences. It offers the flash ID the radio has
just named in `#CMDND`, the one the radio accepts, instead of a list of its own. And it
acknowledges every `#CFLSD` with `#CMDOK`, like any data reply; the updater only does so
after `#CFLSR`, and the radio repeats the others. A status other than `00` after `#CFLID`,
`#CFLMC 01`, an erase, a blank check or a write is an error.

The updater for the HX890 (version 02.00) is a different, native program. It sends the same
sequence with the flash ID `AM063N` and the same chunks of 0x80 bytes, and differs in this:

* It writes four blocks instead of one run, and leaves the rest of the erased area alone:
  0xF40000..0xFC9E7F, 0xFEEE00..0xFEF77F, 0xFEF800..0xFEFEFF and 0xFEFF80..0xFEFFFF.
  It holds the block contents in an encoded form, which `tools/fwextract.py` does not read.
* It waits longer for the acknowledgements: 10 s for the erase, 5 s for the blank check,
  8 s for a write, 5 s for the closing `#CFLMC 03`.
* If the closing `#CFLMC 03` is not acknowledged, it sends `#CFLMC 02`, which switches the
  radio off.
* It has a repair function for a radio left in flash mode, which sends `#CFLMC 03`.
* Before the version request it can send `#CFLSL` to select a unit in a model with an AIS
  unit (it knows a `#CMDND AM059N-AIS`). For the HX890 that step is skipped.
* It names the bits of the status byte in `#CFLSD`: 01 blank error, 02 erase error,
  04 program error, 08 read error, 10 ID error, 20 area error, 40 unknown, 80 busy.

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
  * `127`: unknown from raw log header offset 4
  * `5`: logger interval (in seconds) when log was started
  * `0`: unknown
  * `0`: unknown
  * `1`: unknown
  * `1430`: number of log slots used (max. 6432)
  * `22`: log usage percentage
* `$PMTK001,183,3*3A` - Radio ACK of StatusLog
* `$PMTK622,1*29` - ReadLog, sent to radio
* `$PMTKLOX,0,43*6E` - Radio response with data, expect 43 `LOX,1` log lines
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

* `PMTK183*`  Query logging status
* `PMTK184,0*`  Erase logger flash
* `PMTK185,1*`  Stop logging data
* `PMTK186,1*`  Snapshot write log
* `PMTK187,1,1*`  Configure Locus setting, interval mode 1s
* `PMTK225,0*`  Set periodic power saving mode, normal mode
* `PMTK251,0*`  Set NMEA baud rate, default
* `PMTK301,0*`  Set DGPS correction source, none
* `PMTK313,0*`  Enable or disable SBAS search
* `PMTK386,0*`  Set speed threshold for static navigation
* `PMTK605*`  Query firmware release information
* `PMTK622,0*`  Dump Locus flash data


#### Strings appearing in YCE01 firmware flasher

* `OK` - AnswerOK, not seen from HX870
* `ERROR` - AnswerERROR, not seen from HX870

These haven't been observed on the line, yet.

### Factory reset

After factory reset, the following values are present at offset 0x0110 in config flash:

`17 12 26 18  53 52 18 88  80 4E 00 06  11 76 21 45`

After a full reboot, those values are replaced by all FF.

## Tools

`tools/convert.py` turns a USB capture (pcap) of the vendor software talking to a radio
into the protocol dialogue (`print`) or the memory image it transferred (`dump`). It
needs Wireshark's `tshark`.

`tools/fwextract.py UPDATER.exe IMAGE` extracts the firmware image from one of the
vendor's firmware updaters for the HX870, as `IMAGE.srec` (the updater's own S-records,
which `hxtool firmware --writefrom` takes) and as `IMAGE.bin` (flat, for a disassembler;
the tool prints its load address, entry address and segments). The binary for version
02.03 is identical to the image the updater sends to the radio.

## Testing notes

 - `pip install -e '.[dev]'` - installing the development dependencies
 - `pytest -v` - running the test suite
 - `pytest --cov=hxtool --cov-report=term` - running test coverage

# Documentation

 - https://www.telit.com/wp-content/uploads/2018/03/1VV0301162_V13_Software_User_Guide_r4.pdf
 - https://cdn-shop.adafruit.com/datasheets/PMTK+command+packet-Complete-C39-A01.pdf
 - https://cdn-shop.adafruit.com/datasheets/GTop+LOCUS+Library+User+Manual-v13.pdf
 - https://simcomturkiye.com/pdf/GNSS/SIM28/Locus_Manual_for_MTK_GNSS_Platform_V1.00.pdf 
