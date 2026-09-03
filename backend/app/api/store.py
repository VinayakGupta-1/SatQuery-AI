"""In-memory storage of completed task runs.

This is deliberately simple and deliberately not persistent: restarting the
process loses the task history, though the uploaded and generated files remain
on disk. Swapping this for a database later means implementing the same three
methods, and nothing outside this module needs to change.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass, field

from app.api.schemas import ImageSummary
from app.controller.pipeline import PipelineRun


@dataclass
class TaskRecord:
    """One completed run, plus what the API needs to serve it again."""

    run: PipelineRun
    images: list[ImageSummary] = field(default_factory=list)
    #: artifact_id -> absolute path on disk. Downloads are served only from
    #: this map, so a request can never reach a file the run did not produce.
    artifacts: dict[str, str] = field(default_factory=dict)


class TaskStore:
    """A bounded, thread-safe map of task id to record."""

    def __init__(self, capacity: int = 200) -> None:
        self._records: OrderedDict[str, TaskRecord] = OrderedDict()
        self._capacity = capacity
        self._lock = threading.Lock()

    def save(self, record: TaskRecord) -> TaskRecord:
        with self._lock:
            self._records[record.run.task_id] = record
            self._records.move_to_end(record.run.task_id)
            while len(self._records) > self._capacity:
                self._records.popitem(last=False)
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


#: The process-wide store used by the routers.
task_store = TaskStore()
