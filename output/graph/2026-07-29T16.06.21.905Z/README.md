# Knowledge Graph — import and query guide

Generated deterministically from the pipeline artifacts. No language model produced any node, relationship or query in this export.

## What is in it

| Node | Count |
|---|---|
| `BlindSpot` | 4 |
| `BusinessRule` | 41 |
| `Column` | 105 |
| `File` | 7 |
| `Gap` | 21 |
| `Index` | 1 |
| `Object` | 5 |
| `Parameter` | 20 |
| `RuleSet` | 4 |
| `Sequence` | 3 |
| `State` | 3 |
| `Statement` | 124 |
| `Table` | 15 |

| Relationship | Count |
|---|---|
| `AFFECTS` | 7 |
| `BELONGS_TO` | 41 |
| `BRANCHES_TO` | 40 |
| `CONSTRAINS_TABLE` | 1 |
| `CONTAINS` | 5 |
| `CONTAINS_STATEMENT` | 124 |
| `COVERS` | 2 |
| `DETERMINES` | 119 |
| `ENFORCED_IN` | 40 |
| `FOLLOWS` | 86 |
| `FOREIGN_KEY_ON` | 7 |
| `HAS_COLUMN` | 105 |
| `HAS_PARAMETER` | 20 |
| `HAS_STATE` | 3 |
| `IMPLEMENTED_AT` | 39 |
| `LOOPS_BACK_TO` | 1 |
| `READS` | 4 |
| `READS_COLUMN` | 36 |
| `REFERENCES` | 7 |
| `TOUCHES` | 7 |
| `WRITES` | 6 |
| `WRITES_COLUMN` | 69 |

## Loading it

**Option A — Neo4j Browser or cypher-shell.** Run `import.cypher` top to bottom. It uses `MERGE` throughout, so re-running is safe and idempotent.

```bash
cat import.cypher | cypher-shell -u neo4j -p <password>
```

**Option B — CSV.** `nodes/` and `rels/` hold one file per label and relationship type, for `LOAD CSV` or the admin importer.

**Option C — no Neo4j at all.** Ask questions directly against the artifacts:

```bash
python .claude/scripts/08_graph.py --ask "what breaks if I change ACCOUNTS.BALANCE"
python .claude/scripts/08_graph.py --list-questions
```

The local answer and the Neo4j answer come from the same model, so they cannot disagree.

## Questions this graph answers

### What breaks if I change a given column?

```cypher
MATCH (c:Column {column_id: $column})
OPTIONAL MATCH (o:Object)-[r:READS_COLUMN|WRITES_COLUMN]->(c)
OPTIONAL MATCH (br:BusinessRule)-[:CONSTRAINS]->(c)
OPTIONAL MATCH (i:Index)-[:COVERS]->(c)
RETURN c, collect(DISTINCT o.title) AS units,
       collect(DISTINCT br.rule_id) AS rules, collect(DISTINCT i.index) AS indexes;
```

### Which business rules apply to a program unit, table or column?

```cypher
MATCH (br:BusinessRule)-[:ENFORCED_IN]->(o:Object {object_id: $object})
RETURN br.rule_id, br.name, br.category, br.line ORDER BY br.rule_id;
```

### Where does a given rule live in the source?

```cypher
MATCH (br:BusinessRule {rule_id: $rule})
OPTIONAL MATCH (br)-[:ENFORCED_IN]->(o:Object)
OPTIONAL MATCH (br)-[:IMPLEMENTED_AT]->(s:Statement)
RETURN br, o.title AS unit, s.type AS statement, s.line AS line;
```

### Which program units read or write a given table?

```cypher
MATCH (o:Object)-[r:READS|WRITES]->(t:Table {table: $table})
RETURN o.title, type(r), r.operations ORDER BY o.title;
```

### What is the calling interface of a program unit?

```cypher
MATCH (o:Object {object_id: $object})-[:HAS_PARAMETER]->(p:Parameter)
RETURN p.name, p.mode, p.data_type;
```

### Which rules still need a person to confirm them?

```cypher
MATCH (br:BusinessRule {needs_review: true}) RETURN br.rule_id, br.name, br.category;
```

### Which rules are recorded but not enforced by the database?

```cypher
MATCH (br:BusinessRule {is_enforced: false}) RETURN br.rule_id, br.name, br.origin;
```

### Which program units are most complex?

```cypher
MATCH (o:Object) RETURN o.title, o.cyclomatic, o.shape ORDER BY o.cyclomatic DESC;
```

### Which columns are used most widely?

```cypher
MATCH (o:Object)-[:READS_COLUMN|WRITES_COLUMN]->(c:Column)
RETURN c.column_id, count(DISTINCT o) AS units ORDER BY units DESC;
```

### Which tables are never touched by any program unit?

```cypher
MATCH (t:Table) WHERE NOT (:Object)-[:READS|WRITES]->(t)
RETURN t.table, t.column_count;
```

### What open questions remain for the business?

```cypher
MATCH (g:Gap) RETURN g.gap_id, g.severity, g.title ORDER BY g.severity;
```

### What can this graph NOT see?

```cypher
MATCH (b:BlindSpot) RETURN b.detail;
```

## Concepts — derived views

Run these after loading to enrich the graph. They add labels and properties rather than new facts, so they are safe to re-run.

### Hot column

A column read or written by more than two program units — change last.

```cypher
MATCH (o:Object)-[:READS_COLUMN|WRITES_COLUMN]->(c:Column)
WITH c, count(DISTINCT o) AS units WHERE units > 2
SET c:HotColumn SET c.dependent_units = units RETURN c.column_id, units;
```

### Rule-bearing statement

A statement that implements at least one business rule.

```cypher
MATCH (br:BusinessRule)-[:IMPLEMENTED_AT]->(s:Statement)
SET s:RuleBearing RETURN s.statement_id, collect(br.rule_id);
```

### Write path

Statements on a control-flow path that ends in a write.

```cypher
MATCH p = (s:Statement)-[:FOLLOWS|BRANCHES_TO*1..10]->(w:Statement)
WHERE w.type IN ['UPDATE','INSERT','DELETE','MERGE']
RETURN DISTINCT s.statement_id, w.type, w.line;
```

## Constraints — these should return nothing

Each query below is a validation. A non-empty result is a defect in the pipeline or a genuine finding about the codebase.

### Every rule traces to source

A rule with no program unit and no table cannot be verified.

```cypher
MATCH (br:BusinessRule)
WHERE NOT (br)-[:ENFORCED_IN]->() AND NOT (br)-[:CONSTRAINS_TABLE]->()
RETURN br.rule_id;
```

### No orphan columns in rules

A rule constraining a column that does not exist indicates a join error.

```cypher
MATCH (br:BusinessRule)-[:CONSTRAINS]->(c:Column)
WHERE NOT (:Table)-[:HAS_COLUMN]->(c) RETURN br.rule_id, c.column_id;
```

### Unenforced constraints are visible

Any rule the database does not enforce must be flagged for review.

```cypher
MATCH (br:BusinessRule) WHERE br.is_enforced = false AND br.needs_review = false
RETURN br.rule_id, br.name;
```

## What this graph cannot see

No automated dependency analysis is complete. These limits are exported as `BlindSpot` nodes so they are queryable rather than assumed away:

```cypher
MATCH (b:BlindSpot) RETURN b.blind_spot, b.detail;
```

Treat the graph as a strong lower bound on dependencies, never an upper bound. Human validation remains necessary.

## Provenance

| Setting | Value |
|---|---|
| run_selector | `latest` |
