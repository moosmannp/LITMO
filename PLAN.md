# Restructuring plan

Status: agreed on 2026-10-16 (answers to the open questions below). Phase 0 done (DECISIONS 82), phase 1 done
(DECISIONS 83), phase 2 built (DECISIONS 84; first wine run in
[`examples/wine/RUNS.md`](examples/wine/RUNS.md), follow-ups done in DECISIONS 86; run 2 recorded, its sample-data bug fixed in DECISIONS 87 and re-tested: 4 of 7 questions full; its small follow-ups in DECISIONS 88). Phase 3a built (DECISIONS 89); wine run 3 with it recorded, its follow-ups in DECISIONS 90; run 4 recorded, its CQ-test follow-up in DECISIONS 91; planned superclasses (first part of 3d) in DECISIONS 92; run 5 recorded, generation report stored (DECISIONS 93), its follow-ups in DECISIONS 94; run 6 recorded, its follow-ups in DECISIONS 95; run 7 recorded, its follow-ups in DECISIONS 96; run 8 recorded - results stable since run 6. Phase 3b built (DECISIONS 97), wine runs 9 and 10 with it recorded. Phase 3c built (DECISIONS 98); vocabulary prefixes kept (DECISIONS 99), large vocabularies (DECISIONS 100); wine runs 11 and 12 (3c) recorded, their follow-ups in DECISIONS 102; run 13 recorded. Phases 3d and 3e built (DECISIONS 103, 104); VA measurement runs 1, 2, 3a-3c and 4a-4c recorded in [`examples/va/RUNS.md`](examples/va/RUNS.md), the link follow-ups in DECISIONS 105 and 106, the CQ check in DECISIONS 107, robust model calls in DECISIONS 108, the correction of empty CQ queries in DECISIONS 109, the review of excluded taxonomy categories in DECISIONS 110, the hierarchy after the modules in DECISIONS 111, the core relations after the modules in DECISIONS 112, an unreachable OOPS! service in DECISIONS 113; the documentation export (phase 6) in DECISIONS 114; step 8 split (phase 4) in DECISIONS 115, the JavaScript in one file per step in DECISIONS 116. After runs 4a-4c: the hierarchy target "realized or declined" (DECISIONS 118), core relations to the upper layer and their feedback (DECISIONS 119), the code-review fixes: Turtle round trip (DECISIONS 120), concept key (DECISIONS 121) and the rest (DECISIONS 117, 122);
the tests with pytest (DECISIONS 123); "Evaluate 3x" (phase 6, DECISIONS 124); class restrictions (phase 5,
DECISIONS 125). Decisions taken while carrying it out go to
[`DECISIONS.md`](DECISIONS.md); this file describes the intended path.

## Why

After three weeks of changes the tool has grown into a pattern of **generate weakly, then repair expensively**. In the
visual analytics (VA) project the generation cost about 0.3 million input tokens; the repairs afterwards about 2.5
million:

| Improvement action | Input tokens (VA ontology) |
|---|---|
| Add missing central concepts | ~1.0 M |
| Build hierarchy from the literature | ~0.5 M |
| Group root classes under an upper layer | ~0.26 M |
| Consolidate properties | ~0.55 M |
| Align with vocabularies | ~0.2 M |

All of them repair what can be decided or supplied before generation: the upper layer is configured in step 4 but
applied only afterwards; the core relation vocabulary is a design decision, yet it is derived only after 530 narrow
properties exist; reuse offered in the prompt produced 2 links during generation against 15 from the align action
afterwards; the literature's broader terms and taxonomies, and the list of central concepts, are known to the
inventory but the planning step does not have to use them.

Step 8 does too much (generate, evaluate, improve, refine, export, plus prefixes that belong to the standards), the 58
conflicting definitions in the inventory have no place where the team decides them, there are two generation paths
(module by module with literature, a single call without) that every change has to be built for twice, and two server
functions (naming review, spanning axioms) are not reachable from the UI.

## Guiding idea

**Decide before generating; repair only as an exception.** What is repaired today after generation is decided
beforehand and carried out by the generation. The improvement actions stay, but their main purpose shifts: imported
ontologies ("Load existing ontology"), and a safety net when the evaluation shows that the generation missed
something. They are therefore not a step of their own that one always goes through.

## Target workflow

| # | Step | Change |
|---|---|---|
| 1 | Setup | unchanged |
| 2 | Use case & data | unchanged; "Load existing ontology" leads to step 9 |
| 3 | Literature & existing ontologies | ontologies uploaded as sources can also serve as vocabularies to reuse |
| 4 | Project context | **new: decide conflicting definitions**; conventions; upper layer |
| 5 | Competency questions | unchanged |
| 6 | Key notions & modules | unchanged |
| 7 | Design decisions | patterns, vocabularies **and core relations** approved here; prefixes move here |
| 8 | Generate | planning uses the decided definitions, upper layer, core relations, vocabulary mappings, the literature's hierarchy and every central concept; modules write key restrictions; **one** generation path |
| 9 | Evaluate & refine | evaluation, feedback, Turtle editor, SHACL, exports, **new: documentation**; the improvement actions as collapsed **repair tools** that open when the evaluation finds gaps or the ontology was imported |

