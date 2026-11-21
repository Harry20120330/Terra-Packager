"""Atomic cache writes and opt-in build measurements."""
from __future__ import annotations

import os
import tempfile
import threading
import time
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path


def cache_root() -> Path:
    return Path(os.environ.get("TERRA_CACHE_DIR", Path.home() / ".cache" / "terra-packager")).expanduser().resolve()


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".terra_", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        Path(name).replace(path)
    finally:
        Path(name).unlink(missing_ok=True)


class Measurements:
    def __init__(self):
        self.seconds = Counter()
        self.counts = Counter()
        self.started = time.perf_counter()
        self.lock = threading.Lock()

    @contextmanager
    def stage(self, name):
        started = time.perf_counter()
        try:
            yield
        finally:
            with self.lock:
                self.seconds[name] += time.perf_counter() - started

    def count(self, name):
        with self.lock:
            self.counts[name] += 1

    def summary(self):
        lines = [f"Timings: total wall time {time.perf_counter() - self.started:.3f}s"]
        lines.extend(f"  {name}: {seconds:.3f}s (accumulated task time)" for name, seconds in sorted(self.seconds.items()))
        lines.extend(f"  {name}: {count}" for name, count in sorted(self.counts.items()))
        return "\n".join(lines)


CURRENT_MEASUREMENTS = ContextVar("terra_measurements", default=None)


@contextmanager
def measured(name):
    metrics = CURRENT_MEASUREMENTS.get()
    if metrics is None:
        yield
    else:
        with metrics.stage(name):
            yield
