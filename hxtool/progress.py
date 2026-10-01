"""
Progress reporting for long transfers. The library reports progress through a
callback and knows nothing about how it is presented; log_progress() is the
presentation for anything that is not a terminal.
"""

from collections.abc import Callable
from logging import Logger

# Called with the amount done so far and the total, in the transfer's own unit
Progress = Callable[[int, int], None]


def log_progress(logger: Logger, unit: str, steps: int = 8) -> Progress:
    """A progress callback that logs a line each time another 1/steps of the total is done"""
    last_step = -1

    def report(done: int, total: int) -> None:
        nonlocal last_step
        step = steps if done >= total else done * steps // total
        if step != last_step:
            last_step = step
            percent = 100 if done >= total else int(100.0 * done / total)
            logger.info(f"{done} / {total} {unit} ({percent}%)")

    return report
