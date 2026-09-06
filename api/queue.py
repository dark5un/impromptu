"""Serialised render queue with progress (plan item 15).

`render/melt.py` already parses mlt-melt's progress lines and accepts an
``on_progress`` callback; nothing exposed it, so the UI could only block on an
opaque render. This module is the missing surface, and deliberately nothing
more: it reuses ``run_melt``'s progress rather than re-parsing anything.

Design notes
------------
* **One render at a time.** ``run_melt`` pins threads and sets
  ``real_time=-1`` for deterministic output; two concurrent renders would
  contend for CPU and defeat that. A single worker thread keeps renders
  serialised and makes queue position meaningful.
* **A thread, not a process pool or a broker.** The studio is a local
  single-user tool on one port; Celery or RQ would add a dependency and a
  daemon for something that is one worker and a dict.
* **Progress is a percentage.** ``parse_progress`` yields a frame number, so
  the queue converts it against the job's frame total when one is known and
  otherwise reports the raw count without inventing a denominator.
"""
from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from render.melt import run_melt
from render.pipeline import render_production


def programme_frames(directory: str | Path) -> int | None:
    """Total output frames for a production, or None if it cannot be derived.

    Reuses the compositor's own ``scene_layout`` so the denominator matches the
    timeline MLT will actually render -- including transition overlaps, which a
    naive sum of scene durations would double-count.
    """
    try:
        import yaml

        from core.direct import direct_document
        from render.mlt_xml import scene_layout

        source = Path(directory)
        source = source if source.is_file() else source / "production.yaml"
        document = direct_document(yaml.safe_load(source.read_text()))
        layout = scene_layout(document)
        if not layout:
            return None
        fps = float(document["target"]["fps"])
        last = layout[-1]
        return round((last["program_start"] + last["duration"]) * fps)
    except Exception:
        # Progress reporting must never block a render: an undeterminable total
        # just means the job reports raw frames instead of a percentage.
        return None


def _default_runner(directory: Path, *, threads: int = 1,
                    on_progress: Callable[[float], None] | None = None) -> Path:
    """Render *directory*, forwarding melt's progress to *on_progress*."""
    return render_production(
        directory,
        threads=threads,
        runner=lambda project, output, threads=1: run_melt(
            project, output, threads=threads, on_progress=on_progress),
    )


class RenderQueue:
    """A single-worker render queue with inspectable job state."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._order: list[str] = []
        # One worker: renders must not overlap (see module docstring).
        self._worker: threading.Thread | None = None
        self._pending = threading.Condition(self._lock)
        self._finished: dict[str, threading.Event] = {}

    # ── submission ────────────────────────────────────────────────────────────

    def submit(self, directory: str | Path, *, threads: int = 1,
               runner: Callable[..., Any] | None = None,
               total_frames: int | None = None) -> str:
        """Queue a render and return its job id.

        *runner* is injectable so tests never invoke mlt-melt; *total_frames*
        turns melt's frame counter into a percentage. When not given it is
        derived from the document, so callers get a real progress bar without
        having to compute the timeline themselves.
        """
        job_id = uuid.uuid4().hex[:12]
        if total_frames is None:
            total_frames = programme_frames(directory)
        job = {
            "job_id": job_id,
            "production": str(Path(directory).name),
            "directory": str(directory),
            "state": "queued",
            "percent": 0.0,
            "frame": 0,
            "total_frames": total_frames,
            "output": None,
            "error": None,
            "threads": threads,
            "_runner": runner or _default_runner,
        }
        with self._lock:
            self._jobs[job_id] = job
            self._order.append(job_id)
            self._finished[job_id] = threading.Event()
            self._ensure_worker()
            self._pending.notify_all()
        return job_id

    def _ensure_worker(self) -> None:
        """Start the worker lazily; caller holds the lock."""
        if self._worker is not None and self._worker.is_alive():
            return
        # Daemon: a queued render must never block interpreter shutdown, and an
        # interrupted render is recoverable by resubmitting.
        self._worker = threading.Thread(
            target=self._drain, name="impromptu-render", daemon=True)
        self._worker.start()

    # ── worker ────────────────────────────────────────────────────────────────

    def _next_queued(self) -> dict[str, Any] | None:
        for job_id in self._order:
            job = self._jobs[job_id]
            if job["state"] == "queued":
                return job
        return None

    def _drain(self) -> None:
        while True:
            with self._lock:
                job = self._next_queued()
                if job is None:
                    # Nothing left; exit and let the next submit restart us
                    # rather than parking a thread forever.
                    self._worker = None
                    return
                job["state"] = "running"
                runner = job["_runner"]
                directory = Path(job["directory"])
                threads = job["threads"]
                job_id = job["job_id"]

            def on_progress(frame: float, _job_id: str = job_id) -> None:
                with self._lock:
                    tracked = self._jobs[_job_id]
                    tracked["frame"] = int(frame)
                    total = tracked["total_frames"]
                    if total:
                        tracked["percent"] = min(100.0, 100.0 * frame / total)

            try:
                output = runner(directory, threads=threads, on_progress=on_progress)
            except Exception as exc:  # surfaced on the job, never swallowed
                with self._lock:
                    tracked = self._jobs[job_id]
                    tracked["state"] = "failed"
                    tracked["error"] = f"{type(exc).__name__}: {exc}"
                    self._finished[job_id].set()
                continue

            with self._lock:
                tracked = self._jobs[job_id]
                tracked["state"] = "done"
                tracked["percent"] = 100.0
                tracked["output"] = str(output)
                self._finished[job_id].set()

    # ── inspection ────────────────────────────────────────────────────────────

    @staticmethod
    def _public(job: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in job.items() if not key.startswith("_")}

    def get(self, job_id: str) -> dict[str, Any] | None:
        """Return a snapshot of one job, or None when the id is unknown."""
        with self._lock:
            job = self._jobs.get(job_id)
            return self._public(job) if job else None

    def list(self) -> list[dict[str, Any]]:
        """Snapshot every job in submission order."""
        with self._lock:
            return [self._public(self._jobs[job_id]) for job_id in self._order]

    def wait(self, job_id: str, timeout: float | None = None) -> bool:
        """Block until *job_id* finishes. Returns False on timeout."""
        with self._lock:
            event = self._finished.get(job_id)
        if event is None:
            return False
        return event.wait(timeout)


__all__ = ["RenderQueue"]
