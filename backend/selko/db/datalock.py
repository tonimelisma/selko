"""One owner per data directory: an exclusive lock on ``<data dir>/.selko.lock``.

SQLite keeps one database consistent across processes, but Selko's design
assumes a single process owns ``selko.db``: leases, the in-process work signals
and the live bus are all process-local. Two servers on one directory would each
believe they own the work.
The host's tooling prevents that; this lock is the second safeguard.

The server (``selko.api`` and ``selko.worker_app``) takes it for as long as it
runs. Operator commands (``python -m selko.admin``) do not: they
are meant to run beside the server, and SQLite serializes their writes.

The lock is ``flock``: the kernel releases it when the process exits, however
it exits, so a crash never leaves a stale lock behind.
"""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
from typing import IO

LOCK_FILE = ".selko.lock"


class DataDirLocked(RuntimeError):
    """Another process owns this data directory."""


def acquire(data_dir: Path | str, who: str) -> IO[str]:
    """Take the directory's lock or raise :class:`DataDirLocked`. Keep the handle open."""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    handle = open(data_dir / LOCK_FILE, "a+", encoding="utf-8")  # noqa: SIM115 - held for the process's life
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.seek(0)
        holder = handle.read().strip() or "another process"
        handle.close()
        raise DataDirLocked(f"{data_dir} is in use by {holder}; one process owns a data directory") from None
    handle.seek(0)
    handle.truncate()
    handle.write(f"{who} (pid {os.getpid()})\n")
    handle.flush()
    return handle


def release(handle: IO[str] | None) -> None:
    if handle is not None and not handle.closed:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()
