"""STATUTE Console server tests.

Fixtures are copies of the repository's real committed output/ tree, mutated into
each scenario the console must recognise. Nothing here writes to the repository.

    cd console/server && python -m unittest discover -s tests -v
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1]))
REPO = HERE.parents[3]

from statute_console import catalog as C                   # noqa: E402
from statute_console import views as V                     # noqa: E402
from statute_console.evidence import entity, search, source_window  # noqa: E402
from statute_console.findings import annotation_status, collect, next_steps, source_check  # noqa: E402
from statute_console.health import run_checks                # noqa: E402
from statute_console.model import Workspace, redact         # noqa: E402
from statute_console.server import App, serve                # noqa: E402

DIRS = {"01_inventory": "inventory", "02_parser": "parser", "03_data": "data", "04_logic": "logic",
        "05_rules": "rules", "06_diagram": "diagram", "07_synthesis": "final_report", "08_graph": "graph"}


def rv_at(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H.%M.%S.") + f"{dt.microsecond // 1000:03d}Z"


class Fixture:
    """A throwaway repo root holding a copy of the committed output and src/."""

    def __init__(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="statute_console_"))
        shutil.copytree(REPO / "output", self.tmp / "output")
        (self.tmp / "src").mkdir()
        for f in (REPO / "src").glob("*.sql"):
            shutil.copy2(f, self.tmp / "src" / f.name)
        (self.tmp / ".claude").mkdir()
        shutil.copytree(REPO / ".claude" / "scripts", self.tmp / ".claude" / "scripts",
                        ignore=shutil.ignore_patterns("__pycache__", "archive"))
        shutil.copytree(REPO / ".claude" / "agents", self.tmp / ".claude" / "agents")

    def ws(self) -> Workspace:
        return Workspace(self.tmp)

    def stage_dir(self, key):
        return self.tmp / "output" / DIRS[key]

    def latest(self, key) -> str:
        return json.loads((self.stage_dir(key) / "latest.json").read_text(encoding="utf-8"))["run_version"]

    def clone_run(self, key, new_rv, publish=True, mutate_meta=None):
        src = self.stage_dir(key) / self.latest(key)
        dst = self.stage_dir(key) / new_rv
        shutil.copytree(src, dst)
        meta = json.loads((dst / "run_meta.json").read_text(encoding="utf-8"))
        meta["run_version"] = new_rv
        if mutate_meta:
            mutate_meta(meta)
        (dst / "run_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        if publish:
            (self.stage_dir(key) / "latest.json").write_text(json.dumps({"run_version": new_rv}), encoding="utf-8")
        return dst

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


NOW = datetime.now(timezone.utc)


class Base(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture()

    def tearDown(self):
        self.fx.close()

    def snap(self):
        return self.fx.ws().snapshot(max_age=0)


# ---------------------------------------------------------------------------

class TestCommittedOutput(Base):
    def test_all_stages_succeeded_and_pipeline_consistent(self):
        s = self.snap()
        for key in DIRS:
            self.assertEqual(s.stages[key]["latest"]["state"], "succeeded", key)
            self.assertEqual(s.stages[key]["latest"]["state_basis"], "recorded")
        p = s.current_pipeline_run()
        self.assertEqual(p["consistency"], "consistent")
        self.assertEqual(p["inferred_members"], ["08_graph"])
        self.assertEqual(len(p["members"]), 8)

    def test_provenance_gaps_are_detected(self):
        s = self.snap()
        self.assertEqual(s.stages["05_rules"]["latest"]["provenance_gaps"], ["04_logic"])
        self.assertEqual(len(s.stages["08_graph"]["latest"]["provenance_gaps"]), 7)
        self.assertEqual(s.stages["05_rules"]["freshness"]["value"], "unknown")
        self.assertEqual(s.stages["02_parser"]["freshness"]["value"], "current")

    def test_source_unreachable_but_identical_under_src(self):
        src = source_check(self.snap())
        self.assertEqual(src["unreachable"], 7)
        self.assertEqual(src["missing"], 0)
        self.assertEqual(src["changed"], 0)

    def test_status_attention_and_next_steps(self):
        st = V.status(self.snap())
        kinds = [a["kind"] for a in st["attention"]]
        self.assertIn("source_unreachable", kinds)
        self.assertIn("SME_REVIEW_REQUIRED", kinds)
        prov = [a for a in st["attention"] if a["kind"] == "provenance_unrecorded"]
        self.assertEqual(len(prov), 1, "provenance rows must be grouped into one")
        self.assertEqual(prov[0]["count"], 2)
        self.assertEqual(st["next_steps"]["stages"][0]["stage"], "01_inventory")
        for s in st["stages"]:
            for e in (s["latest"] or {}).get("evidence", []):
                self.assertFalse(Path(e["path"]).is_absolute(), e)

    def test_timeline_reports_between_invocation_time(self):
        s = self.snap()
        tl = V.timeline(s, s.current_pipeline_run())
        self.assertTrue(tl["partial"])
        self.assertGreater(tl["between_ms"], tl["in_stage_ms"])

    def test_evidence_br002_traces_to_line_79(self):
        s = self.snap()
        e = entity(s, s.current_pipeline_run(), "rule", "BR-002")
        self.assertEqual(e["location"]["line"], 79)
        self.assertEqual([x["kind"] for x in e["provenance"]], ["requirement", "rule", "statement", "object", "file"])
        w = source_window(s, s.current_pipeline_run(), e["location"]["file_id"], 79, 3)
        self.assertTrue(w["available"])
        self.assertIn("e_insufficient_balance", next(l["text"] for l in w["lines"] if l["n"] == 79))

    def test_ddl_rule_without_line_still_traces(self):
        s = self.snap()
        e = entity(s, s.current_pipeline_run(), "rule", "BR-014")
        self.assertEqual(e["location"]["table"], "ACCOUNTS")
        self.assertIn("table", [x["kind"] for x in e["provenance"]])

    def test_search(self):
        s = self.snap()
        r = search(s, s.current_pipeline_run(), "accounts.balance")
        self.assertEqual(r[0]["id"], "ACCOUNTS.BALANCE")

    def test_health_catches_agent_spec_drift(self):
        checks = {c["id"]: c for c in run_checks(self.snap())}
        self.assertEqual(checks["H8"]["status"], "warn")
        self.assertTrue(any("checkpoints" in d for d in checks["H8"]["details"]))
        self.assertEqual(checks["H3"]["status"], "warn")
        self.assertEqual(checks["H4"]["status"], "pass")


class TestScenarios(Base):
    def test_newer_parser_run_makes_downstream_unsynced(self):
        self.fx.clone_run("02_parser", rv_at(NOW))
        s = self.snap()
        self.assertEqual(s.stages["02_parser"]["freshness"]["value"], "current")
        for key in ("03_data", "04_logic", "05_rules"):
            self.assertEqual(s.stages[key]["freshness"]["value"], "unsynced", key)
        self.assertEqual(s.stages["06_diagram"]["freshness"]["value"], "unsynced")      # consumes parser directly
        self.assertEqual(s.stages["07_synthesis"]["freshness"]["value"], "unsynced")
        ns = next_steps(s, None)
        self.assertEqual(ns["stages"][0]["stage"], "03_data")
        self.assertIn("02_parser", s.current_pipeline_run()["superseded_by"])

    def test_pinned_input_is_not_stale(self):
        old = self.fx.latest("02_parser")
        new = rv_at(NOW)
        self.fx.clone_run("02_parser", new)
        d = self.fx.stage_dir("03_data") / self.fx.latest("03_data")
        (d / "run_status.json").write_text(json.dumps({
            "schema": "statute.run_status/1", "status": "succeeded", "started_at": "2026-07-29T16:05:52.383Z",
            "finished_at": "2026-07-29T16:05:57.983Z", "inputs": [
                {"stage": "01_inventory", "run_version": self.fx.latest("01_inventory"), "resolved": "latest", "present": True},
                {"stage": "02_parser", "run_version": old, "resolved": "pinned", "present": True}]}), encoding="utf-8")
        self.assertEqual(self.snap().stages["03_data"]["freshness"]["value"], "pinned")

    def test_crashed_legacy_directory_is_inferred(self):
        d = self.fx.stage_dir("02_parser") / rv_at(NOW - timedelta(hours=2))
        (d / "raw_structure").mkdir(parents=True)
        old = time.time() - 7200
        os.utime(d / "raw_structure", (old, old))
        os.utime(d, (old, old))
        s = self.snap()
        r = s.stages["02_parser"]["newest"]
        self.assertEqual((r["state"], r["state_basis"]), ("crashed", "inferred"))
        fs = collect(s)
        self.assertTrue(any(f["kind"] == "run_crashed" for f in fs))

    def test_failed_attempt_before_run_dir(self):
        a = self.fx.stage_dir("02_parser") / "_attempts" / rv_at(NOW)
        a.mkdir(parents=True)
        (a / "run_status.json").write_text(json.dumps({
            "schema": "statute.run_status/1", "stage": "02_parser", "status": "failed",
            "started_at": NOW.isoformat(), "finished_at": NOW.isoformat(),
            "error": {"class": "FileNotFoundError", "message": "No inventory runs found: C:\\Users\\x y\\secret\\latest.json",
                      "where": "02_parser.py:73"}}), encoding="utf-8")
        s = self.snap()
        f = next(f for f in collect(s) if f["kind"] == "run_failed")
        self.assertIn("FileNotFoundError", f["title"])
        self.assertNotIn("Users", f["detail"])
        self.assertEqual(next_steps(s, None)["stages"][0]["stage"], "02_parser")
        # a failed run must never print a stats sentence built from an empty summary
        d = V.stage_run_detail(s, "02_parser", "attempt:" + a.name)
        self.assertTrue(d["summary_text"][0].startswith("Failed before writing its summary"))
        self.assertNotIn("?", " ".join(d["summary_text"]))

    def test_running_and_stalled(self):
        d = self.fx.stage_dir("02_parser") / rv_at(NOW)
        d.mkdir()
        rs = {"schema": "statute.run_status/1", "stage": "02_parser", "status": "running",
              "started_at": (NOW - timedelta(seconds=14)).isoformat(), "updated_at": NOW.isoformat(),
              "progress": {"done": 3, "total": 5, "unit": "objects parsed"},
              "current_item": {"kind": "object", "id": "PROC-.SP_TRANSFER_FUNDS"}}
        (d / "run_status.json").write_text(json.dumps(rs), encoding="utf-8")
        s = self.snap()
        n = s.stages["02_parser"]["newest"]
        self.assertEqual(n["state"], "running")
        self.assertEqual(n["current_item"]["id"], "PROC-.SP_TRANSFER_FUNDS")
        self.assertEqual(V.status(s)["running"], ["02_parser"])
        self.assertTrue(next_steps(s, None)["running"])
        rs["updated_at"] = (NOW - timedelta(minutes=30)).isoformat()
        (d / "run_status.json").write_text(json.dumps(rs), encoding="utf-8")
        self.assertEqual(self.snap().stages["02_parser"]["newest"]["state"], "crashed")

    def test_unpublished_success(self):
        self.fx.clone_run("05_rules", rv_at(NOW), publish=False)
        fs = collect(self.snap())
        self.assertTrue(any(f["kind"] == "run_unpublished" for f in fs))

    def test_declared_degradation(self):
        d = self.fx.stage_dir("05_rules") / self.fx.latest("05_rules")
        (d / "run_status.json").write_text(json.dumps({
            "schema": "statute.run_status/1", "status": "succeeded", "started_at": NOW.isoformat(),
            "finished_at": NOW.isoformat(), "degraded": [{"input": "04_logic", "reason": "optional input not available"}],
            "inputs": [{"stage": "04_logic", "run_version": None, "resolved": "latest", "present": False, "optional": True}]}),
            encoding="utf-8")
        fs = collect(self.snap())
        self.assertTrue(any(f["kind"] == "degraded" and f["stage"] == "05_rules" for f in fs))

    def test_inconsistent_pipeline(self):
        newp = rv_at(NOW - timedelta(minutes=5))
        self.fx.clone_run("02_parser", newp)
        self.fx.clone_run("03_data", rv_at(NOW - timedelta(minutes=4)),
                          mutate_meta=lambda m: m["upstream"].update(parser_run_version=newp))
        data_rv = self.fx.latest("03_data")
        self.fx.clone_run("07_synthesis", rv_at(NOW - timedelta(minutes=3)),
                          mutate_meta=lambda m: m["upstream"].update(data_run_version=data_rv))
        s = self.snap()
        p = s.current_pipeline_run()
        self.assertEqual(p["consistency"], "inconsistent")
        self.assertEqual(p["inconsistencies"][0]["stage"], "02_parser")
        self.assertTrue(any(f["kind"] == "inconsistent" for f in collect(s)))

    def test_annotation_applied_orphaned_and_repointed(self):
        rules_dir = self.fx.clone_run("05_rules", rv_at(NOW - timedelta(minutes=2)))
        art = json.loads((rules_dir / "rules_artifact.json").read_text(encoding="utf-8"))
        r1 = next(r for r in art["business_rules"] if r["rule_id"] == "BR-001")
        r2 = next(r for r in art["business_rules"] if r["rule_id"] == "BR-002")
        r1["rule_id"], r2["rule_id"] = "BR-002", "BR-001"          # a renumbering
        (rules_dir / "rules_artifact.json").write_text(json.dumps(art), encoding="utf-8")
        new_rules = rules_dir.name
        self.fx.clone_run("07_synthesis", rv_at(NOW - timedelta(minutes=1)),
                          mutate_meta=lambda m: m["upstream"].update(rules_run_version=new_rules))
        (self.fx.tmp / "brd_annotations.json").write_text(json.dumps({"annotations": {
            "BR-001": {"note": "regulatory"}, "table:ACCOUNTS": {"note": "master"},
            "table:NO_SUCH_TABLE": {"note": "x"}, "executive_summary": {"note": "y"}}}), encoding="utf-8")
        s = self.snap()
        st = {e["key"]: e["status"] for e in annotation_status(s, s.current_pipeline_run())["entries"]}
        self.assertEqual(st, {"BR-001": "repointed", "table:ACCOUNTS": "applied",
                              "table:NO_SUCH_TABLE": "orphaned", "executive_summary": "applied"})
        kinds = {f["kind"] for f in collect(s)}
        self.assertIn("annotation_repointed", kinds)
        self.assertIn("annotation_orphaned", kinds)

    def test_unreadable_annotations(self):
        (self.fx.tmp / "brd_annotations.json").write_text("{not json", encoding="utf-8")
        self.assertTrue(any(f["kind"] == "annotations_unreadable" for f in collect(self.snap())))

    def test_source_change_detected(self):
        f = next((self.fx.tmp / "src").glob("05_*.sql"))
        f.write_text(f.read_text(encoding="utf-8") + "\n-- edited\n", encoding="utf-8")
        src = source_check(self.snap())
        self.assertEqual(src["changed"], 1)

    def test_events_are_read_incrementally(self):
        d = self.fx.stage_dir("02_parser") / self.fx.latest("02_parser")
        lines = [json.dumps({"schema": "statute.event/1", "seq": i, "time": f"2026-07-29T16:05:{40 + i}.000Z",
                             "type": "item.succeeded", "stage": "02_parser", "item": {"kind": "object", "id": f"O{i}"}})
                 for i in range(1, 6)]
        (d / "events.jsonl").write_text("\n".join(lines) + "\n{torn", encoding="utf-8")
        (d / "run_status.json").write_text(json.dumps({"status": "succeeded", "started_at": "2026-07-29T16:05:37.101Z",
                                                       "finished_at": "2026-07-29T16:05:51.683Z"}), encoding="utf-8")
        s = self.snap()
        ev = V.run_events(s, "02_parser", d.name, after=3)
        self.assertEqual([e["seq"] for e in ev["events"]], [4, 5])
        self.assertIn("malformed", ev["error"])
        self.assertEqual(V.recent_events(s, since="2026-07-29T16:05:43.000Z")["total"], 2)


class TestCatalogue(Base):
    """The dashboard tabs read STATUTE's own artifacts; check them against the committed run."""

    def setUp(self):
        super().setUp()
        self.s = self.snap()
        self.p = self.s.current_pipeline_run()

    def test_agents_come_from_the_harness_definitions(self):
        rows = C.agents(self.s)
        self.assertEqual([r["stage"] for r in rows], list(DIRS))
        self.assertTrue(all(r["description"] and r["script"].endswith(".py") for r in rows))
        self.assertTrue(all(r["llm_in_generation"] is False for r in rows))

    def test_statement_trace_covers_every_parsed_statement(self):
        t = C.statement_trace(self.s, self.p)
        self.assertEqual(len(t["objects"]), 5)
        self.assertEqual(len(t["entries"]), 124)
        self.assertEqual(t["counts"]["total"], 124)
        self.assertEqual(sum(v for k, v in t["counts"].items() if k != "total"), 124)
        one = C.statement_trace(self.s, self.p, "PROC-.SP_TRANSFER_FUNDS")
        self.assertTrue(one["entries"] and all(e["object"] == "PROC-.SP_TRANSFER_FUNDS" for e in one["entries"]))
        self.assertEqual([e["step"] for e in one["entries"]], list(range(1, len(one["entries"]) + 1)))

    def test_rules_quality_and_brd(self):
        r = C.rules(self.s, self.p)
        self.assertEqual(len(r["rules"]), 41)
        br2 = next(x for x in r["rules"] if x["rule_id"] == "BR-002")
        self.assertEqual(br2["line"], 79)
        q = C.quality(self.s, self.p)
        self.assertEqual(q["total_rules"], 41)
        bc = q["by_confidence"]
        expect = round((bc.get("confirmed", 0) + bc.get("high", 0) * 0.9 + bc.get("medium", 0) * 0.5 + bc.get("low", 0) * 0.2) / 41 * 100)
        self.assertEqual(q["score"], expect)
        b = C.brd(self.s, self.p)
        self.assertEqual(b["name"], "brd.md")
        self.assertIn("Business Requirements Document", b["content"])

    def test_data_model_and_diagrams(self):
        d = C.data_model(self.s, self.p)
        self.assertEqual(len(d["tables"]), 15)
        acc = next(t for t in d["tables"] if t["table"] == "ACCOUNTS")
        self.assertTrue(acc["used_by"])
        self.assertTrue(d["erd"] and d["erd"].lstrip().startswith("erDiagram"))
        g = C.diagrams(self.s, self.p)
        self.assertEqual(len(g["diagrams"]), 7)
        self.assertTrue(all(x["source"] for x in g["diagrams"]))

    def test_artifact_catalogue_and_kpis(self):
        a = C.artifacts_all(self.s, self.p)
        self.assertEqual(len(a["artifacts"]), 73)
        self.assertEqual(a["total_bytes"], sum(x["bytes"] for x in a["artifacts"]))
        st = V.status(self.s)
        k = st["kpis"]
        self.assertEqual((k["stages_done"], k["stages_total"], k["objects"], k["statements"], k["tables"], k["rules"]),
                         (8, 8, 5, 124, 15, 41))
        self.assertEqual(k["artifacts"], 73)


