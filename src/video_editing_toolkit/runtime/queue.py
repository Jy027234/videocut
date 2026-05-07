"""In-memory local run queue for P0 development."""

from __future__ import annotations

from collections import deque
from threading import Lock


class InMemoryLocalQueue:
    """A small FIFO queue keyed by run_id.

    This is intentionally process-local. It gives the runtime service the same
    lifecycle shape as a real queue without introducing Redis/RabbitMQ yet.
    """

    def __init__(self) -> None:
        self._items: deque[str] = deque()
        self._cancelled: set[str] = set()
        self._lock = Lock()

    def enqueue(self, run_id: str) -> None:
        with self._lock:
            if run_id not in self._cancelled:
                self._items.append(run_id)

    def dequeue(self) -> str | None:
        with self._lock:
            while self._items:
                run_id = self._items.popleft()
                if run_id not in self._cancelled:
                    return run_id
            return None

    def cancel(self, run_id: str) -> bool:
        with self._lock:
            self._cancelled.add(run_id)
            return run_id in self._items

    def clear_cancelled(self, run_id: str) -> None:
        with self._lock:
            self._cancelled.discard(run_id)

    def __len__(self) -> int:
        with self._lock:
            return sum(1 for run_id in self._items if run_id not in self._cancelled)
