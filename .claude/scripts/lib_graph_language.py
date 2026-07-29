#!/usr/bin/env python3
"""
Plain-English questions over the knowledge graph — deterministically.

WHY NOT AN LLM
--------------
The obvious way to turn English into Cypher is to ask a language model. This
pipeline does not, for the same reason it generates no other content that way:
a fabricated Cypher query returns a plausible, wrong answer, and the user has
no way to tell. Worse, an impact-analysis answer that silently omits a caller
is exactly the failure mode that makes a modernization project fail.

So the interface is an INTENT CATALOGUE. Each supported question is a named
intent with trigger patterns, a resolver that answers from the in-memory graph,
and the equivalent Cypher so the same question can be run against Neo4j. If a
question does not match an intent, the tool says so and lists what it can
answer — it never guesses. Recall is imperfect and precision is total, which is
the correct trade for this domain.

The catalogue is the deliverable as much as the graph is: the impact-analysis
literature notes that practitioners struggle to formulate queries at all, and
jQAssistant ships its value as a rule library rather than as a schema.
"""

import re

# Words that carry no selective meaning; stripped before entity matching.
_STOP = {
    "what", "which", "who", "where", "how", "many", "much", "is", "are", "the", "a", "an",
    "of", "in", "on", "to", "for", "from", "by", "with", "and", "or", "do", "does", "did",
    "i", "me", "my", "we", "us", "show", "list", "find", "get", "give", "tell", "all",
    "any", "please", "can", "you", "if", "it", "that", "this", "there", "be", "been",
}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower().strip(" ?.!"))


def _tokens(text: str):
    return [t for t in re.split(r"[^a-z0-9_.]+", _norm(text)) if t and t not in _STOP]


def resolve_entity(graph, question: str):
    """
    Find the column / table / object / rule the question is about.

    Matching is deliberately literal — an exact identifier first, then a
    business title, then a distinctive token. Guessing a near-match would
    produce a confident answer about the wrong entity.
    """
    q = _norm(question)
    toks = _tokens(question)

    # Rule id, e.g. BR-014
    m = re.search(r"\b(br-\d{3})\b", q)
    if m and m.group(1).upper() in graph.nodes.get("BusinessRule", {}):
        return ("BusinessRule", m.group(1).upper())

    # Qualified column, e.g. accounts.balance
    m = re.search(r"\b([a-z_][a-z0-9_]*)\.([a-z_][a-z0-9_]*)\b", q)
    if m:
        cid = f"{m.group(1).upper()}.{m.group(2).upper()}"
        if cid in graph.nodes.get("Column", {}):
            return ("Column", cid)

    # Exact node key or name, longest first so ACCOUNTS beats ACCOUNT.
    for label in ("Table", "Object", "Column", "Sequence", "Index"):
        candidates = []
        for key, props in graph.nodes.get(label, {}).items():
            for cand in filter(None, [key, props.get("name"), props.get("title")]):
                c = str(cand).lower()
                if c and (c in q or c.replace("_", " ") in q):
                    candidates.append((len(c), label, key))
        if candidates:
            return max(candidates)[1:]

    # Bare column name mentioned without its table.
    for key, props in graph.nodes.get("Column", {}).items():
        if str(props.get("name", "")).lower() in toks:
            return ("Column", key)
    return (None, None)


# ---------------------------------------------------------------------------
# Intents
# ---------------------------------------------------------------------------

def _fmt(label, key, graph):
    p = graph.nodes.get(label, {}).get(key, {})
    return p.get("title") or p.get("name") or key


class Intent:
    def __init__(self, name, question, patterns, cypher, answer, needs_entity=None):
        self.name = name
        self.question = question
        self.patterns = [re.compile(p) for p in patterns]
        self.cypher = cypher
        self.answer = answer
        self.needs_entity = needs_entity

    def matches(self, q):
        return any(p.search(q) for p in self.patterns)


