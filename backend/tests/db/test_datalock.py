"""One owner per data directory (selko.db.datalock)."""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

from selko.db import datalock, runtime


@pytest.fixture(autouse=True)
def _closed():
    runtime.close_database()
    yield
    runtime.close_database()


def _hold_in_another_process(data_dir, ready_file):
    """Start a process that takes the lock, signals, then waits to be killed."""
    script = textwrap.dedent(f"""
        import pathlib, time
        from selko.db import datalock
        handle = datalock.acquire({str(data_dir)!r}, "test holder")
        pathlib.Path({str(ready_file)!r}).write_text("held")
        time.sleep(60)
    """)
    proc = subprocess.Popen([sys.executable, "-c", script])
    for _ in range(200):
        if ready_file.exists():
            return proc
        if proc.poll() is not None:
            raise RuntimeError("the holder exited early")
        import time

        time.sleep(0.05)
    proc.kill()
    raise RuntimeError("the holder never took the lock")


# Validates: SEL-606
def test_a_second_owner_is_refused_and_named(tmp_path):
    first = datalock.acquire(tmp_path, "selko.api")
    try:
        with pytest.raises(datalock.DataDirLocked, match="selko.api"):
            datalock.acquire(tmp_path, "selko.worker_app")
    finally:
        datalock.release(first)
    again = datalock.acquire(tmp_path, "selko.worker_app")
    datalock.release(again)


# Validates: SEL-607
def test_another_process_holds_it_until_it_dies(tmp_path):
    holder = _hold_in_another_process(tmp_path, tmp_path / "ready")
    try:
        with pytest.raises(datalock.DataDirLocked, match="test holder"):
            datalock.acquire(tmp_path, "selko.api")
    finally:
        holder.kill()
        holder.wait()
    # Killed, not released: the kernel drops the lock with the process.
    handle = datalock.acquire(tmp_path, "selko.api")
    datalock.release(handle)


# Validates: SEL-606
def test_a_server_refuses_before_touching_the_database(tmp_path):
    holder = datalock.acquire(tmp_path, "selko.worker_app")
    try:
        with pytest.raises(datalock.DataDirLocked):
            runtime.open_database(tmp_path, owner="selko.api")
        assert not (tmp_path / runtime.DATABASE_FILE).exists()
    finally:
        datalock.release(holder)


# Validates: SEL-605, SEL-608
def test_the_server_holds_it_until_close_and_operator_commands_still_open(tmp_path):
    runtime.open_database(tmp_path, owner="selko.api")
    with pytest.raises(datalock.DataDirLocked):
        datalock.acquire(tmp_path, "selko.worker_app")
    # An operator command beside the running server: no owner, no lock.
    script = (
        "from selko.db.runtime import open_database;"
        f"open_database({str(tmp_path)!r}).query_one('SELECT 1')"
    )
    subprocess.run([sys.executable, "-c", script], check=True)
    runtime.close_database()
    handle = datalock.acquire(tmp_path, "selko.worker_app")
    datalock.release(handle)
