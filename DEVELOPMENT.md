# LITMO — development summary

Status as of 2026-10-09. Installation, architecture overview and user manual are in
[`README.md`](README.md); the reasoning behind the design, with the alternatives
that were not chosen, is in [`DECISIONS.md`](DECISIONS.md).

A web tool for AI-assisted OWL ontology development, following the **MOMo**
(Modular Ontology Modeling) methodology of Shimizu, Hammar & Hitzler,
*Semantic Web* 14(3):459–489, 2023.

---

## 1. What the tool is

| | |
|---|---|
| Backend | `app.py` — FastAPI endpoints; the logic in `store.py`, `llm.py`, `project.py`, `definitions.py`, `ontology_io.py`, `corpus.py`, `momo_steps.py`, `vocabularies.py`, `editing.py`, `testing.py`, `upper.py`, `relations.py`, `generation.py`, `improvements.py` (see README); sessions persisted as JSON files in `data/sessions/` |
| Frontend | `index.html` — single page (markup and styles, ~1,300 lines), no build step; its JavaScript in `js/`, one file per step plus `core.js`, `project.js` and `main.js` (loads last, starts the page) |
| Edit operations | `ontology_edits.py` — applies the model's change operations to the ontology (no web dependencies) |
| Documentation | `documentation.py` — the documentation export (Markdown or HTML, one chapter per module), without model calls |
| Evaluation | `ontology_evaluation.py` — measures for the evaluation report (no web dependencies); see `EVALUATION.md` |
| Tests | `tests/` — `pytest` (install with `pip install -r requirements-dev.txt`); one file per topic, shared helpers in `tests/helpers.py`, setup in `tests/conftest.py` (DECISIONS 123) |
| Landing page | `landing.html` — served at `/`; the tool is at `/app` |
| Pattern catalog | `patterns_catalog.json` + `tools/build_pattern_catalog.py` |
| Measurement series | `tools/compare_runs.py` — compares projects (e.g. repeated generations of one configuration): per project the figures of generation report, evaluation and token use, with mean and spread; `python tools/compare_runs.py --title "VA measurement run 3"` |
| Start | `start.bat` (double-click; creates `.venv` if needed, installs the requirements into it, starts the server, or only opens the browser if a server is already running), or `.venv\Scripts\python.exe -m uvicorn app:app --port 8000` |

LLM providers: Anthropic, OpenAI, Gemini, RWTHgpt/KI:connect, and any
OpenAI-compatible endpoint.

## 2. The workflow

Panels implementing MOMo steps 1–7 and 10. MOMo step 8 (axioms) is covered by the
class restrictions: the modules write the key restrictions of their classes, and the
repair tool "Add class restrictions" adds them to an existing ontology (DECISIONS 125).
Step 9 (naming) is covered by the naming conventions the server applies and by the
OOPS! check; the former free-text endpoints for both steps were removed. In the patterns panel each suggested pattern can be deselected;
deselected notions are modeled from scratch.

**Pattern suggestions.** For each key notion, `candidate_patterns()` ranks the
catalog by word overlap with pattern names, classes, intent, domains and the
patterns' own competency questions (lightly normalized by pattern size, with a
boost when the notion name is part of the pattern name). The prompt shows the
full structure of the top 6 candidates per notion, so the model judges the fit
on classes and properties rather than names. It rates each choice `strong` or
`partial` and states what to keep and change; `null` is the expected answer when
nothing fits. Only strong fits are pre-selected; partial fits must be selected
deliberately. Keep/change notes are passed to generation for selected
patterns. A pattern the team picks manually is marked "chosen by you" and
loses the model's rating and rationale.

Panels are shown with the numbers below, but their element ids are stable
(`panel1`–`panel8`): panels added later keep their own id — `panel8`
(literature) is shown as step 3, `panel7` (project context) as step 4 — so
saved projects keep working.

**Literature (step 3, optional).** For ontologies built from a corpus of
papers, which no single prompt can hold (the 56 papers of the visual analytics
test corpus come to about 5.1 million characters). Each paper is condensed on
its own into a *paper card* (`CARD_SYS`): the concepts it defines with
definition, broader term, synonyms, page and a verbatim quote; relations;
taxonomies; candidate CQs; vocabularies. PDFs are read with `[page N]` markers
so the model can cite pages, and `clean_card()` checks every quote against the
full text (`quote_ok`), which exposes invented quotes. Extraction uses effort
`medium` and reads up to 200,000 characters per paper.

- The browser sends one request per paper, three in parallel
  (`/api/corpus/extract`). The server needs no background job, the API key
  stays in the browser, and a stopped run resumes with the papers still open.