def _impact(graph, label, key):
    """
    Everything that would be affected by changing this column.

    Includes rules that constrain the column's TABLE as well as the column
    itself: a reviewer changing ACCOUNTS.BALANCE needs to see a CHECK
    constraint on ACCOUNTS, even though that rule is not column-scoped.
    """
    if label != "Column":
        return None
    props = graph.nodes["Column"][key]
    rows = []
    for rtype, lab, k in graph.inn("Column", key):
        if lab == "Object" and rtype in ("READS_COLUMN", "WRITES_COLUMN"):
            rows.append([_fmt(lab, k, graph),
                         "reads" if rtype == "READS_COLUMN" else "writes",
                         "program unit"])
        elif lab == "Statement" and rtype in ("READS_COLUMN", "WRITES_COLUMN"):
            s = graph.nodes["Statement"][k]
            unit = _fmt("Object", s.get("object_id"), graph)
            rows.append([f"{unit} — line {s.get('line')}",
                         "reads" if rtype == "READS_COLUMN" else "writes",
                         s.get("type", "")])
        elif rtype == "CONSTRAINS":
            rows.append([f"{k} {graph.nodes[lab][k].get('name', '')}",
                         "constrains this column", "business rule"])
        elif rtype == "COVERS":
            rows.append([k, "indexes this column",
                         "UNIQUE — enforces a rule" if graph.nodes[lab][k].get("unique")
                         else "performance"])
        elif rtype == "POPULATES":
            rows.append([k, "populates this column", "sequence"])

    table = props.get("table")
    for rtype, lab, k in graph.inn("Table", table):
        if rtype == "CONSTRAINS_TABLE":
            rows.append([f"{k} {graph.nodes[lab][k].get('name', '')}",
                         "constrains this table", "business rule"])
    if props.get("is_primary_key"):
        for rtype, lab, k in graph.inn("Table", table):
            if rtype == "REFERENCES":
                rows.append([_fmt(lab, k, graph), "foreign key onto this table",
                             "referential integrity"])

    header = ["Depends on it", "How", "Kind"]
    note = (f"{table}.{props.get('name')} — {props.get('oracle_type')}"
            f"{' — PRIMARY KEY' if props.get('is_primary_key') else ''}"
            f"{'' if props.get('nullable') else ' — NOT NULL'}")
    return header, sorted(rows), note


def _rules_for(graph, label, key):
    if label == "Object":
        rows = [[k, graph.nodes["BusinessRule"][k].get("name"),
                 graph.nodes["BusinessRule"][k].get("category"),
                 graph.nodes["BusinessRule"][k].get("line")]
                for rt, lab, k in graph.inn("Object", key) if rt == "ENFORCED_IN"]
        return ["Rule", "Statement", "Category", "Line"], sorted(rows), _fmt(label, key, graph)
    if label in ("Column", "Table"):
        rt_name = "CONSTRAINS" if label == "Column" else "CONSTRAINS_TABLE"
        rows = [[k, graph.nodes["BusinessRule"][k].get("name"),
                 graph.nodes["BusinessRule"][k].get("category"), ""]
                for rt, lab, k in graph.inn(label, key) if rt == rt_name]
        return ["Rule", "Statement", "Category", ""], sorted(rows), _fmt(label, key, graph)
    return None


def _where_rule(graph, label, key):
    if label != "BusinessRule":
        return None
    p = graph.nodes["BusinessRule"][key]
    rows = []
    for rt, lab, k in graph.out("BusinessRule", key):
        if rt == "ENFORCED_IN":
            rows.append(["Program unit", _fmt(lab, k, graph), ""])
        elif rt == "IMPLEMENTED_AT":
            s = graph.nodes["Statement"][k]
            rows.append(["Statement", s.get("type"), f"line {s.get('line')}"])
        elif rt in ("CONSTRAINS", "CONSTRAINS_TABLE"):
            rows.append(["Constrains", k, ""])
    rows.append(["Origin", p.get("origin", ""), ""])
    rows.append(["Confidence", p.get("confidence", ""),
                 "needs review" if p.get("needs_review") else ""])
    rows.append(["Verification", p.get("verification_method", ""), ""])
    return ["Aspect", "Value", "Detail"], rows, f"{key} — {p.get('name')}"


