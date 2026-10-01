import logging
import subprocess
import sys

from hxtool import config, simulator
from hxtool.main import main
from hxtool.progress import log_progress
from hxtool.protocol import GenericHXProtocol, MediaTekProtocol


def test_library_does_not_import_rich():
    # rich is the command line's presentation; the library only logs and calls back
    code = "import sys, hxtool; print('rich' in sys.modules)"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"


def recorder():
    calls = []
    return calls, lambda done, total: calls.append((done, total))


def assert_progress(calls, total):
    assert calls[0] == (0, total), "starts at nothing done"
    assert calls[-1] == (total, total), "ends complete"
    assert [done for done, _ in calls] == sorted(done for done, _ in calls), "never goes backwards"
    assert {t for _, t in calls} == {total}


def test_progress_callbacks(kill_sims):
    sim = simulator.HXSimulator(config.HX870Config, mode="CP", loop_delay=0.0005)
    sim.gps_log = bytes(0x1000)
    sim.start()
    p = GenericHXProtocol(sim.tty)
    c = config.HX870Config(p)

    calls, callback = recorder()
    image = c.config_read(progress=callback)
    assert_progress(calls, 0x8000)
    assert len(calls) == 0x8000 // 0x40 + 1, "one call per chunk"

    calls, callback = recorder()
    c.config_write(image, progress=callback)
    assert_progress(calls, 0x8000)

    calls, callback = recorder()
    assert len(MediaTekProtocol(p).read_log(progress=callback)) == 0x1000
    assert_progress(calls, 43)

    assert c.config_read() == image, "progress reporting is optional"


def test_log_progress(caplog):
    caplog.set_level(logging.INFO)
    report = log_progress(logging.getLogger("test"), "bytes")
    for done in range(0, 8192 + 1, 32):
        report(done, 8192)
    lines = [record.getMessage() for record in caplog.records]
    assert lines[0] == "0 / 8192 bytes (0%)"
    assert "2048 / 8192 bytes (25%)" in lines
    assert lines[-1] == "8192 / 8192 bytes (100%)"
    assert len(lines) == 9, "one line per eighth, not one per chunk"


def test_cli_is_plain_when_not_on_a_terminal(tmpdir, capsys, kill_sims):
    assert main(["--simulator", "-t", "0", "config", "-d", str(tmpdir.join("config.dat"))]) == 0
    err = capsys.readouterr().err
    assert "\x1b[" not in err, "no terminal control codes in a pipe"
    assert " INFO Reading config flash from handset" in err
    assert " INFO 16384 / 32768 bytes (50%)" in err, "progress is logged instead of drawn"
    assert " INFO Operation successful" in err


def test_cli_is_rich_on_a_terminal(tmpdir, capsys, kill_sims, monkeypatch):
    monkeypatch.setenv("FORCE_COLOR", "1")  # rich then treats stderr as a terminal
    dump = tmpdir.join("config.dat")
    assert main(["--simulator", "-t", "0", "config", "-d", str(dump)]) == 0
    assert dump.size() == 0x8000
    err = capsys.readouterr().err
    assert "\x1b[" in err, "styled output"
    assert "Operation successful" in err
    assert "Reading config" in err, "the progress bar was drawn"
    assert "16384 / 32768 bytes (50%)" not in err, "and replaces the progress log lines"
