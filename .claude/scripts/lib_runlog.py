"""
lib_runlog — run lifecycle and event witnesses for every pipeline stage.

Why this exists
---------------
A stage used to leave evidence only when it *succeeded*: run_meta.json was
written at the very end with a hard-coded "success", so a run in progress and
a crashed run looked identical on disk, and a crash before the run directory
existed left nothing at all. This module makes the lifecycle a recorded fact
without touching any artifact a stage produces:

  <run_dir>/run_status.json   current state of the run (rewritten atomically)
  <run_dir>/events.jsonl      append-only witnesses (statute.event/1)
  <output_root>/_attempts/<id>/   same two files, for runs that failed before
                                  their run directory was created

run_meta.json, latest.json and every artifact are still written by the stage
exactly as before. These files are witnesses, not authority: a reader that
finds run_meta.json + latest.json trusts those, and uses run_status.json only
for timing, progress and failure detail.

Usage (one call to begin, one to attach, one to succeed; failures are caught
automatically through sys.excepthook / atexit):

    rl = runlog.begin("02_parser", output_root=args.output_root,
                      enabled=args.output is None)
    rl.input("01_inventory", inv_run_version, requested=args.inventory_run)
    ...
    rl.attach(run_dir, run_version)          # as soon as the run dir exists
    rl.item("object", oid, "succeeded")      # optional progress
    ...
    rl.succeed(published=True)               # after latest.json is written

Unversioned (--output) runs are deliberately not instrumented: they have no
run_meta/latest.json either, and the test harnesses rely on that mode.

Standard library only. Never raises into the stage: every write is best-effort,
because observability must not be able to break the pipeline.
"""
from __future__ import annotations

import atexit
import hashlib
import json
import os
import re
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_STATUS = "statute.run_status/1"
SCHEMA_EVENT = "statute.event/1"
MAX_MESSAGE = 2000
_STATUS_MIN_INTERVAL = 0.5          # seconds between progress rewrites of run_status.json
_TRACEPARENT_RE = re.compile(r"^[0-9a-f]{2}-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$")
_SCRIPTS_DIR = Path(__file__).resolve().parent

_ACTIVE: "RunLog | None" = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _stamp(dt: datetime) -> str:
    """Folder-safe stamp in the same format as run_version."""
    return dt.strftime("%Y-%m-%dT%H.%M.%S.") + f"{dt.microsecond // 1000:03d}Z"


def _ulid_like() -> str:
    """Time-ordered unique id (48-bit ms timestamp + 80 random bits, Crockford base32)."""
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    n = (int(time.time() * 1000) << 80) | int.from_bytes(os.urandom(10), "big")
    out = []
    for _ in range(26):
        out.append(alphabet[n & 31])
        n >>= 5
    return "".join(reversed(out))


def _truncate(text: str, limit: int = MAX_MESSAGE) -> str:
    text = str(text)
    return text if len(text) <= limit else text[:limit] + f"… [truncated, {len(text)} chars]"


def _code_version(script: Path) -> str | None:
    try:
        return "sha256:" + hashlib.sha256(script.read_bytes()).hexdigest()[:12]
    except OSError:
        return None


def _write_json_atomic(path: Path, payload: dict) -> None:
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    data = json.dumps(payload, indent=2, ensure_ascii=False)
    for attempt in range(5):
        try:
            tmp.write_text(data, encoding="utf-8")
            os.replace(tmp, path)
            return
        except PermissionError:          # a reader holds the file open on Windows
            time.sleep(0.05 * (attempt + 1))
        except OSError:
            break
    try:
        tmp.unlink(missing_ok=True)
    except OSError:
        pass