- Uploads are deduplicated by content hash. The doc id derives from the hash,
  so re-uploading a file restores a missing full text.
- Full texts live in `data/sessions/<id>/corpus/*.txt`, not in the session
  JSON, which is rewritten after every changing request. The project export
  includes them (`corpus_texts`).

The same step also takes **existing ontologies** and **concept tables**. They
are turned into cards without an LLM, because their content is already
explicit:

- **Ontologies** (Turtle, RDF/XML, JSON-LD, N-Triples) go through
  `ontology_card()`:
  - classes with label (English preferred), definition (`skos:definition`,
    IAO definition, `rdfs:comment`), first named superclass, synonyms
    (`skos:altLabel`, other-language labels, oboInOwl) and URI
  - object properties with domain and range as relations
  - title, creator, date, namespace and `owl:imports`
  - OWL/XML is detected and rejected with a hint, because rdflib would read
    it as empty RDF/XML
- **Concept tables** (CSV, Excel): `read_table()` stores the table and
  `guess_columns()` proposes term, definition, broader term, synonyms and URI
  columns from the headers (English and German). The team confirms or changes
  the mapping per sheet (`/api/corpus/map-columns`) before the card is built.
- At most 1,500 concepts per source.
- `concept_key()` splits CamelCase, so `VisualEncoding` and
  "visual encodings" group together.
- In the inventory, each concept shows which existing ontology already covers
  it (with URI), and the list can be filtered to concepts that no existing
  ontology covers yet. A disagreement between an existing ontology and the
  literature counts as a conflict.

Step 2 remains for data the ontology must represent.

`build_inventory()` then merges the cards into a concept inventory:

- `group_concepts()` groups terms deterministically, by a normalized key
  (case, hyphens, article, plural) and by stated synonyms. Abbreviations do
  not link groups.
- One LLM call (`INVENTORY_SYS`) adds:
  - synonym merges
  - conflicting definitions, with the papers holding each position
  - themes as candidate modules
  - consolidated definitions
- `apply_consolidation()` accepts only known ids.
- If that call fails, the name-based grouping is still shown, with a warning.

The consolidation prompt shows all definitions of concepts with several
sources (only those can conflict). Single-source concepts get their label
only, so the list fits into one call (`INVENTORY_PROMPT_LIMIT`, 200,000
characters). Earlier the budget dropped all definitions for large corpora,
which made conflict detection impossible.

**The inventory in later steps.** `inventory_overview()` summarizes it:

- themes with their main concepts
- the central concepts (two or more sources) with definition and matching
  existing-ontology terms
- conflicts with the sources holding each position
- the existing ontologies
- CQ candidates

The overview goes to:

- **the context draft:** glossary, scope and reuse; the most consequential
  conflicts become questions, the rest are recorded with a proposed resolution
  marked `[confirm]`
- **CQ suggestions**
- **key-notion suggestions**

**Generation module by module** (`generate_modular()`). This is the only
generation path (DECISIONS 84); the former single call is gone.

1. A plan call (`PLAN_SYS`, built by `_plan_system()`) fixes the classes of
   each module with unique names and a one-sentence note, and lists notions to
   model as properties or individuals. With an inventory it assigns inventory
   concepts (size target from the number of themed or multi-source concepts,
   40–300); without one it plans from the use case, the competency questions,
   the key notions and the data preview (`DATA_PROMPT_LIMIT`). The modules are
   the key notions; without key notions the plan proposes 3–8 modules. The use
   case is the text of the generation step, including additional requirements.
2. One call per module (`MODULE_SYS`, four in parallel) receives only that
   module's material:
   - its concepts with all source definitions
   - existing-ontology URIs
   - relations from the sources
   - its design pattern
   - the CQs
   - the class names of the other modules, usable as domain/range
3. `merge_modules()` combines the results:
   - deduplicates names
   - adds planned classes a module left out (with the consolidated
     definition)
   - declares classes that are referenced but undefined as placeholders
   - keeps only source ids and URIs that exist in the inventory
   - turns source ids into citations

Classes carry `sources` (exported as `dct:source`) and `see_also` (exported
as `rdfs:seeAlso`). A failed module does not stop the run; its planned classes
are still added from the sources. The generation report shows plan size,
result, placeholders and failed modules.

**Changing the ontology afterwards (edit operations).** Feedback rounds, OOPS!
fixes, syntax fixes and the SHACL adjustment no longer ask the model for a new
ontology. For about 260 classes the full JSON is around 39,000 tokens, more
than the 32,000-token limit of OpenAI-compatible providers, and a rewrite could
drop things the request never touched. Instead the model returns operations,
and `ontology_edits.apply_edits()` applies them to a copy:

