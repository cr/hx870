# TODO

Tasks and known bugs that are not being addressed right now.

## Packaging

- [ ] `ipython` is a runtime dependency but nothing in the code imports it.
      Drop it or move it to the `dev` extra.
- [ ] `setup.cfg` survives only for the `[pycodestyle]` line length, because
      pycodestyle does not read `pyproject.toml`. Goes away with a switch to
      a linter that does (e.g. ruff).
- [ ] Confirm the licence expression: `pyproject.toml` says `GPL-3.0-only`;
      change to `GPL-3.0-or-later` if that is what was meant.
- [ ] Decide what to do with the untracked files in the repo root
      (`hx870log.bt`, `hx890dat.bt`, `hx891bt-e-*-config.bin`): commit or ignore.

## Bugs

- [ ] `hxtool/cli/gpslog.py` `dump_log`: longitude hemisphere is derived from
      `lat_deg` instead of `lon_deg`.
- [ ] `hxtool/cli/gpslog.py` `to_hm`: `divmod` on negative degrees floors, so
      southern and western positions print wrong. Convert the absolute value
      and take the hemisphere from the sign.
- [ ] `hxtool/locus.py` `LocusWaypoint.__bytes__`: `pack(self._format, values)`
      must unpack the list (`*values`).
- [ ] `hxtool/locus.py` `LocusWaypoint.__init__`: `_labels` is assigned
      `content["attributes"]` instead of `content["labels"]`.
- [ ] `hxtool/protocol.py` `Message.checksum`: the `x != "!"` filter compares
      ints with a string and never excludes anything. Find out what was
      intended, then fix or remove.
- [ ] `hxtool/cli/config.py` `--dump`: the output file is opened before the
      radio is read, so a failed read leaves an empty file behind.
- [ ] `hxtool/simulator.py`: module-level `from pty import openpty` breaks
      `import hxtool` on Windows, because `hxtool/__init__.py` and
      `hxtool/device.py` import the simulator unconditionally.

## Safety

- [ ] `config --flash`: check the flash ID before writing and add a `--really`
      override (existing TODO in `hxtool/cli/config.py`).
- [ ] `config --dump`: warn on flash ID mismatch (existing TODO).

## Cleanup

- [ ] `hxtool/cli/config.py`: the command class is named `InfoCommand`, same as
      the one in `hxtool/cli/info.py`. Rename to `ConfigCommand`.
- [ ] `hxtool/config_file.py`: `ConfigFile` is HX870-only (fixed magic and size)
      and not used by the CLI. Generalise or remove.
- [ ] `hxtool/memory.py`: `unpack_channel_groups` and `unpack_weather_channels`
      are stubs; `unpack_channels` enumerates by channel ID instead of the
      enable list (FIXME in code).
- [ ] README: fix the "Experimantal" typo and the HX891BT docstring that says
      HX890 in `hxtool/device.py`.

## Features

- [ ] Expose waypoint reading (`read_waypoints`) and channel decoding on the CLI.
- [ ] Waypoint writing (`pack_waypoint` exists, nothing calls it).
- [ ] HX890 / HX891BT channel and config layout (`memory.py` segments are
      HX870-only).
- [ ] GPX export: speed and heading via GPX 1.1 extensions (TODO in
      `hxtool/cli/gpslog.py`).
- [ ] NMEA mode: `HX870NMEAProtocol` / `HX890NMEAProtocol` are empty shells.
- [ ] GPS log transfer at 115200 baud (currently pinned to the slow default
      because the GPS module misbehaves after a baud rate change).
- [ ] Firmware flashing (`#CFL*` commands are documented in the README only).
- [ ] FT750-style aviation radios on the CLI.