class TestCompare(Base):
    def test_identical_and_changed(self):
        self.fx.clone_run("07_synthesis", rv_at(NOW))
        s = self.snap()
        a, b = s.pipeline_runs[1], s.pipeline_runs[0]
        from statute_console.compare import compare
        c = compare(s, a, b)
        differing = [x["stage"] for x in c["stages"] if x["files_changed"] or x["files_added"] or x["files_removed"]]
        # the older pipeline run owns the (time-inferred) graph run; the clone has none
        self.assertEqual(differing, ["08_graph"])
        self.assertFalse(c["rules"]["added"] or c["rules"]["removed"] or c["rules"]["changed"])
        self.assertEqual(c["gaps"]["count_a"], c["gaps"]["count_b"])


class TestRedaction(unittest.TestCase):
    def test_paths_with_spaces(self):
        self.assertEqual(redact(r"The inventory records E:\Virtusa Projects\plsql_to_brd\src."),
                         "The inventory records …/src.")
        self.assertEqual(redact("No such file: 'E:\\Virtusa Projects\\statute\\src\\x.sql.moved'"),
                         "No such file: '…/x.sql.moved'")
        self.assertEqual(redact(r"see C:\Users\me\x y\file.json for detail"), "see …/file.json for detail")
        self.assertEqual(redact(r"\\server\share\f.sql gone"), "…/f.sql gone")
        self.assertEqual(redact("relative/path ok, ratio 3:1"), "relative/path ok, ratio 3:1")

    def test_linear_time(self):
        t = time.perf_counter()
        redact("x" * 20000 + "E:\\" + "a b " * 20000)
        self.assertLess(time.perf_counter() - t, 1.0)


