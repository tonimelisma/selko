"""Background workers for async job processing.

This package implements the worker side of the Async Monolith pattern,
claiming work from the SQLite database with a continuous worker pool.
"""

from selko.workers.pool import WorkerPool

__all__ = ["WorkerPool"]