- **What the model sees:** a compact listing of the ontology
  (`ontology_listing()`, about 11,000 tokens for 260 classes), with modules named
  in the request in detail and the others by class name only (about 5,000
  tokens per call). It also gets the project context, the last eight change
  requests of the team, and files attached in step 9 (once).
- **What it returns:** `{"summary", "ops"}` with `add_`, `update_`, `rename_`
  and `remove_` operations for classes, properties, individuals, axioms and
  modules, plus `update_ontology` (typically a few hundred tokens).
- **What the server guarantees:**
  - unmentioned content (including `sources` and `see_also`) stays unchanged
  - renames update every reference
  - an operation that would break the ontology is rejected with a reason and
    changes nothing (unknown class, cycle, duplicate name, class as datatype
    range, datatype as class, a prefix the export cannot declare, still-used
    class removed without `replace_with`)
  - operations that refer to something not yet defined are retried after the
    others, so their order does not matter; a name renamed earlier in the
    same answer still resolves
  - rejected operations go back to the model once
  - sources and `see_also` URIs that occur neither in the ontology, the
    literature corpus nor the request are dropped and listed
    (`guard_provenance()`)
  - an integrity check before and after reports new problems
- **Syntax errors** are first fixed by renaming invalid identifiers
  (`sanitize_names()`), without a model call; the renames are shown next to
  the syntax badge. Only then does the model see the error, again as
  operations.
- The result of a feedback round shows the model's summary, the list of applied
  and rejected operations, and the OOPS! changes (`edit_report`, `fix_changes`).
- If no operation can be applied the request fails with HTTP 422 and the
  ontology stays unchanged. An empty operation list is a valid answer.
- The stored conversation history is gone (existing sessions drop it on load).

The reasoning and the alternatives are in `DECISIONS.md` (42–48, 50–51).

**Project context (step 4).** The model drafts a Markdown document (purpose,
scope, glossary, domain rules, data sources, reuse, decisions) from the use
case, the data preview and an optional existing context file, which is read in
full (up to 120,000 characters) rather than as a short preview. Inferred items
are marked `[confirm]`; the model asks at most 8 targeted questions with
answer options, and answers are merged into the document. A conventions form
sets namespace, prefix, label languages, license and OWL profile; namespace,
prefix and license are enforced on the generated file, not left to the model.
Conflicting definitions of the inventory are decided per concept in the same
step (`definitions.py`, DECISIONS 83): take a position, own definition, split
into 2-4 classes, or leave open; an optional model call recommends decisions in
packages of 15. Decisions are stored in `context.definition_decisions` keyed by
the concept, so they survive a rebuild of the inventory. `context_block()`
lists them as "Decided definitions"; the planning renames or adds the decided
classes, the module prompt gives them as DECIDED DEFINITION, and after
generation the server writes them into the descriptions and reports where the
model deviated. The evaluation checks them without a model; the repair action
"Apply decided definitions" uses edit operations.
`context_block()` passes document and conventions to every prompt (CQs,
notions, patterns, standards, generation, feedback, CQ tests); a feedback round
receives the context again only if it changed since the last generation.
Labels are stored per language (`labels: {"en": …, "de": …}`); older
ontologies with `label_de` still work.

| Panel | MOMo steps | Purpose |
|---|---|---|
| 1 · Configure LLM | — | Provider, model, API key |
| 2 · Use Case & Data Sources | 1 | Loose problem description; file upload |
| 3 · Literature (optional) | 1 | Paper cards per paper; concept inventory with conflicts and themes |
| 4 · Project Context | 1 | Purpose, scope, glossary, rules, data, reuse, decisions; conventions |
| 5 · Competency Questions | 2 | The questions the graph must answer |
| 6 · Key Notions & Modules | 3 | The few concepts that each anchor a module |
| 7 · Design decisions | 4 | Tabs: an ODPA pattern per notion, core relations (grouped by domain), vocabularies and prefixes |
| 8 · Generate | 5, 6, 7 | Generate and inspect |
| 9 · Evaluate and refine | 8, 9, 10 | Tabs: overview (scorecards, needs attention), questions, repair tools, edit (feedback, Turtle editor, SHACL), export |

Supported file input: CSV, Excel (.xlsx), PDF, TXT/Markdown, and existing
ontologies in Turtle, JSON-LD and RDF/XML. `analyze_file()` prepares each upload
by type instead of cutting it to a short preview:

