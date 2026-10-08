# The writing standard: ASD-STE100 Simplified Technical English

Use these rules for every README and for `docs/ste-style-guide.md` in each repository. Copy this file
into the repository as `docs/ste-style-guide.md` and add a **project vocabulary** section (Section 3)
with the technical names and technical verbs of that project.

## 1. The writing rules

### Words

1. Use one word for one meaning, and one meaning for one word. Do not use synonyms for variety.
2. Use a word only as one part of speech. For example, `test` is a noun or a verb, `check` is a verb.
3. Do not use phrasal verbs (`set up`, `carry out`, `find out`, `pick up`, `look up`, `come up with`).
   Use one verb: `prepare`, `do`, `find`, `get`, `make`.
4. Do not use an `-ing` form as a noun or an adjective (`the running job`, `after indexing`).
   Exception: a technical name, a file name, a command or a status value.
5. Do not use contractions (`don't`, `it's`, `can't`). Do not use slang or idioms
   (`out of the box`, `under the hood`, `at a glance`, `gotcha`, `bells and whistles`).
6. Do not use `and/or`. Write `A, B or both`.
7. Do not use `should`, `could`, `would` or `may` for instructions. Use `must` for a rule, the
   imperative for a step and `can` for a possibility.
8. Keep the articles `a`, `an` and `the` in sentences.
9. Do not make a noun cluster of more than three words. A technical name is one word.

### Sentences

1. A procedural sentence (an instruction) has a maximum of **20 words**.
2. A descriptive sentence has a maximum of **25 words**.
3. Write one instruction in one sentence.
4. Use the imperative for an instruction: `Run the tests.` Not `The tests should be run.`
5. Use the active voice. Use the passive voice only when the agent of the action is not important.
6. Use only the simple present, the simple past and the simple future.
7. Put a condition before the instruction: `If the index is stale, build it again.`
8. Do not use semicolons in sentences. Write two sentences.

### Paragraphs, notes and warnings

1. A paragraph has one topic and a maximum of **6 sentences**. Start with the topic sentence.
2. A warning or a caution starts with a clear command. Then it gives the reason.
3. A note gives information. It does not give an instruction.
4. Use a vertical list for a sequence or a set of conditions. Each item of a numbered procedure is one step.

### Tables, headings and diagrams

1. A table cell can be a short phrase. If a cell has a sentence, the sentence obeys the rules.
2. A heading is a noun phrase (`The cost model`) or an imperative (`Run the demo`).
   Do not start a heading with an `-ing` form.
3. A diagram label is a short phrase. Use the same terms as the text.

### What STE does not change

Code, commands, file names, paths, field names, environment variables, status values, enum values,
product names and URLs stay exactly as they are. They are technical names. Put them in backticks.

## 2. General words to replace

| Do not use | Use |
|---|---|
| utilize, leverage | use |
| in order to | to |
| set up | prepare, install, configure |
| carry out, perform | do |
| make sure, ensure | make sure (allowed), or `check that` |
| a lot of, lots of | many, much |
| e.g., i.e. | for example, that is |
| should (instruction) | must (rule) / imperative (step) |
| might, may (possibility) | can |
| very, really, just, simply, easily | (delete) |
| seamless, robust, powerful, blazing | (delete or give a measured fact) |

## 3. Project vocabulary

This section gives the technical names and the technical verbs of STATUTE. The README uses each term with only this meaning.

### 3.1 Technical names (nouns)

| Term | Meaning | Do not use |
|---|---|---|
| **agent** | One stage of the pipeline: an independent Python CLI program in `.claude/scripts/` | bot, LLM agent, worker |
| **pipeline** | The eight agents, run in sequence by a person | workflow engine, orchestrator |
| **artifact** | A JSON file that an agent writes into its run directory | output blob, result file, artefact |
| **run** | One timestamped output directory of one agent | job, execution, build |
| **pointer** | The `latest.json` file of an agent, which names the last good run | link, symlink, current file |
| **object** | One PL/SQL program unit: a procedure, a function, a package or a trigger | routine, module |
| **statement** | One PL/SQL statement with a `statement_id` | line, instruction |
| **file role** | The class that Agent 1 gives to a file, for example `schema_ddl` or `procedure` | file type, category |
| **enforcement state** | The STATUS and VALIDATED values of a constraint | constraint status, validity |
| **rule** | A business rule with an ID `BR-nnn`, a source line and a confidence | requirement (except in the BRD), policy, check |
| **obligation** | A rule stated as the condition that must be true | assertion, guard |
| **confidence** | `confirmed`, `high`, `medium` or `low`, given to each rule | certainty, score |
| **gap** | An open matter with an ID `GAP-nnn` | issue, TODO, defect |
| **BRD** | The Business Requirements Document `brd.md` | spec, report |
| **diagram** | One Mermaid file that Agent 3 or Agent 6 writes | chart, figure (except in the run output) |
| **node budget** | The maximum number of nodes in one diagram | limit, cap |
| **knowledge graph** | The property graph of Agent 8 | database, index |
| **intent** | One of the 12 question types of Agent 8 | query template, command |
| **blind spot** | A class of dependency that static analysis cannot see | limitation, hole |
| **annotation** | A business note in `brd_annotations.json`, keyed by a stable ID | comment, override |
| **ground truth** | The hand-annotated rules in `tests/fixtures/ground_truth/` | gold set, labels |
| **check** | One `check(condition, label)` assertion in a test suite | test case, assert |

### 3.2 Technical verbs

| Verb | Meaning |
|---|---|
| **classify** | Give a file its file role, or give a statement its type |
| **parse** | Change PL/SQL text into a parse tree with the ANTLR4 grammar |
| **extract** | Get statements, tables, columns or rules from a parse tree |
| **resolve** | Connect a call or a reference to a known object |
| **mine** | Find rules in one source kind, for example a cursor `WHERE` clause |
| **collapse** | Join contiguous straight-line nodes of a diagram into one node |
| **render** | Change an in-memory model into Mermaid or Cypher text |
| **declare** | State a fact in the output, for example an oversize diagram or a blind spot |
| **annotate** | Add a business note to a stable ID |
| **refuse** | Give no answer to a question with no matching intent, and exit with code 2 |
| **degrade** | Continue without an optional input and record its absence |