def _touching(graph, label, key):
    if label != "Table":
        return None
    rows = []
    for rt, lab, k in graph.inn("Table", key):
        if rt in ("READS", "WRITES", "TOUCHES"):
            ops = next((r[5].get("operations", "") for r in graph.rels
                        if r[0] == "WRITES" and r[2] == k and r[4] == key), "")
            rows.append([_fmt(lab, k, graph),
                         "writes" if rt == "WRITES" else "reads", ops])
    seen, uniq = set(), []
    for r in sorted(rows):
        if tuple(r[:2]) in seen:
            continue
        seen.add(tuple(r[:2]))
        uniq.append(r)
    return ["Program unit", "Access", "Operations"], uniq, _fmt(label, key, graph)


def _unreviewed(graph, *_):
    rows = [[k, p.get("name"), p.get("category"), p.get("confidence")]
            for k, p in graph.nodes.get("BusinessRule", {}).items() if p.get("needs_review")]
    return ["Rule", "Statement", "Category", "Confidence"], sorted(rows), \
        "Rules whose business meaning was inferred and is not confirmed"


def _unenforced(graph, *_):
    rows = [[k, p.get("name"), p.get("origin")]
            for k, p in graph.nodes.get("BusinessRule", {}).items() if p.get("is_enforced") is False]
    return ["Rule", "Statement", "Origin"], sorted(rows), \
        "Rules the database records but does not enforce"


def _complex(graph, *_):
    rows = [[p.get("title"), p.get("cyclomatic"), p.get("shape"), p.get("rule_count")]
            for k, p in graph.nodes.get("Object", {}).items()]
    rows.sort(key=lambda r: -(r[1] or 0))
    return ["Program unit", "Decision paths", "Style", "Rules"], rows, \
        "Program units by cyclomatic complexity, highest first"


def _hot_columns(graph, *_):
    rows = [[k, p.get("usage_count"), p.get("oracle_type")]
            for k, p in graph.nodes.get("Column", {}).items() if (p.get("usage_count") or 0) > 0]
    rows.sort(key=lambda r: -(r[1] or 0))
    return ["Column", "Used by units", "Type"], rows[:25], \
        "Columns referenced by the most program units — change these last"


def _orphan_tables(graph, *_):
    rows = []
    for k, p in graph.nodes.get("Table", {}).items():
        if not [r for r in graph.inn("Table", k) if r[0] in ("READS", "WRITES", "TOUCHES")]:
            rows.append([k, p.get("column_count"), "no program unit in this codebase touches it"])
    return ["Table", "Columns", "Observation"], sorted(rows), \
        "Tables defined in the schema but never accessed by the analysed code"


def _interface(graph, label, key):
    if label != "Object":
        return None
    rows = [[graph.nodes["Parameter"][k].get("name"),
             graph.nodes["Parameter"][k].get("mode"),
             graph.nodes["Parameter"][k].get("data_type")]
            for rt, lab, k in graph.out("Object", key) if rt == "HAS_PARAMETER"]
    return ["Parameter", "Direction", "Type"], rows, _fmt(label, key, graph)


def _blind_spots(graph, *_):
    rows = [[k, p.get("detail")] for k, p in graph.nodes.get("BlindSpot", {}).items()]
    return ["Blind spot", "What the graph cannot see"], sorted(rows), \
        "Known limits of this graph — no automated analysis is complete"


def _gaps(graph, *_):
    rows = [[k, p.get("severity"), p.get("title")]
            for k, p in graph.nodes.get("Gap", {}).items()]
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    rows.sort(key=lambda r: (order.get(r[1], 9), r[0]))
    return ["Reference", "Severity", "Matter"], rows, "Open matters requiring a person"