class RunLog:
    """Lifecycle recorder for one stage invocation."""

    def __init__(self, stage: str, output_root: str | os.PathLike | None, enabled: bool,
                 script: Path | None, argv: list[str]):
        self.stage = stage
        self.enabled = enabled and output_root is not None
        self.output_root = Path(output_root) if output_root is not None else None
        self.started = _now()
        self.attempt_id = _stamp(self.started)
        self.run_dir: Path | None = None
        self.run_version: str | None = None
        self.status = "running"
        self.seq = 0
        self.inputs: list[dict] = []
        self.degraded: list[dict] = []
        self.progress: dict | None = None
        self.current_item: dict | None = None
        self.error: dict | None = None
        self.published = False
        self.finished: datetime | None = None
        self._buffer: list[dict] = []
        self._last_status_write = 0.0
        self._unreadable_sources: set[str] = set()
        tp = os.environ.get("TRACEPARENT", "").strip().lower()
        self.traceparent = tp if _TRACEPARENT_RE.match(tp) else None
        self.code_version = _code_version(script) if script else None
        self.argv = list(argv)
        self.pid = os.getpid()
        self._event("stage_run.started", status="running",
                     data={"argv": self.argv, "code_version": self.code_version})

    # ---- public API -------------------------------------------------------

    def input(self, stage: str, run_version: str | None, requested: str = "latest",
              optional: bool = False) -> None:
        """Record one resolved upstream input (present or absent)."""
        rec = {"stage": stage, "run_version": run_version,
               "resolved": "latest" if requested == "latest" else "pinned",
               "present": run_version is not None, "optional": optional}
        self.inputs.append(rec)
        self._event("stage_run.input_resolved", data=rec)
        if run_version is None and optional:
            self.degrade(stage, "optional input not available")

    def degrade(self, what: str, reason: str) -> None:
        """Declare that the run continued with less than its full input."""
        rec = {"input": what, "reason": reason}
        if rec not in self.degraded:
            self.degraded.append(rec)
            self._event("stage_run.degraded", severity="warning", data=rec)

    def unreadable_source(self, abs_path: str) -> None:
        """Called by a stage's source reader when a source file cannot be read."""
        if abs_path in self._unreadable_sources:
            return
        self._unreadable_sources.add(abs_path)
        self.degrade("source:" + Path(abs_path).name, "source file unreadable or missing")

    def total(self, n: int, unit: str) -> None:
        self.progress = {"done": 0, "total": int(n), "unit": unit}
        self._write_status(force=True)

    def item(self, kind: str, item_id: str, status: str = "succeeded",
             message: str | None = None, severity: str | None = None) -> None:
        """Record a work item finishing (succeeded | failed | skipped | started)."""
        if status == "started":
            self.current_item = {"kind": kind, "id": item_id}
            self._event("item.started", item={"kind": kind, "id": item_id}, status="running")
            # always written: a throttled start would leave a stale "current item" on disk
            # for as long as the item takes (parsing one file can take ~10 s)
            self._write_status(force=True)
            return
        if self.progress is not None and status != "started":
            self.progress["done"] = min(self.progress["done"] + 1, self.progress["total"])
        self.current_item = None
        sev = severity or ("error" if status == "failed" else None)
        self._event(f"item.{status}", item={"kind": kind, "id": item_id}, status=status,
                    severity=sev, message=message)
        self._write_status()

    def attach(self, run_dir: str | os.PathLike, run_version: str) -> None:
        """The run directory now exists: start writing into it."""
        self.run_dir = Path(run_dir)
        self.run_version = run_version
        for ev in self._buffer:
            ev["run_version"] = run_version
        self._flush_buffer()
        self._write_status(force=True)

    def succeed(self, published: bool = True) -> None:
        self.status = "succeeded"
        self.published = published
        self.finished = _now()
        self._event("stage_run.succeeded", status="succeeded",
                    data={"duration_ms": self._duration_ms(), "published": published,
                          "degraded": bool(self.degraded)})
        if published:
            self._event("pointer.published", data={"run_version": self.run_version})
        self._write_status(force=True)

    def fail(self, error_class: str, message: str, where: str | None = None) -> None:
        if self.status in ("succeeded", "failed"):
            return
        self.status = "failed"
        self.finished = _now()
        self.error = {"class": error_class, "message": _truncate(message), "where": where,
                      "last_item": self.current_item}
        self._event("stage_run.failed", status="failed", severity="error",
                    message=_truncate(message, 300),
                    data={"duration_ms": self._duration_ms(), "error": self.error,
                          "run_dir_created": self.run_dir is not None})
        if self.run_dir is None and self.enabled and self.output_root is not None:
            # Nothing to attach to: record the failed attempt beside the runs.
            self.run_dir = self.output_root / "_attempts" / self.attempt_id
            try:
                self.run_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                self.run_dir = None
        self._flush_buffer()
        self._write_status(force=True)

    # ---- internals ----------------------------------------------------------

    def _duration_ms(self) -> int:
        end = self.finished or _now()
        return int((end - self.started).total_seconds() * 1000)

    def _event(self, type_: str, *, status: str | None = None, severity: str | None = None,
               item: dict | None = None, message: str | None = None, data: dict | None = None) -> None:
        self.seq += 1
        ev = {"schema": SCHEMA_EVENT, "event_id": _ulid_like(), "seq": self.seq,
              "time": _iso(_now()), "type": type_, "stage": self.stage,
              "run_version": self.run_version}
        if status:
            ev["status"] = status
        if severity:
            ev["severity"] = severity
        if item:
            ev["item"] = item
        if self.progress is not None and type_.startswith("item."):
            ev["progress"] = dict(self.progress)
        if message:
            ev["message"] = _truncate(message, 500)
        if data:
            ev["data"] = data
        if self.traceparent:
            ev["traceparent"] = self.traceparent
        self._buffer.append(ev)
        if self.run_dir is not None:
            self._flush_buffer()

    def _flush_buffer(self) -> None:
        if not self.enabled or self.run_dir is None or not self._buffer:
            return
        try:
            with open(self.run_dir / "events.jsonl", "a", encoding="utf-8") as fh:
                for ev in self._buffer:
                    fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
            self._buffer.clear()
        except OSError:
            pass

    def _write_status(self, force: bool = False) -> None:
        if not self.enabled or self.run_dir is None:
            return
        now = time.monotonic()
        if not force and now - self._last_status_write < _STATUS_MIN_INTERVAL:
            return
        self._last_status_write = now
        _write_json_atomic(self.run_dir / "run_status.json", {
            "schema": SCHEMA_STATUS,
            "stage": self.stage,
            "run_version": self.run_version,
            "attempt_id": self.attempt_id,
            "status": self.status,
            "started_at": _iso(self.started),
            "updated_at": _iso(_now()),
            "finished_at": _iso(self.finished) if self.finished else None,
            "duration_ms": self._duration_ms() if self.finished else None,
            "pid": self.pid,
            "argv": self.argv,
            "code_version": self.code_version,
            "traceparent": self.traceparent,
            "inputs": self.inputs,
            "degraded": self.degraded,
            "progress": self.progress,
            "current_item": self.current_item,
            "published": self.published,
            "error": self.error,
            "events": self.seq,
        })


