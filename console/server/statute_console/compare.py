"""Compare two pipeline runs by stable keys (never by BR-nnn, which is renumbered)."""
from __future__ import annotations

import hashlib

from . import registry as R
from .model import Snapshot

SKIP_FILES = {"run_meta.json", "run_status.json", "events.jsonl"}


def _rule_key(r: dict) -> str:
    s = r.get("source") or {}
    anchor = s.get("statement_id") or "/".join(str(x) for x in (s.get("table"), s.get("constraint_name") or s.get("column") or s.get("view")) if x)
    return f"{s.get('kind')}|{anchor}|{r.get('condition_text')}"


def _hashes(snap: Snapshot, prun: dict, key: str) -> dict[str, str]:
    d = snap.member_dir(prun, key)
    out = {}
    if not d:
        return out
    for f in sorted(d.rglob("*")):
        if f.is_file() and f.name not in SKIP_FILES:
            try:
                out[f.relative_to(d).as_posix()] = hashlib.sha256(f.read_bytes()).hexdigest()
            except OSError:
                pass
    return out


def _numbers(v, prefix=""):
    out = {}
    if isinstance(v, dict):
        for k, x in v.items():
            out.update(_numbers(x, f"{prefix}{k}."))
    elif isinstance(v, (int, float)) and not isinstance(v, bool):
        out[prefix[:-1]] = v
    return out


def compare(snap: Snapshot, a: dict, b: dict) -> dict:
    stages = []
    for key in R.ORDER:
        ra, rb = a["members"].get(key), b["members"].get(key)
        run_a = snap.runs.get((key, ra)) if ra else None
        run_b = snap.runs.get((key, rb)) if rb else None
        na = _numbers(((run_a or {}).get("summary") or {}).get("values"))
        nb = _numbers(((run_b or {}).get("summary") or {}).get("values"))
        deltas = [{"metric": k, "a": na.get(k), "b": nb.get(k)} for k in sorted(set(na) | set(nb))
                  if na.get(k) != nb.get(k)]
        ha, hb = _hashes(snap, a, key) if ra else {}, _hashes(snap, b, key) if rb else {}
        changed = sorted(p for p in set(ha) & set(hb) if ha[p] != hb[p])
        stages.append({"stage": key, "a": ra, "b": rb, "same_run": ra == rb, "metric_deltas": deltas,
                       "files_changed": changed, "files_added": sorted(set(hb) - set(ha)),
                       "files_removed": sorted(set(ha) - set(hb)), "files_compared": len(set(ha) & set(hb))})

    def rules(p):
        return {_rule_key(r): r for r in (snap.artifact(p, "05_rules") or {}).get("business_rules", [])}
    ra, rb = rules(a), rules(b)
    added = [{"key": k, "id": rb[k]["rule_id"], "name": rb[k].get("name")} for k in sorted(set(rb) - set(ra))]
    removed = [{"key": k, "id": ra[k]["rule_id"], "name": ra[k].get("name")} for k in sorted(set(ra) - set(rb))]
    changed, renumbered = [], []
    for k in sorted(set(ra) & set(rb)):
        x, y = ra[k], rb[k]
        diffs = {f: {"a": x.get(f), "b": y.get(f)} for f in ("name", "category", "confidence", "requires_sme_review", "is_enforced")
                 if x.get(f) != y.get(f)}
        if diffs:
            changed.append({"key": k, "id_a": x["rule_id"], "id_b": y["rule_id"], "changes": diffs})
        if x["rule_id"] != y["rule_id"]:
            renumbered.append({"key": k, "id_a": x["rule_id"], "id_b": y["rule_id"], "name": y.get("name")})

    def gaps(p):
        return {f"{g.get('gap_type')}|{g.get('title')}": g for g in
                (snap.artifact(p, "07_synthesis", "gaps_register.json") or {}).get("gaps", [])}
    ga, gb = gaps(a), gaps(b)
    return {
        "a": a["id"], "b": b["id"], "stages": stages,
        "rules": {"added": added, "removed": removed, "changed": changed, "renumbered": renumbered,
                  "count_a": len(ra), "count_b": len(rb)},
        "gaps": {"opened": [{"title": gb[k].get("title"), "severity": gb[k].get("severity")} for k in sorted(set(gb) - set(ga))],
                 "closed": [{"title": ga[k].get("title"), "severity": ga[k].get("severity")} for k in sorted(set(ga) - set(gb))],
                 "count_a": len(ga), "count_b": len(gb)},
        "identical": all(not s["files_changed"] and not s["files_added"] and not s["files_removed"] for s in stages),
    }