## Phases

| Phase | Content | Effort | Depends on |
|---|---|---|---|
| 0 | Split the server code, no change in behavior | M | - |
| 1 | Decide conflicting definitions (step 4) | S-M | - |
| 2 | One generation path (modules also without literature) | M | 0 |
| 3 | Design decisions and literature structure before generation | L | 2 |
| 4 | Split step 8 into generate and evaluate & refine (with repair tools) | M | 3 |
| 5 | Class restrictions: during generation and as a repair tool | L | 4 |
| 6 | Documentation export and repeated evaluation runs | S + S | 4 |

S, M and L are roughly one, two and three working sessions of the kind of 2026-10-14 to 2026-10-16.

### Phase 0 - Split the server code

Almost every later phase changes the generation and the improvement actions, and most bugs of the last days arose at
transitions inside the 5,700-line `app.py`.

- Split `app.py` into `corpus.py` (literature, inventory), `generation.py` (planning, modules, merge, checks),
  `vocabularies.py` (standards, loading, alignment), `improvements.py` (the five actions, decisions) and
  `testing.py` (competency-question tests, evaluation); `app.py` keeps only the endpoints.
- No behavior changes: the existing tests (89 at the time of writing) are the safety net and must stay green.
- The UI is split in phase 4, where it is rebuilt anyway.

### Phase 1 - Decide conflicting definitions (step 4)

Goal: the team decides the conflicting definitions, not the model silently during generation.

- In the project context, a list of the inventory's conflicts, each with its positions and their sources (e.g.
  "Visualization": a process - 3 papers; a visual artifact - 4; post-hoc model explanation - ...). Per conflict:
  **take a position**, **write an own definition**, **split** into two concepts (e.g. `Visualization` as artifact and
  `VisualizationProcess`), or **leave open** (the model decides as before, marked as such).
- Optional: one model call recommends a decision per conflict with a reason; the team decides.
- Effect: decisions are stored in the context and reach every prompt as a section "Decided definitions"; planning
  creates two classes for a split; the module prompt takes the decided definition literally.
- Check without a model: after generation, decided concepts are compared with their decided definitions; deviations are
  reported.
- For existing ontologies: a small action "Apply decided definitions" that updates descriptions through edit
  operations.
- Success: every decided core concept carries its definition after generation; no silent deviation.

### Phase 2 - One generation path

Before phase 3, so that phase 3 is not built twice (as happened with generation-time reuse).

- Module-by-module generation also without literature: without an inventory, planning derives the classes from the
  use case, the competency questions and the key notions instead of from inventory concepts.
- The single-call path and its separate prompt and checks are removed.
- Success: a small project **without literature in an unrelated domain** - **wine**, with the W3C OWL Guide wine and
  food ontologies as reference (see [`EVALUATION.md`](EVALUATION.md) section 5; inputs in
  [`examples/wine/`](examples/wine/README.md)) - runs end to end. This project also
  serves as the domain-independence check for all later phases. The UC Davis wine-ontology was considered and is
  unusable (a draft that does not parse).

### Phase 3 - Design decisions before generation (step 7 "Design decisions")

**3a - Core relations before generation**
- The vocabulary is proposed from the inventory's relations (910 in the VA corpus), the competency questions and the
  key notions - not from finished properties. Without literature from the questions and notions only.
- The review panel of the property consolidation moves to step 7, with the same editing and checks.
- The module prompt receives the approved vocabulary with the rule: use the core relations; create a specific property
  only where a question needs it, and then below a core relation.
- After the merge, properties without a core relation and domain/range violations are reported (the rules of
  decision 70).

**3b - Upper layer in planning** (built, DECISIONS 97: the plan already places the top classes, the module prompt
handles the classes a module adds)
- The upper layer is created before the merge; the module prompt gives every class without a superclass in its module
  an upper class; empty upper classes are removed as today; the reasoner checks the result.

**3c - Reuse in planning** (built, DECISIONS 98, revised by 101: links decided per planned class after planning)
- For `use_terms` vocabularies, planning may map a concept directly to a vocabulary term (no own class; modules refer
  to the term).
- For `align` vocabularies, planning proposes a link per class from candidates found beforehand (as in the align
  action); the merge sets it as SubClassOf.
- The server lets only existing terms through. The "Additional prefixes" of step 8 move here.

