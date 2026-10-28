"""Read-only HTTP server for the STATUTE Console (standard library only).

Security posture (see dashboard research §40):
  * binds 127.0.0.1 by default and validates the Host header (DNS-rebinding defence)
  * GET/HEAD only — there is no state-changing endpoint
  * never accepts a filesystem path from the client: runs, artifacts and source
    files are addressed by IDs that the server maps to paths and re-checks
  * strict CSP, nosniff, no-referrer; JSON responses carry ETags
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import sys
import threading
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import catalog as K
from . import compare as C
from . import evidence as E
from . import health as H
from . import registry as R
from . import views as V
from .findings import annotation_status, collect, source_check
from .model import Workspace, public_run, sev_rank

API_VERSION = "v1"
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
       "font-src 'self' data:; connect-src 'self'; frame-src 'self' blob: data:; object-src 'none'; "
       "base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
STAGE_RE = re.compile(r"^0[1-8]_[a-z]+$")
STATIC_EXT = {".js", ".mjs", ".css", ".map", ".png", ".svg", ".ico", ".woff", ".woff2", ".ttf", ".html", ".txt", ".webmanifest"}


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def _q(params, name, default=None):
    v = params.get(name)
    return v[0] if v else default


def _int(params, name, default, lo=0, hi=100000):
    try:
        return max(lo, min(hi, int(_q(params, name, default))))
    except (TypeError, ValueError):
        raise ApiError(400, f"'{name}' must be an integer")


class App:
    def __init__(self, ws: Workspace, static_dir: Path | None):
        self.ws = ws
        self.static_dir = static_dir.resolve() if static_dir and static_dir.is_dir() else None
        self.routes = [
            (r"^/api/v1/status$", self.status),
            (r"^/api/v1/stages$", self.stages),
            (r"^/api/v1/stages/(?P<stage>[^/]+)$", self.stage),
            (r"^/api/v1/stages/(?P<stage>[^/]+)/runs/(?P<rid>[^/]+)$", self.stage_run),
            (r"^/api/v1/stages/(?P<stage>[^/]+)/runs/(?P<rid>[^/]+)/items$", self.stage_run_items),
            (r"^/api/v1/stages/(?P<stage>[^/]+)/runs/(?P<rid>[^/]+)/findings$", self.stage_run_findings),
            (r"^/api/v1/stages/(?P<stage>[^/]+)/runs/(?P<rid>[^/]+)/events$", self.stage_run_events),
            (r"^/api/v1/stages/(?P<stage>[^/]+)/runs/(?P<rid>[^/]+)/artifacts$", self.artifacts),
            (r"^/api/v1/stages/(?P<stage>[^/]+)/runs/(?P<rid>[^/]+)/artifacts/(?P<aid>[0-9a-f]{16})$", self.artifact),
            (r"^/api/v1/pipeline-runs$", self.pipeline_runs),
            (r"^/api/v1/pipeline-runs/(?P<pid>[^/]+)$", self.pipeline_run),
            (r"^/api/v1/findings$", self.findings),
            (r"^/api/v1/evidence/search$", self.evidence_search),
            (r"^/api/v1/evidence/(?P<kind>[a-z]+)/(?P<eid>[^/]+)$", self.evidence),
            (r"^/api/v1/source$", self.source),
            (r"^/api/v1/compare$", self.compare),
            (r"^/api/v1/health$", self.health),
            (r"^/api/v1/events$", self.events),
            (r"^/api/v1/annotations$", self.annotations),
            (r"^/api/v1/agents$", self.agents),
            (r"^/api/v1/trace$", self.trace),
            (r"^/api/v1/rules$", self.rules),
            (r"^/api/v1/catalogue$", self.catalogue),
            (r"^/api/v1/brd$", self.brd),
            (r"^/api/v1/data-model$", self.data_model),
            (r"^/api/v1/diagrams$", self.diagrams),
            (r"^/api/v1/quality$", self.quality),
        ]
        self.routes = [(re.compile(p), f) for p, f in self.routes]

    # ---- helpers -----------------------------------------------------------
    def _stage(self, key):
        if not STAGE_RE.match(key) or key not in R.BY_KEY:
            raise ApiError(404, f"unknown stage '{key}'")
        return key

    def _prun(self, snap, params, required=False):
        pid = _q(params, "pipeline_run")
        if pid:
            p = snap.pipeline_run(pid)
            if not p:
                raise ApiError(404, f"unknown pipeline run '{pid}'")
            return p
        p = snap.current_pipeline_run()
        if required and not p:
            raise ApiError(404, "no pipeline run exists yet")
        return p

    # ---- handlers ------------------------------------------------------------
    def status(self, snap, params):
        return V.status(snap)

    def stages(self, snap, params):
        return {"stages": [{**{k: s[k] for k in ("key", "n", "title", "purpose", "script", "agent", "requires", "optional")},
                            "downstream": R.downstream_of(s["key"]),
                            "latest_run_version": snap.stages[s["key"]]["latest_run_version"],
                            "freshness": snap.stages[s["key"]].get("freshness")} for s in R.STAGES]}

    def stage(self, snap, params, stage):
        return V.stage_info(snap, self._stage(stage))

    def stage_run(self, snap, params, stage, rid):
        out = V.stage_run_detail(snap, self._stage(stage), unquote(rid))
        if out is None:
            raise ApiError(404, "unknown run")
        return out

    def stage_run_items(self, snap, params, stage, rid):
        out = V.stage_run_items(snap, self._stage(stage), unquote(rid))
        if out is None:
            raise ApiError(404, "unknown run")
        return out

    def stage_run_findings(self, snap, params, stage, rid):
        out = V.stage_run_findings(snap, self._stage(stage), unquote(rid))
        if out is None:
            raise ApiError(404, "unknown run")
        return {"findings": out}

    def stage_run_events(self, snap, params, stage, rid):
        out = V.run_events(snap, self._stage(stage), unquote(rid), _int(params, "after", 0),
                           _int(params, "limit", 1000, 1, 5000))
        if out is None:
            raise ApiError(404, "unknown run")
        return out

    def artifacts(self, snap, params, stage, rid):
        out = V.list_artifacts(snap, self._stage(stage), unquote(rid))
        if out is None:
            raise ApiError(404, "unknown run")
        return {"artifacts": out}

    def artifact(self, snap, params, stage, rid, aid):
        out = V.read_artifact(snap, self._stage(stage), unquote(rid), aid)
        if out is None:
            raise ApiError(404, "unknown artifact")
        return out

    def pipeline_runs(self, snap, params):
        return {"pipeline_runs": [V.pipeline_summary(snap, p) for p in snap.pipeline_runs],
                "grid": [{"stage": k, "title": R.BY_KEY[k]["title"],
                          "runs": [{"id": r["id"], "run_version": r["run_version"], "state": r["state"],
                                    "state_basis": r["state_basis"], "published": r["published"],
                                    "attempt": r["attempt"], "started_at": r["started_at"],
                                    "duration_ms": r["duration_ms"],
                                    "upstream": [{"stage": u["stage"], "run_version": u["run_version"]} for u in r["upstream"]]}
                                   for r in sorted(snap.stages[k]["runs"] + snap.stages[k]["attempts"],
                                                   key=lambda r: r["sort_key"], reverse=True)[:_int(params, "limit", 30, 1, 500)]]}
                         for k in R.ORDER]}

    def pipeline_run(self, snap, params, pid):
        p = snap.pipeline_run(unquote(pid))
        if not p:
            raise ApiError(404, "unknown pipeline run")
        return V.pipeline_detail(snap, p)

    def findings(self, snap, params):
        prun = self._prun(snap, params)
        fs = collect(snap, prun)
        cat, sev, stage, q = (_q(params, "category"), _q(params, "severity"), _q(params, "stage"),
                              (_q(params, "q") or "").lower())
        total = {c: sum(1 for f in fs if f["category"] == c) for c in ("run", "lineage", "source", "content", "review")}
        if cat:
            fs = [f for f in fs if f["category"] == cat]
        if sev:
            fs = [f for f in fs if sev_rank(f["severity"]) <= sev_rank(sev)]
        if stage:
            fs = [f for f in fs if f.get("stage") == stage]
        if q:
            fs = [f for f in fs if q in (f["title"] + " " + (f.get("detail") or "") + " " + f["kind"]).lower()]
        return {"pipeline_run": (prun or {}).get("id"), "by_category": total, "findings": fs}

    def evidence_search(self, snap, params):
        return {"results": E.search(snap, self._prun(snap, params), _q(params, "q", ""))}

    def evidence(self, snap, params, kind, eid):
        if kind not in E.KINDS:
            raise ApiError(404, f"unknown evidence kind '{kind}'")
        out = E.entity(snap, self._prun(snap, params), kind, unquote(eid))
        if out is None:
            raise ApiError(404, f"{kind} '{unquote(eid)}' not found in this pipeline run")
        return out

    def source(self, snap, params):
        fid = _q(params, "file_id")
        if not fid:
            raise ApiError(400, "file_id is required")
        out = E.source_window(snap, self._prun(snap, params), fid, _int(params, "line", 1, 1),
                              _int(params, "context", 3, 0, 25))
        if out is None:
            raise ApiError(404, "unknown file")
        return out

    def compare(self, snap, params):
        a, b = snap.pipeline_run(_q(params, "a", "")), snap.pipeline_run(_q(params, "b", ""))
        if not a or not b:
            raise ApiError(400, "a and b must be pipeline run ids")
        return C.compare(snap, a, b)

    def health(self, snap, params):
        return {"checks": H.run_checks(snap), "source": source_check(snap)}

    def events(self, snap, params):
        return V.recent_events(snap, _q(params, "since"), _int(params, "limit", 500, 1, 5000))

    def annotations(self, snap, params):
        return annotation_status(snap, self._prun(snap, params))

    def agents(self, snap, params):
        return {"agents": K.agents(snap)}

    def trace(self, snap, params):
        return K.statement_trace(snap, self._prun(snap, params), _q(params, "object"))

    def rules(self, snap, params):
        return K.rules(snap, self._prun(snap, params))

    def catalogue(self, snap, params):
        return K.artifacts_all(snap, self._prun(snap, params))

    def brd(self, snap, params):
        out = K.brd(snap, self._prun(snap, params))
        if out is None:
            raise ApiError(404, "no BRD has been synthesised yet")
        return out

    def data_model(self, snap, params):
        return K.data_model(snap, self._prun(snap, params))

    def diagrams(self, snap, params):
        return K.diagrams(snap, self._prun(snap, params))

    def quality(self, snap, params):
        return K.quality(snap, self._prun(snap, params))

    # ---- dispatch -----------------------------------------------------------
    def handle_api(self, path, params):
        snap = self.ws.snapshot()
        for rx, fn in self.routes:
            m = rx.match(path)
            if m:
                return fn(snap, params, **m.groupdict())
        raise ApiError(404, "no such endpoint")


def make_handler(app: App, allowed_hosts: set[str]):
    class Handler(BaseHTTPRequestHandler):
        server_version = "STATUTE-Console/1"
        sys_version = ""

        def log_message(self, fmt, *args):            # quiet; errors still reported
            pass

        def _headers(self, status, ctype, length, extra=None):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(length))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()

        def _json(self, status, payload, head=False):
            body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            etag = '"' + hashlib.sha1(body).hexdigest() + '"'
            if status == 200 and self.headers.get("If-None-Match") == etag:
                self._headers(304, "application/json", 0, {"ETag": etag, "Cache-Control": "no-cache"})
                return
            self._headers(status, "application/json; charset=utf-8", len(body),
                          {"ETag": etag, "Cache-Control": "no-cache"})
            if not head:
                self.wfile.write(body)

        def _deny(self, status, msg):
            self._json(status, {"error": msg})

        def do_GET(self, head=False):
            host = (self.headers.get("Host") or "").lower()
            if host not in allowed_hosts:
                return self._deny(421, "unexpected Host header")
            url = urlparse(self.path)
            path = url.path
            if "\x00" in path or "\\" in unquote(path):
                return self._deny(400, "invalid path")
            if path.startswith("/api/"):
                try:
                    payload = app.handle_api(path, parse_qs(url.query))
                    return self._json(200, payload, head)
                except ApiError as e:
                    return self._json(e.status, {"error": e.message}, head)
                except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError):
                    return None   # the browser navigated away mid-response; nothing to answer
                except Exception:  # noqa: BLE001
                    traceback.print_exc(file=sys.stderr)
                    return self._json(500, {"error": "internal error — see console server log"}, head)
            return self._static(path, head)

        def do_HEAD(self):
            self.do_GET(head=True)

        def _refuse(self):
            self._deny(405, "the console is read-only")

        do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = _refuse

        def _static(self, path, head):
            root = app.static_dir
            if root is None:
                msg = b"STATUTE Console API is running. Build the UI: cd console/web && npm run build"
                self._headers(200, "text/plain; charset=utf-8", len(msg))
                if not head:
                    self.wfile.write(msg)
                return
            rel = unquote(path).lstrip("/")
            target = (root / rel).resolve() if rel else root / "index.html"
            try:
                target.relative_to(root)
            except ValueError:
                return self._deny(404, "not found")
            if not target.is_file() or target.is_symlink():
                # Run versions contain dots (2026-07-29T16.06.14.998Z), so "has a dot" cannot mean
                # "is a file": only the build's asset folder and real static types 404.
                if rel.startswith("assets/") or Path(rel).suffix.lower() in STATIC_EXT:
                    return self._deny(404, "not found")
                target = root / "index.html"              # SPA route
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript",):
                ctype += "; charset=utf-8"
            data = target.read_bytes()
            cache = "no-cache" if target.name == "index.html" else "public, max-age=31536000, immutable"
            self._headers(200, ctype, len(data), {"Cache-Control": cache})
            if not head:
                self.wfile.write(data)

    return Handler


def serve(ws: Workspace, host: str, port: int, static_dir: Path | None) -> ThreadingHTTPServer:
    app = App(ws, static_dir)
    allowed: set[str] = set()
    httpd = ThreadingHTTPServer((host, port), make_handler(app, allowed))
    real_port = httpd.server_address[1]           # port 0 -> the OS-assigned port
    allowed.update(f"{h}:{real_port}" for h in ("127.0.0.1", "localhost"))
    if host not in ("127.0.0.1", "localhost"):
        allowed.add(f"{host}:{real_port}")
    httpd.daemon_threads = True
    return httpd


__all__ = ["serve", "App", "ApiError", "public_run", "threading"]
