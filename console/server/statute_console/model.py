"""Workspace scanning and derivations.

Everything here is *derived on read* from STATUTE's own files and never
persisted. Every derived status carries the evidence (repo-relative file paths)
that justifies it, and anything inferred rather than recorded says so.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import registry as R

RUNNING_STALE_AFTER = timedelta(minutes=5)     # run_status "running" with no update for this long -> crashed
INFER_RUNNING_WITHIN = timedelta(minutes=2)    # legacy dir without any record, touched this recently -> running?
RV_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}\.\d{2}\.\d{2}\.\d{3}Z$")
SEVERITY_ORDER = ["critical", "high", "medium", "low", "info"]


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_rv(rv: str | None) -> datetime | None:
    if not rv or not RV_RE.match(rv):
        return None
    return datetime.strptime(rv[:-1], "%Y-%m-%dT%H.%M.%S.%f").replace(tzinfo=timezone.utc)


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z") if dt else None


_PATH_START_RE = re.compile(r"(?:(?<![A-Za-z0-9])[A-Za-z]:[\\/]|\\\\)")
_PATH_STOP = set("'\"<>|\r\n,;()")


def redact(text) -> str:
    """Replace absolute filesystem paths with '…/<name>' — never ship local paths.

    A linear scan, not a regex: directory names may contain spaces ("Virtusa Projects"),
    so a path runs until a quote/bracket/newline; within it, only the final component is
    kept, and anything after the first space in that component is ordinary prose.
    """
    if text is None:
        return ""
    s = str(text)
    out, i = [], 0
    while True:
        m = _PATH_START_RE.search(s, i)
        if not m:
            out.append(s[i:])
            break
        out.append(s[i:m.start()])
        j = m.end()
        while j < len(s) and s[j] not in _PATH_STOP:
            j += 1
        span = s[m.end():j]
        last_sep = max(span.rfind("\\"), span.rfind("/"))
        tail = span[last_sep + 1:] if last_sep >= 0 else span
        name, sep, rest = tail.partition(" ")
        if last_sep < 0 and sep:          # e.g. "C:\foo bar": nothing after the drive but prose
            name, rest = tail.split(" ", 1)[0], tail.split(" ", 1)[1]
        out.append("…/" + name + (sep + rest if sep else ""))
        i = j
    return "".join(out)


def sev_rank(sev: str) -> int:
    return SEVERITY_ORDER.index(sev) if sev in SEVERITY_ORDER else len(SEVERITY_ORDER)


class JsonCache:
    """Parsed-JSON cache keyed by (mtime_ns, size). Returns (data, error)."""

    def __init__(self):
        self._d: dict[str, tuple] = {}
        self._lock = threading.Lock()

    def load(self, path: Path):
        try:
            st = path.stat()
        except OSError:
            return None, "missing"
        sig = (st.st_mtime_ns, st.st_size)
        key = str(path)
        with self._lock:
            hit = self._d.get(key)
            if hit and hit[0] == sig:
                return hit[1], hit[2]
        data, err = None, None
        for attempt in range(3):          # a writer may be replacing the file right now
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                err = None
                break
            except (OSError, ValueError) as e:
                err = f"unreadable: {type(e).__name__}"
                time.sleep(0.02 * (attempt + 1))
        with self._lock:
            self._d[key] = (sig, data, err)
        return data, err

    def load_jsonl(self, path: Path):
        try:
            st = path.stat()
        except OSError:
            return [], "missing"
        sig = (st.st_mtime_ns, st.st_size)
        key = "L:" + str(path)
        with self._lock:
            hit = self._d.get(key)
            if hit and hit[0] == sig:
                return hit[1], hit[2]
        rows, bad = [], 0
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        bad += 1          # torn last line while a writer appends
        except OSError as e:
            return [], f"unreadable: {type(e).__name__}"
        err = f"{bad} malformed line(s)" if bad else None
        with self._lock:
            self._d[key] = (sig, rows, err)
        return rows, err


# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------

class Workspace:
    def __init__(self, repo: Path, output: Path | None = None, source_roots: list[Path] | None = None,
                 annotations: Path | None = None):
        self.repo = repo.resolve()
        self.output = (output or self.repo / "output").resolve()
        self.scripts = self.repo / ".claude" / "scripts"
        self.agents = self.repo / ".claude" / "agents"
        # Source files may only be read from these roots (never from a path an artifact names elsewhere).
        self.source_roots = [p.resolve() for p in (source_roots or [self.repo])]
        self.fallback_source = self.repo / "src"
        self.annotations_path = annotations or self.repo / "brd_annotations.json"
        self.cache = JsonCache()
        self._snap = None
        self._snap_at = 0.0
        self._lock = threading.Lock()

    # ---- paths ----------------------------------------------------------
    def rel(self, p: Path | str | None) -> str | None:
        if p is None:
            return None
        p = Path(p)
        try:
            return p.resolve().relative_to(self.repo).as_posix()
        except (ValueError, OSError):
            return "…/" + p.name

    def stage_dir(self, key: str) -> Path:
        return self.output / R.BY_KEY[key]["dir"]

    def run_dir(self, key: str, rv: str) -> Path | None:
        if not (RV_RE.match(rv) or rv.startswith("attempt:")):
            return None
        base = self.stage_dir(key)
        d = base / "_attempts" / rv.split(":", 1)[1] if rv.startswith("attempt:") else base / rv
        try:
            d = d.resolve()
            d.relative_to(self.output)
        except (ValueError, OSError):
            return None
        return d if d.is_dir() else None

    def load_json(self, path: Path):
        return self.cache.load(path)

    # ---- snapshot -------------------------------------------------------
    def snapshot(self, max_age: float = 0.75) -> "Snapshot":
        with self._lock:
            if self._snap is not None and time.monotonic() - self._snap_at < max_age:
                return self._snap
            snap = Snapshot(self)
            self._snap, self._snap_at = snap, time.monotonic()
            return snap

    # ---- source files ---------------------------------------------------
    def resolve_source(self, meta: dict) -> tuple[Path | None, str]:
        """Locate a corpus file: the recorded abs_path if it is inside an allowed root,
        else the same relative path under ./src. Returns (path, how)."""
        candidates = []
        if meta.get("abs_path"):
            candidates.append((Path(meta["abs_path"]), "recorded path"))
        if meta.get("file"):
            candidates.append((self.fallback_source / meta["file"], "relative path under src/"))
        for p, how in candidates:
            try:
                rp = p.resolve()
            except OSError:
                continue
            if rp.suffix.lower() != ".sql" or not rp.is_file():
                continue
            if any(_is_within(rp, root) for root in self.source_roots):
                return rp, how
        return None, "not found"


def _is_within(p: Path, root: Path) -> bool:
    try:
        p.relative_to(root)
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Snapshot: one consistent read of the output tree
# ---------------------------------------------------------------------------

class Snapshot:
    def __init__(self, ws: Workspace):
        self.ws = ws
        self.taken_at = now_utc()
        self.stages: dict[str, dict] = {}
        self.runs: dict[tuple[str, str], dict] = {}
        for s in R.STAGES:
            self.stages[s["key"]] = self._scan_stage(s)
        self._derive_freshness()
        self.pipeline_runs = self._derive_pipeline_runs()

    # ---- scanning -------------------------------------------------------
    def _scan_stage(self, s: dict) -> dict:
        ws, key = self.ws, s["key"]
        sdir = ws.stage_dir(key)
        latest, latest_err = ws.load_json(sdir / "latest.json")
        latest_rv = (latest or {}).get("run_version") if isinstance(latest, dict) else None
        runs, attempts = [], []
        if sdir.is_dir():
            for entry in sorted(os.scandir(sdir), key=lambda e: e.name, reverse=True):
                if entry.is_dir() and RV_RE.match(entry.name):
                    runs.append(self._build_run(key, Path(entry.path), latest_rv))
            adir = sdir / "_attempts"
            if adir.is_dir():
                for entry in sorted(os.scandir(adir), key=lambda e: e.name, reverse=True):
                    if entry.is_dir():
                        attempts.append(self._build_run(key, Path(entry.path), latest_rv, attempt=True))
        for r in runs + attempts:
            self.runs[(key, r["id"])] = r
        latest_run = next((r for r in runs if r["run_version"] == latest_rv), None)
        info = {
            "stage": key, "title": s["title"], "n": s["n"], "purpose": s["purpose"],
            "dir": ws.rel(sdir),
            "latest_run_version": latest_rv,
            "latest_error": None if latest is not None or latest_err == "missing" else latest_err,
            "latest_missing_dir": bool(latest_rv) and latest_run is None,
            "runs": runs, "attempts": attempts,
            "latest": latest_run,
        }
        # the newest activity of any kind (run or attempt) — what is happening *now*
        newest = sorted(runs + attempts, key=lambda r: r["sort_key"], reverse=True)
        info["newest"] = newest[0] if newest else None
        return info

    def _build_run(self, key: str, d: Path, latest_rv: str | None, attempt: bool = False) -> dict:
        ws = self.ws
        rv = d.name
        meta, meta_err = ws.load_json(d / "run_meta.json")
        rs, rs_err = ws.load_json(d / "run_status.json")
        meta = meta if isinstance(meta, dict) else None
        rs = rs if isinstance(rs, dict) else None
        evidence = []
        reason = None
        if rs:
            evidence.append({"label": "run_status.json", "path": ws.rel(d / "run_status.json")})
            st = rs.get("status")
            if st == "succeeded":
                state = "succeeded"
            elif st == "failed":
                state = "failed"
            else:
                upd = parse_iso(rs.get("updated_at")) or parse_iso(rs.get("started_at"))
                if upd and self.taken_at - upd > RUNNING_STALE_AFTER:
                    state = "crashed"
                    reason = (f"recorded as running but not updated for "
                              f"{_human_delta(self.taken_at - upd)} — the process ended without recording an outcome")
                else:
                    state = "running"
            basis = "recorded"
        elif meta:
            state, basis = "succeeded", "recorded"
        else:
            newest = _newest_mtime(d)
            basis = "inferred"
            if newest and self.taken_at - newest < INFER_RUNNING_WITHIN:
                state = "running"
                reason = "no run_meta.json yet and the directory changed moments ago — probably still running"
            else:
                state = "crashed"
                reason = ("no run_meta.json and no run_status.json — the process stopped before recording "
                          "an outcome (crash, kill, or an un-instrumented failure)")
        if meta:
            evidence.append({"label": "run_meta.json", "path": ws.rel(d / "run_meta.json")})
        if meta_err and meta_err != "missing":
            reason = f"run_meta.json is {meta_err}"

        # ---- inputs / provenance --------------------------------------
        upstream, provenance_gaps = [], []
        if rs and isinstance(rs.get("inputs"), list):
            for i in rs["inputs"]:
                upstream.append({"stage": i.get("stage"), "run_version": i.get("run_version"),
                                 "resolved": i.get("resolved", "latest"), "present": bool(i.get("present")),
                                 "optional": bool(i.get("optional")), "source": "run_status"})
        elif meta:
            ups = meta.get("upstream") if isinstance(meta.get("upstream"), dict) else {}
            for field, sk in R.UPSTREAM_FIELDS.items():
                if field in ups:
                    v = ups[field]
                    upstream.append({"stage": sk, "run_version": v, "resolved": "unknown",
                                     "present": v is not None, "optional": sk in R.BY_KEY[key]["optional"],
                                     "source": "run_meta"})
        recorded = {u["stage"] for u in upstream}
        if not attempt and state == "succeeded":
            provenance_gaps = [i for i in R.inputs_of(key) if i not in recorded]

        degraded = []
        if rs:
            degraded = [dict(x) for x in rs.get("degraded") or []]
        if meta and isinstance(meta.get("quality"), dict):
            for lab in meta["quality"].get("degraded_inputs") or []:
                sk = R.BY_DIR.get(lab, {}).get("key", lab)
                if not any(x.get("input") == sk for x in degraded):
                    degraded.append({"input": sk, "reason": "optional input not available"})

        # ---- timing ---------------------------------------------------
        started = finished = None
        timing_basis = None
        if rs:
            started = parse_iso(rs.get("started_at"))
            finished = parse_iso(rs.get("finished_at"))
            timing_basis = "recorded"
        elif meta:
            started = parse_rv(rv)
            finished = parse_iso(meta.get("generated_at"))
            timing_basis = "partial"
            if started and finished and finished < started:      # 07 stamps generated_at before run_version
                finished = started
        else:
            started = parse_rv(rv)
            timing_basis = "inferred"
        if state == "running" and started:
            duration_ms = int((self.taken_at - started).total_seconds() * 1000)
        elif started and finished:
            duration_ms = int((finished - started).total_seconds() * 1000)
        else:
            duration_ms = None
        if rs and rs.get("duration_ms") is not None:
            duration_ms = rs["duration_ms"]
        if key == "01_inventory" and timing_basis == "partial":
            duration_ms = None                       # stage 1 stamps start only

        summary = None
        if meta:
            for k in ("stats_summary", "quality", "counts", "stats"):
                if isinstance(meta.get(k), dict):
                    summary = {"kind": k, "values": meta[k]}
                    break

        error = None
        if rs and rs.get("error"):
            e = rs["error"]
            error = {"class": e.get("class"), "message": redact(e.get("message")), "where": e.get("where"),
                     "last_item": e.get("last_item")}

        rid = ("attempt:" + rv) if attempt else rv
        sort_dt = started or parse_rv(rv) or datetime.fromtimestamp(0, timezone.utc)
        published = (not attempt) and rv == latest_rv
        return {
            "stage": key, "id": rid, "run_version": None if attempt else rv, "attempt": attempt,
            "dir": ws.rel(d),
            "state": state, "state_basis": basis, "state_reason": reason,
            "published": published,
            "started_at": iso(started), "finished_at": iso(finished), "duration_ms": duration_ms,
            "timing_basis": timing_basis,
            "generated_at": (meta or {}).get("generated_at"),
            "upstream": upstream, "provenance_gaps": provenance_gaps,
            "degraded": degraded,
            "summary": summary,
            "progress": (rs or {}).get("progress"),
            "current_item": (rs or {}).get("current_item") if state == "running" else None,
            "error": error,
            "instrumented": rs is not None,
            "code_version": (rs or {}).get("code_version"),
            "traceparent": (rs or {}).get("traceparent"),
            "events": (rs or {}).get("events"),
            "evidence": evidence,
            "sort_key": iso(sort_dt),
        }

    # ---- freshness ------------------------------------------------------
    def _derive_freshness(self):
        latest_rv = {k: v["latest_run_version"] for k, v in self.stages.items() if v["latest"]}
        for key in R.ORDER:
            st = self.stages[key]
            run = st["latest"]
            causes = []
            if run is None:
                st["freshness"] = {"value": "never_run" if not st["runs"] else "unknown",
                                   "causes": [] if not st["runs"] else
                                   [{"kind": "unknown", "text": "latest.json does not name an existing run"}]}
                continue
            for u in run["upstream"]:
                cur = latest_rv.get(u["stage"])
                if u["run_version"] is None:
                    if cur and u["optional"]:
                        causes.append({"kind": "unsynced", "stage": u["stage"],
                                       "text": f"ran without {u['stage']}; a {u['stage']} run now exists"})
                    continue
                if cur and cur != u["run_version"]:
                    if u["resolved"] == "pinned":
                        causes.append({"kind": "pinned", "stage": u["stage"],
                                       "text": f"pinned to {u['stage']} {u['run_version']} (latest is {cur})"})
                    elif cur > u["run_version"]:
                        causes.append({"kind": "unsynced", "stage": u["stage"],
                                       "text": f"newer {u['stage']} run exists ({cur}); this run consumed {u['run_version']}"})
                    else:
                        causes.append({"kind": "unsynced", "stage": u["stage"],
                                       "text": f"consumed {u['stage']} {u['run_version']}, which is no longer published (latest {cur})"})
            for g in run["provenance_gaps"]:
                if latest_rv.get(g):
                    causes.append({"kind": "unknown", "stage": g,
                                   "text": f"does not record which {g} run it consumed"})
            for u in run["upstream"]:
                up = self.stages.get(u["stage"], {}).get("freshness", {})
                if up.get("value") in ("unsynced", "upstream_unsynced") and not any(
                        c["kind"] == "unsynced" and c.get("stage") == u["stage"] for c in causes):
                    causes.append({"kind": "upstream_unsynced", "stage": u["stage"],
                                   "text": f"{u['stage']} is itself out of date"})
            kinds = {c["kind"] for c in causes}
            for v in ("unsynced", "upstream_unsynced", "unknown", "pinned"):
                if v in kinds:
                    value = v
                    break
            else:
                value = "current"
            st["freshness"] = {"value": value, "causes": causes}

    # ---- pipeline runs --------------------------------------------------
    def _derive_pipeline_runs(self) -> list[dict]:
        syn = self.stages["07_synthesis"]
        graph_runs = [r for r in self.stages["08_graph"]["runs"] if r["state"] == "succeeded"]
        anchors = [r for r in syn["runs"] if r["state"] == "succeeded"]
        anchor_rvs = sorted(r["run_version"] for r in anchors)
        out = []
        for a in anchors:
            members = {"07_synthesis": a}
            refs: dict[str, dict[str, list[str]]] = {}
            missing = []
            queue = [a]
            while queue:
                r = queue.pop()
                for u in r["upstream"]:
                    if not u["run_version"]:
                        continue
                    refs.setdefault(u["stage"], {}).setdefault(u["run_version"], []).append(r["stage"])
                    if u["stage"] not in members:
                        m = self.runs.get((u["stage"], u["run_version"]))
                        if m:
                            members[u["stage"]] = m
                            queue.append(m)
                        elif (u["stage"], u["run_version"]) not in missing:
                            missing.append((u["stage"], u["run_version"]))
            inconsistent = {s: v for s, v in refs.items() if len(v) > 1}
            # attach a graph run: recorded provenance first, else inferred by time window
            g_member, g_inferred = None, False
            for g in sorted(graph_runs, key=lambda r: r["run_version"], reverse=True):
                rec = next((u for u in g["upstream"] if u["stage"] == "07_synthesis"), None)
                if rec and rec["run_version"] == a["run_version"]:
                    g_member = g
                    break
            if g_member is None:
                nxt = next((rv for rv in anchor_rvs if rv > a["run_version"]), None)
                window = [g for g in graph_runs if not any(u["stage"] == "07_synthesis" for u in g["upstream"])
                          and g["run_version"] > a["run_version"] and (nxt is None or g["run_version"] < nxt)]
                if window:
                    g_member, g_inferred = max(window, key=lambda r: r["run_version"]), True
            if g_member:
                members["08_graph"] = g_member
            superseded_by = [k for k, m in members.items()
                             if self.stages[k]["latest_run_version"] and
                             self.stages[k]["latest_run_version"] != m["run_version"]]
            starts = [parse_iso(m["started_at"]) for m in members.values() if m["started_at"]]
            ends = [parse_iso(m["finished_at"]) or parse_iso(m["started_at"]) for m in members.values()]
            ends = [e for e in ends if e]
            out.append({
                "id": f"synthesis@{a['run_version']}",
                "anchor": a["run_version"],
                "members": {k: m["run_version"] for k, m in sorted(members.items())},
                "inferred_members": ["08_graph"] if g_inferred else [],
                "missing_members": [{"stage": s, "run_version": v} for s, v in missing],
                "consistency": "inconsistent" if inconsistent else ("incomplete" if missing else "consistent"),
                "inconsistencies": [{"stage": s, "versions": [{"run_version": v, "consumed_by": c}
                                                                for v, c in sorted(vs.items())]}
                                    for s, vs in sorted(inconsistent.items())],
                "is_current": a["run_version"] == syn["latest_run_version"],
                "superseded_by": superseded_by,
                "started_at": iso(min(starts)) if starts else None,
                "finished_at": iso(max(ends)) if ends else None,
                "span_ms": int((max(ends) - min(starts)).total_seconds() * 1000) if starts and ends else None,
            })
        out.sort(key=lambda p: p["anchor"], reverse=True)
        return out

    # ---- accessors -------------------------------------------------------
    def current_pipeline_run(self) -> dict | None:
        return next((p for p in self.pipeline_runs if p["is_current"]), None) or \
            (self.pipeline_runs[0] if self.pipeline_runs else None)

    def pipeline_run(self, pid: str) -> dict | None:
        return next((p for p in self.pipeline_runs if p["id"] == pid), None)

    def member_dir(self, prun: dict | None, key: str) -> Path | None:
        """Run directory for a stage within a pipeline run (or the published run)."""
        rv = (prun or {}).get("members", {}).get(key) if prun else self.stages[key]["latest_run_version"]
        return self.ws.run_dir(key, rv) if rv else None

    def artifact(self, prun: dict | None, key: str, filename: str | None = None):
        d = self.member_dir(prun, key)
        if d is None:
            return None
        data, _ = self.ws.load_json(d / (filename or R.BY_KEY[key]["artifact"]))
        return data if isinstance(data, dict) else None


def _newest_mtime(d: Path) -> datetime | None:
    newest = None
    try:
        for e in os.scandir(d):
            try:
                m = e.stat().st_mtime
            except OSError:
                continue
            newest = m if newest is None or m > newest else newest
        m = d.stat().st_mtime
        newest = m if newest is None or m > newest else newest
    except OSError:
        return None
    return datetime.fromtimestamp(newest, timezone.utc) if newest else None


def _human_delta(td: timedelta) -> str:
    s = int(td.total_seconds())
    if s < 90:
        return f"{s} s"
    if s < 5400:
        return f"{s // 60} min"
    if s < 172800:
        return f"{s // 3600} h"
    return f"{s // 86400} days"


def public_run(r: dict | None) -> dict | None:
    """Run record as served by the API (drop internal sort key)."""
    if r is None:
        return None
    return {k: v for k, v in r.items() if k != "sort_key"}
