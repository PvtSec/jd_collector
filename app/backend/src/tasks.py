from __future__ import annotations

import asyncio
import time
from typing import Any

from .db import DB


class TaskRunning(Exception):
    pass


class TaskManager:
    def __init__(self, db: DB):
        self.db = db
        self._lock = asyncio.Lock()  # not used across threads; state guarded below
        self._state_lock = __import__("threading").Lock()
        self._current: dict | None = None
        self._subscribers: list[asyncio.Queue] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    @property
    def is_running(self) -> bool:
        with self._state_lock:
            return self._current is not None

    def current(self) -> dict:
        with self._state_lock:
            if self._current is None:
                return {"running": False}
            return {"running": True, **self._current}

    def history(self, limit: int = 20) -> list[dict]:
        return self.db.recent_runs(limit)

    def begin(self, kind: str, companies_total: int = 0) -> int:
        run_id = self.db.start_run(kind)
        with self._state_lock:
            self._current = {
                "kind": kind,
                "started_at": time.time(),
                "run_id": run_id,
                "companies_total": companies_total,
                "companies_done": 0,
                "jobs_seen": 0,
                "jobs_new": 0,
                "jobs_matched": 0,
                "progress": "starting",
            }
        self.publish({"type": "task_started", **self._current})
        return run_id

    def progress(self, **fields):
        with self._state_lock:
            if self._current is None:
                return
            self._current.update(fields)
            snapshot = dict(self._current)
        self.publish({"type": "task_progress", **snapshot})

    def finish(self, status: str, error: str = ""):
        with self._state_lock:
            cur = self._current
            self._current = None
        if cur:
            self.db.finish_run(cur.get("run_id"), status, error)
            self.publish({"type": "task_completed" if status == "success" else "task_failed",
                          "status": status, "error": error, **cur})

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    def publish(self, event: dict[str, Any]):
        if self._loop is None:
            return  # no loop yet (e.g. called before lifespan); drop event
        for q in list(self._subscribers):
            try:
                self._loop.call_soon_threadsafe(self._put, q, event)
            except RuntimeError:
                # loop closed during shutdown
                pass

    @staticmethod
    def _put(q: asyncio.Queue, event: dict):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            # drop oldest-ish: pop one then put (back-pressure → slow consumer)
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass


# Module-level singleton, set in app.py
manager: TaskManager | None = None


def get_manager() -> TaskManager:
    if manager is None:
        raise RuntimeError("TaskManager not initialized")
    return manager


def set_manager(m: TaskManager):
    global manager
    manager = m