INTENTS = [
    Intent("impact_of_column",
           "What breaks if I change a given column?",
           # Patterns do not require the entity to appear — `needs_entity`
           # already guards that, and a question the tool advertises must be
           # RECOGNISED even when asked generically, so the refusal explains
           # what is missing rather than claiming not to understand at all.
           [r"\bwhat breaks\b", r"\bimpact analysis\b",
            r"\b(break|impact|affect|depend)\w*\b.*\b(chang|modif|alter|drop|rename)\w*\b",
            r"\b(chang|modif|alter|drop|rename)\w*\b.*\b(break|impact|affect|depend)\w*\b",
            r"\bwhat (uses|reads|writes|touches)\b", r"\bwho (uses|reads|writes)\b",
            r"\b(break|impact|affect|depend)\w*\b.*\b\w+\.\w+\b"],
           """MATCH (c:Column {column_id: $column})
OPTIONAL MATCH (o:Object)-[r:READS_COLUMN|WRITES_COLUMN]->(c)
OPTIONAL MATCH (br:BusinessRule)-[:CONSTRAINS]->(c)
OPTIONAL MATCH (i:Index)-[:COVERS]->(c)
RETURN c, collect(DISTINCT o.title) AS units,
       collect(DISTINCT br.rule_id) AS rules, collect(DISTINCT i.index) AS indexes;""",
           _impact, needs_entity="Column"),

    Intent("rules_of",
           "Which business rules apply to a program unit, table or column?",
           [r"\b(rules?|requirements?|policy|policies)\b.*\b(for|in|on|of|apply|applies)\b",
            r"\bwhat rules\b", r"\brules (in|for|on)\b"],
           """MATCH (br:BusinessRule)-[:ENFORCED_IN]->(o:Object {object_id: $object})
RETURN br.rule_id, br.name, br.category, br.line ORDER BY br.rule_id;""",
           _rules_for),

    Intent("where_is_rule",
           "Where does a given rule live in the source?",
           [r"\bbr-\d{3}\b", r"\bwhere (is|does)\b.*\brule\b", r"\btrace\b.*\brule\b"],
           """MATCH (br:BusinessRule {rule_id: $rule})
OPTIONAL MATCH (br)-[:ENFORCED_IN]->(o:Object)
OPTIONAL MATCH (br)-[:IMPLEMENTED_AT]->(s:Statement)
RETURN br, o.title AS unit, s.type AS statement, s.line AS line;""",
           _where_rule, needs_entity="BusinessRule"),

    Intent("who_touches_table",
           "Which program units read or write a given table?",
           [r"\b(who|what|which)\b.*\b(touch|access|use|read|write|update)\w*\b.*\btable\b",
            r"\btouches\b", r"\bwrites to\b", r"\breads from\b"],
           """MATCH (o:Object)-[r:READS|WRITES]->(t:Table {table: $table})
RETURN o.title, type(r), r.operations ORDER BY o.title;""",
           _touching, needs_entity="Table"),

    Intent("interface_of",
           "What is the calling interface of a program unit?",
           [r"\b(interface|signature|parameters?|arguments?|inputs?|outputs?)\b",
            r"\bhow (do i |to )?call\b"],
           """MATCH (o:Object {object_id: $object})-[:HAS_PARAMETER]->(p:Parameter)
RETURN p.name, p.mode, p.data_type;""",
           _interface, needs_entity="Object"),

    Intent("needs_review",
           "Which rules still need a person to confirm them?",
           [r"\b(need|require)\w*\b.*\b(review|confirm|sme|validat)\w*\b",
            r"\bunconfirmed\b", r"\buncertain\b", r"\bnot (yet )?(confirmed|reviewed)\b"],
           "MATCH (br:BusinessRule {needs_review: true}) RETURN br.rule_id, br.name, br.category;",
           _unreviewed),

    Intent("unenforced",
           "Which rules are recorded but not enforced by the database?",
           [r"\b(unenforced|not enforced|disabled)\b", r"\bdisabled constraint\b"],
           "MATCH (br:BusinessRule {is_enforced: false}) RETURN br.rule_id, br.name, br.origin;",
           _unenforced),

    Intent("most_complex",
           "Which program units are most complex?",
           [r"\b(complex|complicated|risk|riskiest|hardest|difficult)\w*\b",
            r"\bcyclomatic\b", r"\bdecision paths?\b"],
           "MATCH (o:Object) RETURN o.title, o.cyclomatic, o.shape ORDER BY o.cyclomatic DESC;",
           _complex),

    Intent("hot_columns",
           "Which columns are used most widely?",
           # Both orders occur: "most widely used" and "used most widely".
           [r"\b(most|widely|heavily)\b.*\b(used|referenced|shared)\b",
            r"\b(used|referenced|shared)\b.*\b(most|widely|heavily)\b",
            r"\bhot columns?\b", r"\bshared (data|columns?)\b",
            r"\bcolumns?\b.*\b(most|widely|heavily)\b"],
           """MATCH (o:Object)-[:READS_COLUMN|WRITES_COLUMN]->(c:Column)
RETURN c.column_id, count(DISTINCT o) AS units ORDER BY units DESC;""",
           _hot_columns),

    Intent("orphan_tables",
           "Which tables are never touched by any program unit?",
           # Both word orders occur naturally: "which unused tables" and
           # "which tables are never used".
           [r"\b(orphan|unused|dead)\b.*\btables?\b",
            r"\btables?\b.*\b(orphan|unused|dead)\b",
            r"\b(never|not)\s+(used|touched|accessed|referenced)\b",
            r"\btables?\b.*\bnever\b", r"\bnever\b.*\btables?\b"],
           """MATCH (t:Table) WHERE NOT (:Object)-[:READS|WRITES]->(t)
RETURN t.table, t.column_count;""",
           _orphan_tables),

    Intent("open_gaps",
           "What open questions remain for the business?",
           [r"\b(gap|open question|outstanding|todo|unresolved|assumption)\w*\b",
            r"\bwhat.*(still )?(needs?|require)\w*\b.*\b(answer|decision|input)\b"],
           "MATCH (g:Gap) RETURN g.gap_id, g.severity, g.title ORDER BY g.severity;",
           _gaps),

    Intent("blind_spots",
           "What can this graph NOT see?",
           [r"\b(blind ?spot|limitation|caveat|incomplete)\w*\b",
            r"\b(can ?not|cannot|can't|does ?n[o']t|not)\s+(see|cover|include|know|capture)\b",
            r"\bwhat.*\b(miss|missing|excluded|left out)\w*\b",
            r"\bhow (complete|reliable|trustworthy)\b"],
           "MATCH (b:BlindSpot) RETURN b.detail;",
           _blind_spots),
]


