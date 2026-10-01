"""
Presentation for the command line: how log records and progress look. The
library modules only use `logging` and progress callbacks; rich stays in here
and is imported when the command line needs it, not when hxtool is imported.

On a terminal, logging and progress bars are drawn by rich. Anywhere else
(pipes, files, tests) the output is plain lines, progress included.
"""

import logging
from contextlib import contextmanager

from ..progress import log_progress

logger = logging.getLogger(__name__)

_console = None  # the rich console of the running command, once logging is set up


def setup_logging(debug: bool = False) -> None:
    """Route the library's log records to stderr, in the style that suits it"""
    global _console
    from rich.console import Console

    _console = Console(stderr=True)
    if _console.is_terminal:
        from rich.logging import RichHandler
        handler = RichHandler(console=_console, show_path=debug, omit_repeated_times=False, markup=False,
                              rich_tracebacks=True, log_time_format="%H:%M:%S")
        handler.setFormatter(logging.Formatter("%(message)s"))
    else:
        handler = logging.StreamHandler()
        fmt = "%(asctime)s %(levelname)s %(name)s %(message)s" if debug else "%(asctime)s %(levelname)s %(message)s"
        handler.setFormatter(logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S"))
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO, handlers=[handler], force=True)


@contextmanager
def progress(description: str, unit: str):
    """
    The progress callback to hand to a library transfer: a progress bar on a
    terminal, log lines otherwise.
    """
    if _console is None or not _console.is_terminal:
        yield log_progress(logger, unit)
        return

    from rich.progress import BarColumn, MofNCompleteColumn, Progress, TaskProgressColumn, TextColumn, \
        TimeRemainingColumn

    columns = (TextColumn("{task.description}"), BarColumn(), TaskProgressColumn(), MofNCompleteColumn(),
               TextColumn(unit), TimeRemainingColumn())
    with Progress(*columns, console=_console, transient=True) as bar:
        task = bar.add_task(description, total=None)
        yield lambda done, total: bar.update(task, completed=done, total=total)
