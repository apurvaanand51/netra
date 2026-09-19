"""
Background job registry.

WHY JOBS EXIST AT ALL
---------------------
A full analysis takes tens of seconds. Holding an HTTP request open that long
means the browser times out and the analyst watches a spinner with no
explanation. So the API accepts the work and returns immediately:

    POST /analyze  -> 202 Accepted + a job id
    GET  /job/{id} -> status, progress, and the log lines as they happen

That also gives the dashboard the thing that makes a demo feel alive: a progress
bar and a scrolling log, driven by real work rather than a timer.

WHY IN-MEMORY, AND WHAT IT COSTS
--------------------------------
Deliberately in-memory, not Redis or a task queue. The target is a
single-process, offline, air-gapped host: an external broker would be one more
thing to install, one more thing to keep running, and one more thing to fail
while someone is presenting. The trade-offs are real and stated rather than
discovered later:

  * job state is lost when the process restarts
  * jobs do not survive across multiple workers

Both are acceptable for a single-process tool and neither is acceptable for a
service. That is the actual boundary, so it is written down.
"""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

# How many finished jobs to keep before dropping the oldest. Without a cap this
# is a slow memory leak in a process that is meant to run for days.
MAX_JOBS = 50


@dataclass
class Job:
    id: str
    kind: str
    status: str = "queued"          # queued | running | done | error
    progress: float = 0.0           # 0..1
    log: list[str] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "progress": round(self.progress, 4),
            "log": list(self.log),
            "result": self.result,
            "error": self.error,
            "elapsed_seconds": round((self.finished_at or time.time()) - self.created_at, 2),
        }


class JobStore:
    """Thread-safe registry of background jobs.

    The Lock is not decoration. The work runs on a worker thread while the
    polling endpoint reads job state from the event loop thread; without it the
    two race and the UI can read a job mid-write -- showing a log line without
    the progress that produced it, or an empty log on a finished job.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}

    # ---- inspection --------------------------------------------------------
    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda job: job.created_at, reverse=True)

    # ---- mutation ----------------------------------------------------------
    def log(self, job_id: str, message: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.log.append(message)

    def progress(self, job_id: str, value: float) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.progress = max(0.0, min(1.0, value))

    def submit(self, kind: str, work: Callable[[str], dict[str, Any] | None]) -> Job:
        """Run `work(job_id)` on a worker thread and track it.

        The callable receives the job id so it can report progress through
        `log`/`progress` without needing a reference to the store.
        """
        job = Job(id=uuid.uuid4().hex[:12], kind=kind)

        with self._lock:
            self._jobs[job.id] = job
            if len(self._jobs) > MAX_JOBS:
                finished = sorted(
                    (item for item in self._jobs.values() if item.finished_at),
                    key=lambda item: item.finished_at or 0.0,
                )
                for stale in finished[: len(self._jobs) - MAX_JOBS]:
                    self._jobs.pop(stale.id, None)

        def runner() -> None:
            with self._lock:
                job.status = "running"
            try:
                result = work(job.id)
                with self._lock:
                    job.result = result or {}
                    job.status = "done"
                    job.progress = 1.0
            except Exception as exc:  # noqa: BLE001 - a job must never kill the server
                with self._lock:
                    job.status = "error"
                    job.error = f"{type(exc).__name__}: {exc}"
                    # The traceback goes in the log, not the response: an
                    # operator needs it, and a stack path is not something to
                    # hand a browser.
                    job.log.append(traceback.format_exc(limit=6))
            finally:
                with self._lock:
                    job.finished_at = time.time()

        threading.Thread(target=runner, name=f"netra-{job.id}", daemon=True).start()
        return job