**3d - Hierarchy from the literature in planning** (built, DECISIONS 103; measured in the VA run)
- Planning receives the inventory's broader terms and taxonomies for the concepts of each module and fixes the
  superclasses of the planned classes (the `parent` of a planned class exists since DECISIONS 92, so far without the
  literature's terms); relations that do not hold are left out with a reason (as in the hierarchy
  action, where the model declined loose "broader" relations).

**3e - Every central concept planned or excluded** (built, DECISIONS 104; measured in the VA run)
- Planning must assign every central concept (defined by two or more sources) to a class, a property or an individual,
  or exclude it with a reason; the server checks the plan for completeness before the modules are generated and lists
  the exclusions with their reasons (they become decisions that can be reconsidered).

**Success (measurement run):** a fresh generation of the VA ontology compared with today's result of generation plus
repairs:

| | Today after all repairs | Target |
|---|---|---|
| Top-level relations per class (DECISIONS 130; before: about 70 or fewer) | 0.35 (120 for 345 classes) | about 0.3 or fewer |
| Root classes | 7 | about 10 or fewer |
| Links to PROV-O | 15-17 | at least as many |
| Central concepts as a class (or decided otherwise) | 76.5 % as a class | at least as good, without "Add missing concepts" |
| Broader/narrower relations of the literature realized or declined with a reason (DECISIONS 118; before: realized) | 99 realized and 44 declined of 153 (93.5 %) | at least as good, without "Build hierarchy" |
| Competency questions / held-out | 10/10, 7-8/10 | at least as good |
| Input tokens | ~2.8 M | well below 1 M |

### Phase 4 - Split step 8 (built, DECISIONS 115, 116)

Two steps, not three: after phase 3, a separate "improve" step would suggest that every generated ontology goes through
it, which contradicts the guiding idea.

| New step | Content |
|---|---|
| 8 Generate | generation, generation report, ontology view |
| 9 Evaluate & refine | evaluation, feedback with attachments, Turtle editor (with a warning that it loses sources), SHACL, exports, documentation; **repair tools** (the improvement actions with their decisions and reconsider) as a collapsed section |

- The repair tools open by themselves when the evaluation finds a gap they address (missing central concepts, a flat
  hierarchy, many root classes, too many top-level relations, unaligned candidates) or when the ontology was imported;
  each tool says which measurement made it appear.
- "Load existing ontology" jumps to step 9 with the repair tools open.
- The JavaScript moves out of `index.html` into one file per step.
- The UI has no automated tests: a fixed walk-through of every step in the browser on a test copy.

### Phase 5 - Class restrictions: during generation and as a repair tool (built, DECISIONS 125; to be measured)

- Data model for restrictions (some, only, min, max), Turtle export and import, edit operations to add and remove
  them, reasoner check.
- **During generation:** each module writes the key restrictions of its classes (MOMo's module axioms), using the core
  relations; the server checks them like other references.
- **As a repair tool** for existing ontologies: proposals from the merges of the consolidation (the specific domain and
  range of every merged property gives `X SubClassOf r some Y`; recorded since DECISIONS 125, for the VA baseline
  reconstructed with `tools/lost_pairs.py`), the inventory's relations and the competency questions.
- The unused spanning-axioms function becomes the basis or is replaced; the naming review is wired into step 9 as a
  check or removed.
- Success: the class pairs that lost their specific property in the VA ontology (257 counted on an intermediate
  state; 264 between the states before and after the consolidation) are expressed again as restrictions where they
  are right; the reasoner stays consistent; the competency questions do not get worse.

### Phase 6 - Documentation and repeated measurement

- Documentation export (built, DECISIONS 114): per module its description, diagram, classes with definitions and sources, as HTML or Markdown
  - for the expert review and the paper.
- "Evaluate 3x" (built, DECISIONS 124): three independent test runs with mean and spread (single runs varied by 2 of
  10 questions).

## For every phase

- Existing projects keep working: without conflict decisions, core relations or an upper layer the generation behaves
  as today; the VA copies stay usable. Core relations and the upper layer are optional and switched on by default.
- Domain independence: every phase is also checked on the unrelated-domain project from phase 2.
- Per phase: a DECISIONS entry, new tests, a push.

## Decided questions (2026-10-16)

1. Phase 0: **yes**.
2. Core relations and upper layer: **optional, switched on by default** - small ontologies do not need a relation
   vocabulary.
3. "Split" for conflicting definitions: **yes**.
4. Test project domain: **wine**, compared with the W3C wine and food ontologies. Because that reference is very
   likely memorized by the models, the paper's generalization claim rests on a less known domain (SAREF4WATR, and
   OntoPFAS if time allows), each run preceded by a memorization probe - see [`EVALUATION.md`](EVALUATION.md)
   section 5.
