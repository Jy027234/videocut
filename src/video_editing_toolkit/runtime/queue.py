"""In-memory local run queue for P0 development."""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from threading import Lock
from typing import Any


QUEUE_SNAPSHOT_SCHEMA = "video_editing_toolkit.runtime.local_queue_snapshot.v0"


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

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-safe queue snapshot for P0 local persistence."""

        with self._lock:
            return {
                "schema": QUEUE_SNAPSHOT_SCHEMA,
                "queued_run_ids": [
                    run_id
                    for run_id in self._items
                    if run_id not in self._cancelled
                ],
                "cancelled_run_ids": sorted(self._cancelled),
            }

    def save_snapshot(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(self.snapshot(), ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, Any]) -> "InMemoryLocalQueue":
        queue = cls()
        queued = snapshot.get("queued_run_ids", [])
        cancelled = snapshot.get("cancelled_run_ids", [])
        if isinstance(queued, list):
            for run_id in queued:
                if isinstance(run_id, str) and run_id:
                    queue.enqueue(run_id)
        if isinstance(cancelled, list):
            for run_id in cancelled:
                if isinstance(run_id, str) and run_id:
                    queue.cancel(run_id)
        return queue

    @classmethod
    def load_snapshot(cls, path: str | Path) -> "InMemoryLocalQueue":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("Queue snapshot must be a JSON object.")
        return cls.from_snapshot(raw)