# ---- module-level entry points --------------------------------------------------

def begin(stage: str, output_root, enabled: bool = True, argv: list[str] | None = None) -> RunLog:
    """Start recording a stage invocation and install the failure hooks."""
    global _ACTIVE
    script = Path(sys.argv[0]).resolve() if sys.argv and sys.argv[0] else None
    rl = RunLog(stage, output_root, enabled, script, argv if argv is not None else sys.argv[1:])
    _ACTIVE = rl
    if rl.enabled:
        previous = sys.excepthook

        def _hook(exc_type, exc, tb):
            where = None
            for frame in traceback.extract_tb(tb):
                if Path(frame.filename).resolve().parent == _SCRIPTS_DIR:
                    where = f"{Path(frame.filename).name}:{frame.lineno}"
            rl.fail(exc_type.__name__, str(exc), where)
            previous(exc_type, exc, tb)

        sys.excepthook = _hook
        atexit.register(_at_exit, rl)
    return rl


def _at_exit(rl: RunLog) -> None:
    if rl.status == "running":
        rl.fail("Exit", "process exited before the stage recorded completion "
                        "(sys.exit or interruption)")


def note_unreadable_source(abs_path: str) -> None:
    """Hook for the stages' cached source readers; a no-op when no run is active."""
    if _ACTIVE is not None:
        _ACTIVE.unreadable_source(abs_path)


def new_event_id() -> str:
    return _ulid_like()


__all__ = ["begin", "RunLog", "note_unreadable_source", "new_event_id",
           "SCHEMA_STATUS", "SCHEMA_EVENT"]