def ask(graph, question: str) -> dict:
    """
    Answer a question, or say plainly that it cannot be answered.

    Returns a dict with either a result table or a `suggestions` list. It never
    returns a guessed answer: an unmatched question is a miss, not an
    approximation.
    """
    q = _norm(question)
    if not q:
        return {"ok": False, "reason": "empty question",
                "suggestions": [i.question for i in INTENTS]}

    label, key = resolve_entity(graph, question)

    matched = [i for i in INTENTS if i.matches(q)]
    # Prefer an intent whose required entity type is the one actually found —
    # "what rules apply to ACCOUNTS.BALANCE" and "what breaks if I change
    # ACCOUNTS.BALANCE" share vocabulary but want different answers.
    ranked = sorted(matched, key=lambda i: (i.needs_entity != label, INTENTS.index(i)))

    for intent in ranked:
        if intent.needs_entity and label != intent.needs_entity:
            continue
        result = intent.answer(graph, label, key)
        if result is None:
            continue
        header, rows, subject = result
        return {"ok": True, "intent": intent.name, "question": intent.question,
                "subject": subject, "header": header, "rows": rows,
                "cypher": intent.cypher, "entity": {"label": label, "key": key},
                "row_count": len(rows)}

    if matched and label is None:
        return {"ok": False,
                "reason": f"Understood the question type ({matched[0].question}) but could "
                          f"not identify which table, column, program unit or rule you mean. "
                          f"Name it exactly, e.g. ACCOUNTS.BALANCE or BR-014.",
                "suggestions": [i.question for i in INTENTS]}

    return {"ok": False,
            "reason": "No supported question matched. This interface answers only what it "
                      "can answer exactly — it does not guess.",
            "suggestions": [i.question for i in INTENTS]}
