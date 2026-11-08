"""Trusted child progress: count a billable fit before starting it, never after."""

from contextvars import ContextVar
from contextlib import contextmanager
from dataclasses import dataclass
import json, os
from pathlib import Path

CURRENT = ContextVar("cisstat_compute_meter", default=None)
IN_CHILD = ContextVar("cisstat_compute_child", default=False)


class WorkLimitExceeded(BaseException):
    """Budget interruption must escape a tuner's ordinary failed-trial retry."""

    pass


@dataclass
class Meter:
    key: str
    limit: int
    path: str | None = None
    units: int = 0

    def save(self):
        if not self.path:
            return
        path = Path(self.path)
        temp = path.with_suffix(".tmp")
        with temp.open("w", encoding="utf-8") as stream:
            json.dump(
                {"key": self.key, "units": self.units, "limit": self.limit}, stream
            )
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)


@contextmanager
def meter_scope(key, limit, *, path=None):
    if type(limit) is not int or not 1 <= limit <= 100000:
        raise ValueError("finite work-unit bound required")
    meter = Meter(key, limit, path)
    meter.save()
    token = CURRENT.set(meter)
    try:
        yield meter
    finally:
        CURRENT.reset(token)


def tick(key):
    meter = CURRENT.get()
    if meter is None:
        return
    if key != meter.key or meter.units >= meter.limit:
        raise WorkLimitExceeded("calibrated work bound exceeded")
    meter.units += 1
    meter.save()