- **Tables** (CSV, all Excel sheets): a column profile over all rows (up to
  200,000) — type, share of empty values, numeric range, value distribution or
  frequent values, and three example rows.
- **Documents** (PDF, text): the full text (up to 120,000 characters per file,
  300,000 in total) goes once into the project context draft (step 4); the
  data preview used by later prompts keeps a 4,000-character excerpt, so
  generation and feedback do not grow with the documents.
- **RDF**: declared classes and properties, instances per class, predicates in
  use, and the namespaces that actually occur.

## 3. Development history

### Initial version (May 2026)

Seven-step wizard, LLM-driven generation, table and graph views (vis.js),
Turtle export, OOPS! quality check, feedback iteration.

### SHACL, diff and provider support (May–Jul 2026)

SHACL constraint editor, diff between iterations, multi-file upload,
RWTHgpt/KI:connect and custom OpenAI-compatible providers.

### Correctness pass (Jul 2026, `a25f88d`)

- Turtle string escaping (`"`, `\`, newlines) — previously unescaped.
- Axiom serialization (`DisjointClasses`, `EquivalentClasses`, `SubClassOf`),
  which the generator produced but never wrote out.
- Prefix handling: no doubled `:` on prefixed names; prefixes used by the model
  but not selected as standards are detected and declared; custom prefixes can
  be added, resolved via prefix.cc.
- `rdf_graph_to_onto()` no longer mistakes properties and the ontology node for
  individuals.
- Blocking LLM calls moved out of `async def` handlers.
- UI translated to English; panels 5–7 merged into one.

### MOMo restructure (Oct 2026, `e73c2fb`, `854ab94`)

**Workflow.** Rebuilt around the methodology: use case → competency questions →
key notions → patterns → modules → axioms/naming. Modules and their pattern
provenance are exported as OPLa annotations, so the generated file records which
pattern each module came from.

**Key notions.** The team defines them; suggestions are optional and are
accepted one at a time rather than filling the list automatically. The prompt
asks for the few concepts that each anchor a module (3–6, never more than 7)
instead of every recurring noun, and the server drops suggestions duplicating
what the team already wrote.

**Design patterns.** Bound to the [ODPA patterns
repository](https://github.com/odpa/patterns-repository): the model may only
choose patterns that exist in the catalog, checked server-side, and the chosen
pattern's real classes and properties are passed to the generator as the module
template. Panel 5 has a searchable picker linking back to the repository.

**OOPS! integration.** Fixed; it had never reported a single pitfall, so every
ontology appeared clean. Details in §5.

**Landing page.** Describes the tool and the methodology, with the ten steps,
the mapping onto the panels, and the citation.

**Models.** Updated for Anthropic, OpenAI and Gemini. The token limit parameter
is now chosen per server: GPT-5.x and GPT-6 reject `max_tokens` and require
`max_completion_tokens`, while OpenAI-compatible servers expect `max_tokens`, so
the call falls back to the other if one is rejected.

## 4. Quality checks on generated ontologies

1. **Turtle syntax** — validated with rdflib; on failure invalid identifiers
   are renamed by the server, and only if that does not help the model is asked
   for correcting operations.
2. **OOPS!** — the generation prompt already lists the pitfalls of the
   [OOPS! catalogue](https://oops.linkeddata.es/catalogue.jsp) that the JSON
   format can express (`OOPS_GUIDANCE` in `editing.py`). The ontology is then sent
   to `oops.linkeddata.es`; pitfalls of importance *critical* and *important*
   are fixed automatically, *minor* ones are reported. A fix that produces
   invalid Turtle is discarded and the original kept, and the report is
   refreshed after a fix so it shows what remains. To avoid recurring
   pitfalls the Turtle export declares a license (P41), `owl:inverseOf` (P13),
   reused external classes such as `schema:Person` (P34), and the OPLa terms.

3. **Competency questions as tests** — after generation and after each
   feedback round, the LLM writes one SPARQL SELECT/ASK query per CQ plus a
   small set of sample individuals (`/api/momo/test-cqs`). rdflib then decides:
   a CQ counts as covered only if its query parses, uses only terms the
   ontology declares, and returns a result on the sample data that is not made
   up of schema terms alone. Sample triples using undeclared terms are dropped
   before the queries run. This replaces the former `cq_coverage` field, in
   which the LLM reported on its own work. Failed CQs can be copied into the
   feedback box with one click. CQ suggestions are capped at 10.

4. **Evaluation report** (`POST /api/evaluate`, `ontology_evaluation.py`) — on
   request in step 9. Competency questions full/partial/none (yours and up
   to 10 hold-out questions from the paper cards), coverage of the concept
   inventory (via the `inventory_concepts` link stored at generation, then
   name matching), traceability of classes, structural metrics, and HermiT
   (owlready2, Java) on the ontology and on the CQ sample data in a child
   process. Only deterministic measures; the model only writes SPARQL and
   sample data. The CQ tests store their results server-side
   (`cq_test_report`) with the used terms, so an evaluation in the same
   iteration usually costs one call. Literature and plan: `EVALUATION.md`;
   decisions 53–63.
   Coverage separates class / represented otherwise / deliberately not
   modeled / missing (`ConceptIndex`). A taxonomic recall measures the
   broader/narrower relations of the literature that the hierarchy realizes
   (`hierarchy_coverage`).
5. **Closing gaps** (`/api/gaps/start|step|finish`, `build_gap_batches`) — two
   actions from the evaluation box: add missing central concepts, and build
   the hierarchy from broader terms and taxonomies. Packages of edit
   operations sent one by one by the browser; declined items are stored in
   `gap_decisions` / `gap_hierarchy_decisions`; after every package HermiT
   compares the unsatisfiable classes with the state before the run, and the
   package is corrected once or rolled back (`_reasoner_guard`).

Automatic fixing now includes *important* pitfalls such as P10 (missing
disjointness) and P11 (missing domain/range). This was a deliberate decision
against MOMo's preference for scoped over global domain/range axioms: every
property now gets a global domain and range.

## 5. Bugs found and fixed

Worth recording, since several were silent.

| Bug | Effect |
|---|---|
| OOPS! parser matched lowercase tags | The response uses `oops:Pitfall`, `Code`, `Importance`, so nothing was ever parsed and every ontology was reported clean |
| OOPS! importance compared lowercase | Values arrive as `Critical`/`Important`; automatic fixing could never trigger |
| Unreadable OOPS! response returned `[]` | A failed check was indistinguishable from a clean result |
| Report built before the fix | Listed pitfalls that had just been fixed |
| Pattern links assumed branch `main` | The ODPA repository uses `master`; every catalog link 404'd |
| `switchTab()` used a hardcoded panel id | After renumbering, the view tabs in panel 6 stopped switching |
| Critical pitfalls sorted last | `impOrder[x] || 2` turned `0` into `2` |
| Details toggle used `querySelector` | Updated the diff view's button instead of its own |

## 6. Regenerating the pattern catalog

`patterns_catalog.json` is a snapshot of ODPA commit `bab4d82` (126 patterns
that have an OWL formalization). To update:

```bash
git clone --depth 1 https://github.com/odpa/patterns-repository odpa
python tools/build_pattern_catalog.py odpa
```

The builder reads the branch from the clone, pins OWL file links to the cloned
commit, reads OWL/XML files that rdflib cannot parse, and removes patterns that
appear under several folder names. Patterns without an OWL file (diagram only)
are excluded, as are the logical and reengineering patterns, which are not
module templates.

## 7. Known limitations

- **Single-user persistence.** Sessions are saved as JSON files in
  `data/sessions/` (override with `ODT_SESSION_DIR`) after every changing API
  request, and loaded on startup; the browser remembers the open project in
  `localStorage`. There is no locking between users or browser tabs working on
  the same project, and old session files are never cleaned up automatically.
  API keys are never stored. Projects can be exported and imported as
  `*.project.json` via the header buttons.
- **No API key in the code** since DECISIONS 139: RWTHgpt can use a key the server
  reads from `LITMO_RWTHGPT_KEY`; the earlier hard-coded key is revoked.
- **MOMo steps 5 and 7 are only partly supported.** They centre on iterative
  schema diagrams used to provoke domain experts; the tool renders a
  whole-ontology graph, which covers step 7 reasonably, but it does not replace
  the synchronous expert sessions of step 5.
- **Tests use a scripted fake model.** About 160 tests in `tests/` (run with `pytest`; the reasoner tests need
  Java) cover the edit operations, the generation, the actions, the CQ tests and the evaluation. What the prompts
  achieve with a real model is measured in the wine and VA runs (`examples/*/RUNS.md`), not in the tests.
- **`gpt-5.5-reasoning`** in the RWTHgpt list is a guess at the model id.

## 8. Reference

> Cogan Shimizu, Karl Hammar, and Pascal Hitzler. *Modular ontology modeling.*
> Semantic Web, 14(3):459–489, 2023.

Design patterns: [ODPA patterns
repository](https://github.com/odpa/patterns-repository). Quality checks:
[OOPS!](https://oops.linkeddata.es/).
