"""Background workers for async job processing.

This package implements the worker side of the Async Monolith pattern,
processing jobs from the PostgreSQL job queue using a continuous worker pool.
"""

from selko.workers.pool import WorkerPool

__all__ = ["WorkerPool"]