class TestHttp(Base):
    def setUp(self):
        super().setUp()
        static = self.fx.tmp / "static"
        static.mkdir()
        (static / "index.html").write_text("<!doctype html><title>t</title>", encoding="utf-8")
        (static / "app.js").write_text("console.log(1)", encoding="utf-8")
        self.httpd = serve(self.fx.ws(), "127.0.0.1", 0, static)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        super().tearDown()

    def req(self, method, path, host=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": host or f"127.0.0.1:{self.port}", **(headers or {})}
        c.request(method, path, headers=h)
        r = c.getresponse()
        body = r.read()
        c.close()
        return r, body

    def test_status_and_security_headers(self):
        r, body = self.req("GET", "/api/v1/status")
        self.assertEqual(r.status, 200)
        self.assertIn("default-src 'self'", r.getheader("Content-Security-Policy"))
        self.assertEqual(r.getheader("X-Content-Type-Options"), "nosniff")
        etag = r.getheader("ETag")
        r2, _ = self.req("GET", "/api/v1/status", headers={"If-None-Match": etag})
        self.assertIn(r2.status, (200, 304))

    def test_rejects_foreign_host(self):
        r, _ = self.req("GET", "/api/v1/status", host="evil.example:80")
        self.assertEqual(r.status, 421)

    def test_read_only(self):
        for m in ("POST", "PUT", "DELETE", "PATCH"):
            r, _ = self.req(m, "/api/v1/status")
            self.assertEqual(r.status, 405, m)

    def test_no_traversal(self):
        for p in ("/../../output/inventory/latest.json", "/%2e%2e/%2e%2e/README.md", "/..%5c..%5cREADME.md",
                  "/api/v1/stages/02_parser/runs/..%2f..%2finventory", "/api/v1/stages/../runs/x"):
            r, body = self.req("GET", p)
            self.assertNotIn(b"run_version", body if r.status == 200 and b"<title>" not in body else b"", p)
            self.assertIn(r.status, (200, 400, 404), p)
        r, body = self.req("GET", "/api/v1/stages/02_parser/runs/..%2F..%2Finventory")
        self.assertEqual(r.status, 404)

    def test_spa_fallback_and_missing_asset(self):
        r, body = self.req("GET", "/runs/synthesis@x")
        self.assertEqual(r.status, 200)
        self.assertIn(b"<title>", body)
        r, _ = self.req("GET", "/assets/missing.js")
        self.assertEqual(r.status, 404)
        # deep links whose last segment is a run version (contains dots) are client routes
        for p in ("/runs/synthesis@2026-07-29T16.06.14.998Z", "/stages/02_parser/runs/2026-07-29T16.05.37.101Z",
                  "/evidence/object/PROC-.SP_TRANSFER_FUNDS", "/evidence/column/ACCOUNTS.BALANCE"):
            r, body = self.req("GET", p)
            self.assertEqual(r.status, 200, p)
            self.assertIn(b"<title>", body, p)

    def test_every_endpoint_answers_and_never_writes(self):
        before = _tree_hash(self.fx.tmp / "output")
        s = self.fx.ws().snapshot(max_age=0)
        p = s.current_pipeline_run()["id"]
        rv = self.fx.latest("02_parser")
        arts = json.loads(self.req("GET", f"/api/v1/stages/07_synthesis/runs/{self.fx.latest('07_synthesis')}/artifacts")[1])
        aid = next(a["id"] for a in arts["artifacts"] if a["path"] == "brd.md")
        paths = ["/api/v1/status", "/api/v1/stages", "/api/v1/stages/02_parser", f"/api/v1/stages/02_parser/runs/{rv}",
                 f"/api/v1/stages/02_parser/runs/{rv}/items", f"/api/v1/stages/02_parser/runs/{rv}/findings",
                 f"/api/v1/stages/02_parser/runs/{rv}/events", f"/api/v1/stages/07_synthesis/runs/{self.fx.latest('07_synthesis')}/artifacts/{aid}",
                 "/api/v1/pipeline-runs", f"/api/v1/pipeline-runs/{p}", "/api/v1/findings?category=review",
                 "/api/v1/evidence/search?q=BR-00", "/api/v1/evidence/rule/BR-002", "/api/v1/evidence/table/ACCOUNTS",
                 "/api/v1/source?file_id=05_MEDIUM_FUND_TRANSFER_WITH_VALIDATION__5E3A3BBB&line=79",
                 f"/api/v1/compare?a={p}&b={p}", "/api/v1/health", "/api/v1/events", "/api/v1/annotations",
                 "/api/v1/agents", "/api/v1/trace", "/api/v1/trace?object=PROC-.SP_TRANSFER_FUNDS", "/api/v1/rules",
                 "/api/v1/catalogue", "/api/v1/brd", "/api/v1/data-model", "/api/v1/diagrams", "/api/v1/quality"]
        for path in paths:
            r, body = self.req("GET", path)
            self.assertEqual(r.status, 200, path)
            self.assertNotRegex(body.decode("utf-8"), r"[A-Za-z]:\\\\(Users|Virtusa)", path)
        self.assertEqual(before, _tree_hash(self.fx.tmp / "output"), "the console must never write")

    def test_unknown_things_404(self):
        for p in ("/api/v1/stages/09_nope", "/api/v1/evidence/rule/BR-999", "/api/v1/evidence/weird/x",
                  "/api/v1/source?file_id=NOPE&line=1", "/api/v1/pipeline-runs/nope", "/api/v1/nope"):
            r, _ = self.req("GET", p)
            self.assertEqual(r.status, 404, p)


def _tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(root.rglob("*")):
        if f.is_file():
            h.update(f.relative_to(root).as_posix().encode())
            h.update(f.read_bytes())
    return h.hexdigest()


class TestRealRepositoryReadOnly(unittest.TestCase):
    """Runs against the real repository without writing to it."""

    def test_real_output_loads(self):
        if not (REPO / "output").is_dir():
            self.skipTest("no output/")
        before = _tree_hash(REPO / "output")
        app = App(Workspace(REPO), None)
        st = app.handle_api("/api/v1/status", {})
        self.assertEqual(len(st["stages"]), 8)
        app.handle_api("/api/v1/health", {})
        self.assertEqual(before, _tree_hash(REPO / "output"))


if __name__ == "__main__":
    unittest.main()
