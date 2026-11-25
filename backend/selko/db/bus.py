"""In-process events: what Postgres sent with pg_notify and realtime.send.

There is one process, so a notification never has to leave it. The data layer
publishes from `Transaction.after_commit` (so a rolled-back write announces
nothing), possibly from a worker thread; subscribers are asyncio consumers --
the ingestion workers waiting for work, and the web clients' `/live` streams
waiting for invalidation hints.

A slow subscriber never blocks a publisher: each subscription has a bounded
queue, and when it is full the oldest message is dropped and the subscription
is marked `lagged`. Both kinds of consumer already treat messages as hints and
catch up from the database, so dropping is safe; a lagged `/live` stream tells
its client to refetch everything.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

DEFAULT_QUEUE_SIZE = 256


@dataclass(eq=False)  # identity: each subscription is its own consumer
class Subscription:
    topic: str
    queue: asyncio.Queue[Any]
    loop: asyncio.AbstractEventLoop
    lagged: bool = False
    _closed: bool = field(default=False, repr=False)

    async def __aiter__(self) -> AsyncIterator[Any]:  # pragma: no cover - thin wrapper
        while not self._closed:
            yield await self.queue.get()

    async def get(self, timeout: float | None = None) -> Any:
        """The next message, or raises TimeoutError after ``timeout`` seconds."""
        return await asyncio.wait_for(self.queue.get(), timeout)


class Bus:
    def __init__(self, queue_size: int = DEFAULT_QUEUE_SIZE) -> None:
        self._queue_size = queue_size
        self._subscribers: dict[str, set[Subscription]] = {}
        self._lock = threading.Lock()

    def subscribe(self, topic: str) -> Subscription:
        """Subscribe from a running event loop."""
        sub = Subscription(topic, asyncio.Queue(self._queue_size), asyncio.get_running_loop())
        with self._lock:
            self._subscribers.setdefault(topic, set()).add(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        sub._closed = True
        with self._lock:
            subs = self._subscribers.get(sub.topic)
            if subs is not None:
                subs.discard(sub)
                if not subs:
                    del self._subscribers[sub.topic]

    def subscriber_count(self, topic: str) -> int:
        with self._lock:
            return len(self._subscribers.get(topic, ()))

    def publish(self, topic: str, message: Any) -> int:
        """Deliver to every subscriber of ``topic``, from any thread. Returns how many."""
        with self._lock:
            subs = list(self._subscribers.get(topic, ()))
        for sub in subs:
            if sub.loop.is_closed():
                continue
            sub.loop.call_soon_threadsafe(_offer, sub, message)
        return len(subs)


def _offer(sub: Subscription, message: Any) -> None:
    if sub._closed:
        return
    if sub.queue.full():
        sub.queue.get_nowait()
        sub.lagged = True
    sub.queue.put_nowait(message)


class WorkSignals:
    """Worker wake-ups: the in-process replacement for the Postgres WorkListener.

    Workers keep their ``event_for(work_type).wait()`` / ``.clear()`` loops.
    The data layer calls `signal` after COMMIT (possibly from a worker
    thread), so a worker never wakes to a row it cannot see yet. The safety
    poll stays the floor.
    """

    WORK_TYPES = ("email_pending", "event_approved", "item_pending", "attachment_pending")

    def __init__(self) -> None:
        self._events: dict[str, asyncio.Event] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._sent = 0
        self._last_signal_at: float | None = None

    async def start(self) -> None:
        """Bind to the running loop and create the events (no I/O)."""
        self._loop = asyncio.get_running_loop()
        for work_type in self.WORK_TYPES:
            self.event_for(work_type)

    async def stop(self) -> None:
        self._loop = None

    def event_for(self, work_type: str) -> asyncio.Event:
        if work_type not in self._events:
            self._events[work_type] = asyncio.Event()
        return self._events[work_type]

    def signal(self, work_type: str) -> None:
        """Wake the workers waiting for ``work_type``; safe from any thread."""
        import time

        self._sent += 1
        self._last_signal_at = time.time()
        event = self._events.get(work_type)
        loop = self._loop
        if event is None or loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(event.set)

    def status(self) -> dict[str, Any]:
        return {
            "kind": "in_process",
            "bound": self._loop is not None,
            "signals_sent": self._sent,
            "last_signal_at": self._last_signal_at,
        }
