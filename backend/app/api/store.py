"""In-memory storage of completed task runs.

This is deliberately simple and deliberately not persistent: restarting the
process loses the task history. Files of a task pushed out of the store are
deleted with it, and files left by an earlier process are purged at startup
(``SATQUERY_RETENTION_HOURS``), because neither can ever be served again.
Swapping this for a database later means implementing the same three
methods, and nothing outside this module needs to change.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Callable

from app.api.schemas import ImageSummary
from app.controller.pipeline import PipelineRun
from app.storage.artifacts import StorageError, get_artifact_store


@dataclass
class TaskRecord:
    """One completed run, plus what the API needs to serve it again."""

    run: PipelineRun
    images: list[ImageSummary] = field(default_factory=list)
    #: artifact_id -> absolute path on disk. Downloads are served only from
    #: this map, so a request can never reach a file the run did not produce.
    artifacts: dict[str, str] = field(default_factory=dict)
    #: The Supabase user who ran it; ``None`` when sign-in is off. A record
    #: is only ever served back to its owner.
    user_id: str | None = None


class TaskStore:
    """A bounded, thread-safe map of task id to record.

    ``on_evict`` is called with the id of every task pushed out by a newer
    one. Once a record is gone its files can never be served again, so the
    process-wide store deletes them rather than letting the disk fill.
    """

    def __init__(
        self,
        capacity: int = 200,
        on_evict: Callable[[str], None] | None = None,
    ) -> None:
        self._records: OrderedDict[str, TaskRecord] = OrderedDict()
        self._capacity = capacity
        self._on_evict = on_evict
        self._lock = threading.Lock()

    def save(self, record: TaskRecord) -> TaskRecord:
        evicted: list[str] = []
        with self._lock:
            self._records[record.run.task_id] = record
            self._records.move_to_end(record.run.task_id)
            while len(self._records) > self._capacity:
                evicted.append(self._records.popitem(last=False)[0])
        # Outside the lock: deleting files must not stall other requests.
        if self._on_evict is not None:
            for task_id in evicted:
                self._on_evict(task_id)
        return record

    def get(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            return self._records.get(task_id)

    def list(self, limit: int = 50) -> list[TaskRecord]:
        """Return the most recent records, newest first."""
        with self._lock:
            records = list(self._records.values())
        return list(reversed(records))[:limit]

    def clear(self) -> None:
        with self._lock:
            self._records.clear()


def _delete_files(task_id: str) -> None:
    try:
        get_artifact_store().delete_task(task_id)
    except StorageError:
        pass


#: The process-wide store used by the routers.
task_store = TaskStore(on_evict=_delete_files)
