# Measurement runs of the visual analytics (VA) project

The VA project is the case study of the full workflow: 54 papers, a concept inventory of 1,395 concepts (264 central,
i.e. with two or more sources), 329 taxonomies, ten key notions, ten competency questions, PROV-O, SKOS, Data Cube and
DCAT loaded as vocabularies ("use terms directly"). The project data are not in the repository (`data/` is ignored);
the runs are recorded here. Targets: [PLAN.md](../../PLAN.md), phase 3, "Success (measurement run)".

## Run 1 - 2026-10-28, gpt-6-sol, commit ce0ad1c (phase 3 complete: DECISIONS 89-104)

**Setup.** The baseline is the project "Visualization Analytics Core Ontology" (`c7323784`) after generation and all
repair actions (iteration 6, evaluated 2026-10-16), the version PLAN.md's table describes. It was exported and imported
as "VA measurement run 1 (phase 3)" (`b151f9fe`); in the copy, the repairs' decisions (29 declined concepts, 89
hierarchy relations, 3 upper-layer, 40 link and 49 property decisions) and the core vocabulary derived from the old
ontology were removed, so the run does not inherit knowledge from the repairs. Then: core relations proposed from the
literature in step 7 and approved unchanged (41 relations), regenerated, CQ tests, evaluation with hold-out questions.
**No repair action was run.**

**Generation report:** 10 modules, 219 planned classes (218 with a planned superclass) -> 234 classes and 122
properties; **central concepts: 264 - 259 placed by the plan, 5 added by the completion call, 47 excluded with a
reason, none left open**; 12 broader/narrower relations of the literature declined by the plan; upper layer: Process,
Agent, InformationObject, Specification, Quality used, PhysicalObject removed, no top class outside; vocabulary links:
8 planned classes with candidates, 1 link (`UncertaintyAwareDataset -> dcat:Dataset`), 1 term used instead of a class
(`Dataset -> dcat:Dataset`), 6 declined; core relations: 17 module properties below them, 42 without one, no
violation.

| | Baseline (after all repairs) | Run 1 (no repair) | Target (PLAN.md) | |
|---|---|---|---|---|
| **Input tokens** | ~2.8 M for generation and repairs (3.66 M for the whole project) | **~271k** for the whole run, incl. CQ and hold-out tests | well below 1 M | met (-90 %) |
| Top-level relations | 112 | **82** | about 70 or fewer | close |
| Root classes | 7 | **5** (4 upper classes + 1) | about 10 or fewer | met |
| Links to reused vocabularies | 13 (PROV-O) | **6** (PROV-O, DCAT) | at least as many | **not met** |
| Central concepts as a class | 76.5 % (202) | **78.0 %** (206); represented 98.9 %, 43 deliberately excluded, 3 missing | at least as good, without "Add missing concepts" | met |
| Broader/narrower relations realized | 99 of 153 (64.7 %) | 90 of 139 (**64.7 %**) | at least as good, without "Build hierarchy" | same share |
| Competency questions full | 10 / 10; **8 / 10 (2 partial) with the current test** | 8 / 10 (2 partial) | at least as good | met |
| Hold-out questions full | 7 / 10; **5 / 10 (4 partial, 1 none) with the current test** | 3 / 10 (6 partial, 1 none) | at least as good | 2 fewer, see below |

Further figures:

| | Baseline | Run 1 |
|---|---|---|
| Classes / object / datatype properties / individuals / axioms | 345 / 301 / 14 / 5 / 45 | 234 / 108 / 14 / 9 / 16 |
| Relations / with a superproperty | 187 / 77 | 100 / 18 |
| Hierarchy depth (max / mean) | 6 / 3.29 | 7 / 3.06 |
| Sibling groups with disjointness | 16 of 54 | 5 of 34 |
| Properties without domain or range | 23 | 0 |
| Classes linked to the inventory / untraceable | 68.4 % / 0.9 % | **90.6 %** / 0.4 % |
| Reasoner | consistent | consistent, also with the sample data |
| What the repairs would still offer | - | Align: 20 classes with candidates; Build hierarchy: 49 relations; Add missing: 3 concepts; Group root classes: none |

Tokens per step: core-relation proposal ~7k; plan 38.6k / 13.5k; completion 1.3k / 0.6k; vocabulary links 0.9k / 0.8k;
ten modules 116k / 45k (8-14k input each); CQ tests 53.9k / 6.7k; hold-out tests 53.8k / 4.6k.

### Findings

1. **The cost target is met by far**: about 271k input tokens for proposal, generation, CQ and hold-out tests, against
   about 2.8 M for generation and repairs before. The plan prompt with broader terms, taxonomies and the central-concept
   rule costs 38.6k tokens; the completion and link calls together 2k.
2. **Coverage without repairs is at least as good as with them**: every central concept placed or excluded with a
   reason (none open), 78.0 % as classes against 76.5 %, 90.6 % of the classes linked to inventory concepts against
   68.4 %; the literature's hierarchy realized to the same share (64.7 %) without "Build hierarchy".
3. **Vocabulary links fall short**: 6 against 13. The link step found candidates for only 8 of 219 planned classes -
   it matches the planned class *name*, while the align action matched classes with their labels after generation.
   Modules created properties named like PROV-O terms (`used`, `generatedBy`, `wasDerivedFrom`) without linking them,
   since the link step only links classes. "Align" would still offer 20 classes.
4. **The CQ results are not comparable as they stand**: the baseline was tested on 2026-10-16, before the CQ test
   learned to report partial answers (DECISIONS 91, 95, 96), and it had reused and extended its sample data and
   queries over six iterations. The run's partial results come from the authors' "leaves out" statements, several of
   which ask more than the question does ("whether the returned agent is an Infovis system") - the over-reporting seen
   in the wine runs. A fair comparison needs the baseline tested again with the current test - done below.
5. **Leaner, with fewer axioms**: 234 instead of 345 classes, 108 instead of 301 object properties, no property
   without domain or range; but 16 instead of 45 axioms, and disjointness in 5 instead of 16 sibling groups.
6. **Core relations are broad**: 30 of 41 relate "any" to "any"; top-level relations 82, not yet the ~70 aimed at.

### Baseline retested with the current CQ test

A copy of the baseline export ("VA baseline CQ retest", `292f8fe0`) was evaluated from scratch on 2026-10-28 with
gpt-6-sol: new sample data and queries for the competency and hold-out questions, the CQ test of DECISIONS 91-96. The
ontology was not changed; all other figures are the baseline's.

| Question | Baseline, current test | Run 1 |
|---|---|---|
| Competency questions | 8 full, 2 partial | 8 full, 2 partial |
| - filtering, selection, zooming in coordinated views | partial (before/after contents of the views) | partial (resulting extent, level of detail) |
| - evaluating a design, validation | partial (adequacy criteria, outcome) | full |
| - mapping attributes to marks and channels | full | partial (the sample data had no position mapping) |
| Hold-out questions | 5 full, 4 partial, 1 none | 3 full, 6 partial, 1 none |
| - techniques supporting an analytic goal | full | partial: "whether depicting the task's target data makes the representation suitable" |
| - intents an Infovis system supports | full | partial: "whether the returned agent is an Infovis system and whether it offers, rather than merely uses, the technique" |
| - information-seeking problems per data type; inherent uncertainty; tracking items; composition operators | partial | partial |
| - components of a Vega-Lite unit specification | none | none |

**Result.** With the same test the baseline drops from 10 to 8 full competency questions and from 7 to 5 full hold-out
questions: most of the earlier gap was the measurement. The competency questions are now even (8 / 2 / 0 each, with
one different question partial on each side - one of them caused by the sample data, not the ontology). On the
hold-out questions run 1 is two behind, and both differences are "leaves out" statements about judgements (whether a
representation is *suitable*, whether a system *is* an Infovis system) of the kind DECISIONS 91 meant to exclude; the
baseline's run of the test happened not to make them. Every test is a single run of a non-deterministic model, so a
difference of one or two questions is within the noise; the hold-out question no version answers (Vega-Lite) needs a
concept neither ontology has.

### Follow-ups (proposed)

- Link step: match planned classes also by their concepts' labels and variants and the planned note; link
  properties too (subPropertyOf a vocabulary property, e.g. PROV-O's `used`, `wasGeneratedBy`). **Done: DECISIONS
  105, measured in run 2.**
- CQ test: "leaves out" statements that only doubt a judgement or a type the query already asks for still count as
  partial (both hold-out differences above); the rule of DECISIONS 91 needs a sharper wording or a check.
- Disjointness: ask the modules for DisjointClasses among sibling classes that cannot share instances (OOPS! P10).

## Run 2 - 2026-10-28, gpt-6-sol, commit 0700ee0 (vocabulary links, DECISIONS 105)

**Setup.** As run 1: a new copy of the same baseline export ("VA measurement run 2 (vocabulary links)", `cdf6597c`),
the repairs' decisions removed. Run 1's approved core relations (41) were copied into it unchanged, so that the
generation differs from run 1 only by the code. Regenerated, CQ tests, evaluation with hold-out questions; no repair.
**One manual fix:** two module properties had the range "(any)", copied from the listing of the core relations, and
the Turtle export wrote `:(any)` - the CQ test could not parse it (the generation's syntax-fix call, 9.9k tokens,
did not repair it either). The two ranges were cleared in the project file, which is what the merge does since the
fix in DECISIONS 105 ("Fixed with 105").

**Links to vocabularies.** After planning: candidates for 20 planned classes (run 1: 8) - the labels and variants of
the concepts find more - but no link: 18 declined, mostly with reasons about DCAT's narrower meaning ("a collection of
data items need not meet DCAT's publication, curation, and access requirements"), and 2 classes replaced by a term:
`TaskTarget -> prov:Entity`, `AnnotationActivity -> prov:Activity`. After the modules: 25 terms with candidates, 7
linked (`Agent`, `EntityWithProvenance`, `ProvenanceActivity` as subclasses of `prov:Agent`, `prov:Entity`,
`prov:Activity`; `attributedTo`, `generatedBy`, `used`, `wasDerivedFrom` as subproperties of their PROV-O
counterparts), 18 declined, none refused. The modules linked 3 more classes to `prov:Person` themselves.

| | Baseline | Run 1 | Run 2 |
|---|---|---|---|
| Input tokens of the run (generation, CQ, hold-out) | ~2.8 M (with repairs) | 264k (+7k core proposal) | 264k (incl. 2.6k for the new link call and 9.9k syntax fix) |
| **Links to reused vocabularies** | 13 (PROV-O) | 6 (PROV-O, DCAT) | **11** (PROV-O): 6 class links, 4 subproperties, 1 domain `prov:Activity` |
| Top-level relations | 112 | 82 | 87 |
| Root classes | 7 | 5 | 4 |
| Central concepts as a class | 76.5 % | 78.0 % (43 decided, 3 missing) | **68.9 %** (65 decided, 2 missing); represented 99.2 % |
| Broader/narrower relations realized | 64.7 % (99/153) | 64.7 % (90/139) | **51.3 %** (61/119) |
| Competency questions full / partial / none | 8 / 2 / 0 (current test) | 8 / 2 / 0 | 6 / 4 / 0 |
| Hold-out questions full / partial / none | 5 / 4 / 1 (current test) | 3 / 6 / 1 | 2 / 6 / 2 |
| Classes / object / datatype properties / axioms | 345 / 301 / 14 / 45 | 234 / 108 / 14 / 16 | 212 / 108 / 10 / 20 |
| Planned classes / central concepts excluded by the plan | - | 219 / 47 | 194 / 70 |
| Reasoner | consistent | consistent | consistent, also with the sample data |
| What "Align" would still offer | - | 20 | 0 |

### Findings

1. **The link step works**: 11 links instead of 6, at 2.6k tokens; together with the baseline's 13 - which needed the
   align repair - within reach. Nothing is left for "Align": everything with a candidate is linked or declined with a
   reason. The model declines DCAT for general data and dataset classes, as the careful rules of DECISIONS 102 ask.
2. **"Use the term" replaced classes by broader terms**: `TaskTarget` and `AnnotationActivity` disappeared in favour of
   `prov:Entity` and `prov:Activity`. The rule for `use` (DECISIONS 101) says the term replaces the class, but not
   that it must mean the same; a broader term should give a subclass.
3. **The run differs from run 1 far more than the code change explains.** The plan prompt was the same (the link step
   runs after it), yet the plan has 194 instead of 219 classes and excluded 70 instead of 47 central concepts -
   among them domain concepts from the literature's uncertainty taxonomy ("Usage Uncertainty", "Ignorance",
   "Incomplete Knowledge", "Nonrepresentative Sampling") and "overplotting", "sensitivity analysis methods". Central
   concepts as classes fall from 78.0 % to 68.9 %, the realized hierarchy from 64.7 % to 51.3 %, and the competency
   questions from 8 to 6 full. A single generation is not a measurement: the model's variance between two runs of the
   same plan prompt is larger than most effects measured so far.
4. **An invalid range broke the export**: the generation's own syntax check sent the Turtle to the model, which could
   not fix `:(any)` - now prevented in the merge (DECISIONS 105).

### Follow-ups (proposed)

- `use` only for a term with the same meaning; a broader term gives `subclass` (prompt rule in the link call).
  **Done: DECISIONS 106** (with a server check: same name or label).
- Measure with three generations per configuration (PLAN.md phase 6 plans "evaluate 3x"; it is needed now): mean and
  spread of central coverage, hierarchy, links and CQ results, so that a change is judged against the variance.
- Exclusions of central concepts: the plan rule allows "out of scope or specific to one paper"; concepts that belong
  to a taxonomy of the literature, or that the competency questions name, should not be excluded without a stronger
  reason - or the exclusions should be reviewed by the completion call.

## Runs 3a-3c - 2026-10-28, gpt-6-sol, commit b84cbab (three generations of one configuration)

**Setup.** Three new copies of the baseline export with the same reset as runs 1 and 2 and run 1's 41 approved core
relations, generated one after the other with the same code (DECISIONS 105, 106); then CQ tests and evaluation with
hold-out questions; no repair. Compared with `tools/compare_runs.py`. Two incidents:
- **3b** first stopped at the provider's token rate limit (429) right after 3a's tests; generated again a few minutes
  later. One module wrote a restriction as a class name (`SubClassOf(UsefulAI, "isPartOf some HumanCenteredAI")`),
  which broke the Turtle export; the generation's syntax-fix call tried twice (23.7k tokens) and could not repair it.
  The merge now leaves such axioms out (DECISIONS 105, "Fixed with 105"); in 3b the axiom was removed by hand in the
  project file before the CQ tests.
- **3c** ran with that merge fix (not yet committed then); it left out one axiom of the same kind
  (`SubClassOf(CompoundTask, "hasConstituentTask some Task")`), and no syntax fix was needed.
- In 3a the CQ tests ran twice (the input tokens include about 55k for the second run).

| | 3a | 3b | 3c | mean | sd |
|---|---|---|---|---|---|
| Planned classes | 224 | 198 | 231 | 217.7 | 17.4 |
| Central concepts excluded (plan + completion) | 42 | 68 | 24 | 44.7 | 22.1 |
| Vocabulary links after planning / after the modules | 2 / 6 | 1 / 6 | 0 / 7 | 1.0 / 6.3 | |
| Classes / object properties / axioms | 239 / 108 / 23 | 222 / 115 / 29 | 261 / 120 / 24 | 240.7 / 114.3 / 25.3 | |
| Root classes | 4 | 4 | 4 | 4.0 | 0.0 |
| Top-level relations | 85 | 91 | 99 | 91.7 | 7.0 |
| Links to reused vocabularies | 9 | 9 | 8 | 8.7 | 0.6 |
| Sibling groups with disjointness | 9 | 8 | 9 | 8.7 | 0.6 |
| Central concepts as a class (%) | 80.7 | 68.9 | 80.7 | 76.8 | 6.8 |
| Broader/narrower relations realized (%) | 48.0 | 55.3 | 64.5 | 55.9 | 8.3 |
| Classes linked to the inventory (%) | 92.5 | 90.1 | 85.4 | 89.3 | 3.6 |
| Competency questions full / partial / none | 8 / 2 / 0 | 4 / 6 / 0 | 2 / 8 / 0 | 4.7 full | 3.1 |
| Hold-out questions full / partial / none | 4 / 6 / 0 | 4 / 6 / 0 | 5 / 4 / 1 | 4.3 full | 0.6 |
| Input tokens of the run (k) | 325 (CQ twice) | 284 (syntax fix 24k) | 277 | 295 | 26 |

**Against the targets (PLAN.md phase 3), as mean over 3a-3c; in brackets the mean over all five runs where the code
changes since run 1 cannot matter (they act after the plan):**

| | Baseline | Target | Mean (sd) | |
|---|---|---|---|---|
| Input tokens | ~2.8 M | well below 1 M | ~280k per run | met |
| Top-level relations | 112 | about 70 | 91.7 (7.0) | not met |
| Root classes | 7 | about 10 or fewer | 4.0 | met |
| Links to reused vocabularies | 13 | at least as many | 8.7 (0.6) | not met (run 1: 6) |
| Central concepts as a class | 76.5 % | at least as good | 76.8 % (6.8) [75.4 %] | met on average, with a large spread |
| Broader/narrower relations realized | 64.7 % | at least as good | 55.9 % (8.3) [56.8 %] | not met |
| Competency questions full (current test) | 8 | at least as good | 4.7 (3.1); **8.3 (0.6) with the check** (below) | not met at first - see finding 3; met with the check |
| Hold-out questions full (current test) | 5 | at least as good | 4.3 (0.6) | close |

### Findings

1. **Generations of one configuration differ a lot.** The same plan prompt gives 198-231 planned classes and excludes
   24-68 central concepts; central concepts as classes vary between 68.9 % and 80.7 %, the realized hierarchy between
   48 % and 65 %. Single runs (runs 1 and 2) cannot show the effect of a change smaller than this spread.
2. **Stable:** root classes (4), links to vocabularies (8-9, the link calls decide alike), represented central
   concepts (98-100 %), consistency; token use ~280k per run.
3. **The CQ results vary mostly through the test, not the ontology**: full answers 8, 4 and 2. Most partial and failed
   results in 3b and 3c judge something the question does not ask: "whether the insight is sufficiently justified to
   be accepted as knowledge", "how much they help an audience understand", "not that the recorded interaction caused
   the insight", "the kinds are available from the asserted types rather than as separate answer values". The rule of
   DECISIONS 91 (a "leaves out" is missing information, not a judgement) does not hold the model.
4. **Two structural shortfalls remain**: the literature's hierarchy (56 % against 65 %) and the top-level relations
   (92 against 112 before and ~70 aimed at - more than run 1's 82; 30 of the 41 core relations relate "any" to "any",
   and modules add relations below few of them).
5. **Restrictions appear unasked**: two of three generations wrote "r some C" as a class - the modules want to say
   things the format cannot express yet (PLAN.md phase 5).

### Follow-ups (proposed)

- CQ test: make the "leaves out" rule hold - e.g. a second check per partial result ("is this information the
  question asks for, or a judgement about it?"), or the level decided by a separate short call with only question,
  answer rows and the stated gap; then test 3a-3c again to separate test noise from ontology differences.
- Exclusions of central concepts (24-68 per run): stricter rule as proposed after run 2.
- Hierarchy: look at which broader/narrower relations the plans realize in one run and not in another.

### 3a-3c tested again with the check of partial answers (DECISIONS 107)

The three ontologies unchanged; "Evaluate from scratch" (new sample data and queries for the competency and hold-out
questions), now with the separate check of partial answers. 3b twice: in the first evaluation its hold-out test failed
(the model's JSON answer was broken, `JSONDecodeError`), in the second the check of its hold-out answers hit the
provider's quota (429) - as designed they stayed partial and the report says so; so 3b's hold-out result is unchecked.

| | 3a | 3b | 3c | mean | sd |
|---|---|---|---|---|---|
| Competency questions full - first test (run 3) | 8 | 4 | 2 | 4.7 | 3.1 |
| **Competency questions full - with the check** | **8** | **8 / 9** (two tests) | **8** | **8.3** | 0.6 |
| ... of them made full by the check | 1 | 0 / 1 | 3 | | |
| ... full without the check (fresh test alone) | 7 | 8 / 8 | 5 | | |
| Hold-out questions full - first test | 4 | 4 | 5 | 4.3 | 0.6 |
| Hold-out questions full - with the check | 3 | (failed / 1 unchecked) | 5 (2 by the check) | | |
| Input tokens of the check calls | 2.0k | 0.8k / 0.8k | 2.5k | | |

**Findings.**
1. **The competency-question result is stable now: 8, 8-9 and 8 full** where the first test gave 8, 4 and 2 - on the
   same ontologies. All three reach the baseline's 8 (current test); the target "at least as good" is met.
2. **Two sources of test noise.** The fresh test alone already gives 7, 8 and 5 instead of 8, 4 and 2: queries and
   sample data written anew differ from test to test. The check removes the second source, gaps that judge instead
   of asking (made full: "the question asks how the concepts relate, not whether an insight was accepted or
   sufficiently justified", "... not whether they actually improved audience understanding"). The gaps it keeps name
   what the question asks ("the question asks about axes as well as legends, but the rows give only a legend").
3. **The hold-out questions remain hard to measure**: 3 and 5 full in 3a and 3c; in 3b one failure through broken
   JSON and one unchecked result through the quota. Several unchecked 3b gaps are judgements again ("whether users
   can actually perform each intended task"). Queries whose chain of joins finds no sample data still fail now and
   then ("No result on the sample data").
4. The baseline's hold-out figure (5) was measured without the check; a fair comparison needs it retested too.

### Follow-ups (proposed)

- Robustness of model calls: wait and retry when the provider's rate limit is reached; one retry when the answer is
  no valid JSON - both cost a run's test or a whole generation today.
- A query without a result on its own sample data: one correction round (query and sample data back to the model).
- Exclusions of central concepts, hierarchy and top-level relations: as above.

All four built: DECISIONS 108 (rate limits, broken JSON), 109 (correction of empty queries), 110 (exclusions of
taxonomy categories and concepts of the questions reviewed), 111 (hierarchy after the modules), 112 (core relations
after the modules); also 113 (an unreachable OOPS! service fails fast).

## The hierarchy measure with declined relations (DECISIONS 111), recomputed for the runs so far

Since DECISIONS 111 the evaluation also counts broader/narrower relations that were declined with a reason (by the
plan, by "Build hierarchy" or after the modules). Recomputed from the project files of the earlier runs (no model
call; the realized counts match their stored evaluations):

| | Relations | Realized | Declined with a reason | Neither | Realized | Realized or declined |
|---|---|---|---|---|---|---|
| Baseline (after repairs) | 153 | 99 | 44 | 9 | 64.7 % | **93.5 %** |
| Run 1 | 139 | 90 | 5 | 44 | 64.7 % | 68.3 % |
| Run 2 | 119 | 61 | 8 | 49 | 51.3 % | 58.0 % |
| 3a | 148 | 71 | 10 | 67 | 48.0 % | 54.7 % |
| 3b | 123 | 68 | 10 | 45 | 55.3 % | 63.4 % |
| 3c | 155 | 100 | 8 | 46 | 64.5 % | 69.7 % |

The baseline's "Build hierarchy" repair decided almost every relation: it realized 99 and declined 44, leaving 9
open. The runs without repair leave 44-67 relations neither realized nor decided. This - not the realized share,
which the baseline reaches in runs 1 and 3c - is the gap the hierarchy step after the modules (DECISIONS 111) is
meant to close; runs 4a-4c measure it.

Before runs 4a-4c the changes since 3a-3c (DECISIONS 108-113) were reviewed; four defects were fixed (notes under
DECISIONS 108-111): two broader terms of one class in one call overwrote each other, an upper-layer class could be
put below a domain class, one correction with invalid Turtle discarded the sample data of all others, and errors
that only mention a "limit" (or a quota for the day) were waited for in vain.

## Runs 4a-4c - 2026-10-29, gpt-6-sol, commit 166e028 (steps 1-4 and the code-review fixes)

**Setup.** As 3a-3c: three new copies of the baseline export with the same reset and run 1's 41 approved core
relations, generated one after the other, then CQ tests and evaluation with hold-out questions; no repair. The code
differs from 3a-3c by DECISIONS 107-113 (check of partial answers, robust model calls, correction of empty queries,
review of excluded taxonomy categories, hierarchy and core relations after the modules, OOPS! fail-fast) and the
review fixes (DECISIONS 117). No errors: no failed step, no invalid axiom, no placeholder class; the JSON repair and the
correction of an empty query were each used once (4c), and the corrected question then passed.

| | 3a-3c (mean, sd) | **4a** | **4b** | **4c** | **4a-4c (mean, sd)** |
|---|---|---|---|---|---|
| Planned classes | 217.7 (17.4) | 252 | 238 | 251 | 247.0 (7.8) |
| Central concepts excluded | 44.7 (22.1) | 11 | 9 | 16 | **12.0 (3.6)** |
| ... exclusions reviewed / kept (DECISIONS 110) | - | 7 / 1 | 7 / 0 | 15 / 0 | |
| Classes / object properties / axioms | 240.7 / 114.3 / 25.3 | 278 / 139 / 26 | 268 / 132 / 23 | 283 / 145 / 40 | 276.3 / 138.7 / 29.7 |
| Root classes | 4.0 | 4 | 4 | 4 | 4.0 |
| Top-level relations | 91.7 (7.0) | 75 | 91 | 100 | 88.7 (12.7) |
| ... relations placed below a core relation after the modules / kept | - | 28 / 36 | 16 / 51 | 15 / 61 | |
| Links to reused vocabularies | 8.7 (0.6) | 8 | 5 | 14 | 9.0 (4.6) |
| Sibling groups with disjointness | 8.7 | 13 | 6 | 10 | 9.7 |
| Central concepts as a class (%) | 76.8 (6.8) | 85.2 | 80.7 | 81.8 | **82.6 (2.3)** |
| Broader/narrower relations realized (%) | 55.9 (8.3) | 56.0 | 54.7 | 60.1 | 56.9 (2.8) |
| ... realized or declined with a reason (%) | 54.7-69.7 | 98.8 | 98.0 | 98.7 | **98.5** |
| ... after the modules: offered / added / declined / refused | - | 66 / 0 / 66 / 0 | 61 / 1 / 58 / 2 | 52 / 1 / 49 / 2 | |
| Competency questions full (with the check) | 8.3 (0.6) | 9 | 9 | 10 | **9.3 (0.6)** |
| Hold-out questions full | 4.0 (two runs) | 6 | 4 | 3 | 4.3 (1.5) |
| Input tokens of the run (k) | ~280-295 | 314 | 308 | 318 | 313 (5) |

The new steps cost about 20k input tokens per run: core relations after the modules 11-13k, hierarchy after the
modules 4-5k, the checks and corrections of the tests 1-3k.

**Against the targets (PLAN.md phase 3; baseline after all repairs):**

| | Baseline | Target | 4a-4c | |
|---|---|---|---|---|
| Input tokens | ~2.8 M | well below 1 M | ~313k per run | met |
| Root classes | 7 | about 10 or fewer | 4 | met |
| Central concepts as a class | 76.5 % | at least as good | 82.6 % (sd 2.3) | **met, now clearly** |
| Competency questions full (current test) | 8 | at least as good | 9.3 | **met** |
| Broader/narrower relations | 64.7 % realized, 93.5 % realized or declined | at least as good | 56.9 % realized, 98.5 % realized or declined | decided: met; realized: not met |
| Hold-out questions full | 5 (without the check) | at least as good | 4.3 | close |
| Links to reused vocabularies | 13 | at least as many | 9.0 (4c: 14) | not met |
| Top-level relations | 112 | about 70 | 88.7 (4a: 75) | not met |

### Findings

1. **The measurement is stable now.** The spread fell for every figure the steps aimed at: planned classes sd 17.4 ->
   7.8, excluded central concepts 22.1 -> 3.6, central concepts as classes 6.8 -> 2.3 points, realized hierarchy
   8.3 -> 2.8 points, competency questions 0.6. Differences between configurations of a few points can now be seen.
2. **Reviewing the exclusions works (DECISIONS 110):** 12 instead of 45 central concepts excluded, and central
   concepts as classes 82.6 % against 76.8 % - higher than the baseline after "Add missing central concepts". The plan
   itself excluded far fewer (the rule), and the review placed what remained in all but one case.
3. **The hierarchy step decides, but adds almost nothing (DECISIONS 111):** of 52-66 relations it added 0-1 and
   declined the rest, with sound reasons - the sources' "broader" terms are mostly single-source and loose ("Goal is a
   kind of Axis", "Interaction is a kind of Visualization"). So the literature's hierarchy is now decided almost
   completely (98.5 % against 93.5 % for the baseline after "Build hierarchy"), while the realized share stays at
   57 %. The baseline's higher realized share probably includes such loose relations adopted by the repair; the
   "realized" target compares against that and should give way to "realized or declined".
4. **Core relations after the modules (DECISIONS 112) help little:** they placed 15-28 relations, but the modules
   produce more relations than before (139 against 114 object properties), so top-level relations stay at 89 on
   average, with a wide spread (75-100). The model keeps 36-61 relations as "their own kind of connection".
5. **Links stay below the baseline** (9 against 13), varying with the plan (4c linked five role classes to prov:Role).
6. **The disjointness check of the hierarchy step works:** it refused two superclasses that would have put an
   interaction under both Process and InformationObject (4b and 4c).

### Follow-ups (proposed)

- **Done (DECISIONS 118):** the baseline's realized relations compared with 4a-4c - of its 99, 56-63 do not exist in
  a run at all (a class is missing or named differently); of those that do, the runs realize 30-36, decline 5-8 and
  leave 0-2 open; each run realizes 49-64 that the baseline does not have. Seven of the ten declined ones follow one
  modelling choice: the plan separates an executed interaction (brushing, panning, semantic zooming as something a user
  does) from the interaction technique that specifies it, and does not put the one below the other - a point for the
  expert review. The target is now "realized or declined".
- (was:) Replace the hierarchy target "realized at least as good" by "realized or declined at least as good" (PLAN.md), and
  look at the baseline's realized relations that the runs decline - if they are loose, the baseline's 64.7 % is not a
  goal.
- **Done (DECISIONS 119):** the relations kept without a core relation are mostly kept for good reasons; across 4a-4c
  they point to information objects (92), qualities (25), agents (13) and processes (10), and no core relation has
  Quality as range. 20 of the 41 core relations were below no relation in any run. The step-7 proposal now asks for
  general relations to upper-layer classes ("has quality") and keeps narrow ones in the modules; step 7 shows after
  a generation which core relations are unused and where the rest point.
- (was:) Top-level relations: find out why the model keeps relations like `hasTaskInput` as their own kind - the candidates
  are many (about 30 per relation) and most core relations relate "any" to "any"; fewer, more specific core relations
  or a closer look at the reasons kept.
- The remaining review findings (DECISIONS 117), first the Turtle editor (T1) and the plural handling of the concept key
  (T11, then all runs evaluated again).
  **Done:** the Turtle editor (DECISIONS 120) and the concept key (DECISIONS 121) - recomputed for the baseline and
  runs 1-4c, the new key changes none of the coverage and hierarchy figures, so no run had to be evaluated again.


## Runs 5a-5c - 2026-10-30/31, gpt-6-sol, commits d1d1719 / 2e25b08 (phase 5 and 6: class restrictions, Evaluate 3x)

**Setup.** As 4a-4c: three new copies of the baseline export with the same reset, generated one after the other,
then **Evaluate 3x** (three independent tests of the competency and hold-out questions, DECISIONS 124); no repair.
Unlike 4a-4c, the copies did not use run 1's 41 core relations but a vocabulary of 39 proposed with the new step-7
prompt (DECISIONS 119: general relations to the upper layer, "has quality") - 17 relations new, 19 gone, most domains
and ranges now upper-layer classes. (Corrected on 2026-10-31; the first version of this record said "the 41 approved
core relations".) New since 4a-4c: the core-relation proposal for the upper layer (DECISIONS 119), the
review fixes (120-122) and class restrictions written by the modules and checked by the reasoner (125). 5a was
generated on d1d1719 (12:32 CET), 5b on 2e25b08 (15:08 CET), 5c on 2026-10-31 (21:27 CET, same generation code). No
failed step. The daily limit of 100 sol calls set the pace: one run with Evaluate 3x takes 32-34 calls.

| | 4a-4c (mean, sd) | **5a** | **5b** | **5c** | **5a-5c (mean, sd)** |
|---|---|---|---|---|---|
| Planned classes | 247.0 (7.8) | 227 | 242 | 238 | 235.7 (7.8) |
| Central concepts excluded | 12.0 (3.6) | 26 | 21 | 17 | **21.3 (4.5)** |
| ... exclusions reviewed / kept | | 25 / 0 | 19 / 0 | 14 / 0 | |
| Classes / object properties / axioms | 276.3 / 138.7 / 29.7 | 264 / 115 / 28 | 272 / 126 / 29 | 269 / 130 / 27 | 268.3 / 123.7 / 28.0 |
| Root classes | 4.0 | 5 | 4 | 8 | 5.7 (2.1) |
| Top-level relations | 88.7 (12.7) | 67 | 75 | 89 | **77.0 (11.1)** |
| Links to reused vocabularies | 9.0 (4.6) | 9 | 10 | 15 | 11.3 (3.2) |
| Sibling groups with disjointness | 9.7 | 11 | 13 | 10 | 11.3 |
| Class restrictions (on classes) | - | 84 (72) | 84 (70) | 60 (55) | 76.0 |
| ... refused by the checks / removed by the reasoner | - | 1 / not checked | 1 / 0 | 2 / 0 | |
| Reasoner consistent | - | no (see below) | yes | yes | |
| Central concepts as a class (%) | 82.6 (2.3) | 75.0 | 80.3 | 79.5 | **78.3 (2.9)** |
| Central concepts represented (%) | | 98.5 | 98.9 | 98.1 | 98.5 (0.4) |
| Broader/narrower relations realized (%) | 56.9 (2.8) | 53.9 | 52.7 | 59.4 | 55.3 (3.6) |
| ... realized or declined with a reason (%) | 98.5 | 100.0 | 99.4 | 99.4 | **99.6** |
| Competency questions full, first test | 9.3 (0.6) | 9 | 8 | 9 | 8.7 (0.6) |
| Competency questions full, Evaluate 3x | - | 9, 6, 6 | 8, 8, 9 | 9, 8, 10 | **8.1** (runs 7.0, 8.3, 9.0) |
| ... spread within a run (sd) | - | 1.7 | 0.6 | 1.0 | 1.1 |
| Hold-out questions full, first test | 4.3 (1.5) | 5 | 4 | 4 | 4.3 (0.6) |
| Hold-out questions full, Evaluate 3x | - | 5, 4, 4 | 4, 4, 3 | 4, 5, 4 | **4.1** (sd within a run 0.6) |
| Model calls: generation / Evaluate 3x | | 18 / 15 | 18 / 16 | 17 / 15 | 17.7 / 15.3 |
| Input tokens: generation / Evaluate 3x (k) | ~313 incl. one test | 176 / 430 | 180 / 448 | 179 / 436 | 178 / 438 |

**5a and the reasoner.** HermiT refused 5a: the module wrote `hasPart min 2`, and `hasPart` is transitive - OWL 2 DL
allows no numbers on such a property. The reasoner check after the merge was therefore skipped ("not checked"). Fixed
in 2e25b08 (`restriction_issues`: no numbers on non-simple properties); without the three affected restrictions 5a is
consistent (checked offline). In 5c the new check refused exactly such a restriction (`CompoundTask SubClassOf hasPart
min 2 Task`); 5b and 5c are consistent, also with sample data, and the reasoner removed nothing.

### Findings

1. **One test is not enough, three are:** within one ontology the competency questions varied by up to three of ten
   between identical tests (5a: 9, 6, 6). Over the three generations the mean of the repeated tests is 8.1, the first
   test alone said 8.7. A difference between two configurations of one or two questions is within this noise; the
   hold-out questions vary less (sd 0.6).
2. **Class restrictions work from the first generation on:** 60-84 per run on 55-72 classes, almost all
   existential ("some"), each checked against domain and range; the checks refused one or two per run for good reasons
   (a class not below the property's domain, a number on a transitive property), and the reasoner had nothing to
   remove.
3. **Fewer top-level relations (DECISIONS 119):** 77 against 89, with 5a at 67 - near the target of about 70 for the
   first time - but the spread stays wide (67-89).
4. **More central concepts excluded:** 21 against 12. The plan assigned fewer (229-237 against 245-248), the completion
   placed more, and the review kept none of the exclusions. The excluded concepts are mostly about research itself -
   in all three runs `methodology`, `taxonomy`, `pitfall`, `problem-driven research`, `technique-driven research`,
   `reflection`, `VIS4ML` - but also `interaction primitive`, `information location` and `task by data type taxonomy`,
   which could be classes. Central concepts as classes fell to 78.3 % (82.6 %), represented or decided stays at 98.5 %.
5. **The hierarchy is decided almost completely** (99.6 % realized or declined), the realized share unchanged (55 %).
6. **Cost:** a generation now takes about 180k input tokens in 17-18 calls; Evaluate 3x costs about 2.5 times as much
   (430-450k, 15-16 calls).

### Class restrictions on a copy of the baseline (2026-10-30, eefcf277)

The repair tool "Add class restrictions" (DECISIONS 125) on a copy of the baseline after all repairs, to measure how
many of the class pairs the property consolidation gave up come back (`tools/lost_pairs.py`). Evaluate (single test),
add class restrictions (11 calls, 30 candidates each), evaluate again: 23 calls.

| | |
|---|---|
| Candidates (class pairs) | 301 |
| Restrictions written / declined with a reason | 55 (54 "some", 1 "min 2") on 46 classes / 245; 2 still offered |
| Lost class pairs of the consolidation (264) with a restriction again | 43 (16.3 %); 215 declined |
| Reasoner | consistent, also with sample data |
| Competency / hold-out questions full (after) | 10 / 7 (one test) |

The declined pairs mostly fail the "every A" test ("An attribute can exist without a recorded observation"), so the
tool restores a lost connection only where it holds for every member of the class. The question results before the
repair were overwritten by the second evaluation (follow-up below).

### Follow-ups (proposed)

- **Keep the previous evaluation** next to the latest, so a repair can be compared before and after (DECISIONS,
  open points).
- **Done (analysis below):** why the plan excludes more central concepts than in 4a-4c.
- **Done (DECISIONS 132):** root classes 8 in 5c - four of them were `User` and three roles below `prov:Person`,
  which the ontology puts below `Agent`; the count did not follow that link. Recomputed: 5c 4, run 1 4 (was 5), the
  rest unchanged; 5a keeps 5 (`CollaboratorRole` only below `dcat:Role`).

## Top-level relations per class (DECISIONS 130), recomputed for all runs

The absolute target "about 70" became "about 0.3 top-level relations per class or fewer". Recomputed from the stored
ontologies (no model calls):

| | Classes | Top-level relations | Per class | Target 0.3 |
|---|---|---|---|---|
| Raw generations before any consolidation | 229-326 | 268-272 | 0.83-1.17 | not met |
| Baseline after all repairs | 345 | 112 | 0.32 | close |
| Run 1 / 2 | 234 / 212 | 82 / 87 | 0.35 / 0.41 | not met |
| Runs 3a / 3b / 3c | 239 / 222 / 261 | 85 / 91 / 99 | 0.36 / 0.41 / 0.38 | not met |
| Runs 4a / 4b / 4c | 278 / 268 / 283 | 75 / 91 / 100 | 0.27 / 0.34 / 0.35 | 4a met |
| Runs 5a / 5b / 5c | 264 / 272 / 269 | 67 / 75 / 89 | 0.25 / 0.28 / 0.33 | 5a, 5b met |
| Wine runs 13 / 14 | 13 / 18 | 6 / 6 | 0.46 / 0.33 | below the minimum of 10 relations: not assessed |

The verdicts for VA hardly change (with "about 70", 5a met and 4a, 5b were close); the wine ontology is no longer
measured against a number meant for an ontology fifteen times its size.

## Why 5a-5c excluded more central concepts than 4a-4c (analysis, 2026-10-31, no model calls)

**The planning call got the same input in all six runs.** Inventory (1,395 concepts), use case, competency
questions, key notions, project context, upper layer and data are identical (compared by hash), the model was
gpt-6-sol via RWTHgpt in all runs, and the planning prompt did not change between 166e028 and 2e25b08. The core
vocabulary differs (see the setup of 5a-5c), but the planning prompt does not contain it. The new concept key
(DECISIONS 121) changes which concepts the review protects by one (611 -> 612, `aesthetics`).

**What differs is the model's answer.** Counted per run:

| | 4a | 4b | 4c | 5a | 5b | 5c |
|---|---|---|---|---|---|---|
| Central concepts the plan excluded | 16 | 16 | 31 | 51 | 40 | 31 |
| ... of them reviewed (taxonomy category or named in a question) | 7 | 7 | 15 | 25 | 19 | 14 |
| ... still excluded after the review | 1 | 0 | 0 | 0 | 0 | 0 |
| Not reviewed, so excluded as the plan said | 9 | 9 | 16 | 26 | 21 | 17 |
| Placed by the completion | 15 | 19 | 17 | 35 | 27 | 32 |

4c and 5c are equal (31); the means differ (21 against 41), but with three runs each the difference is not
significant (Welch's t about 2.6, 4 degrees of freedom, p about 0.06). **The likeliest explanation is the spread of
the planning call itself, not a change in the code**: for the same input it excluded between 16 and 51 central
concepts.

**Why the spread reaches the result:** the review (DECISIONS 110) only re-examines exclusions of protected concepts
(taxonomy categories, concepts named in a question) - and it placed all of them in 5a-5c. Every other exclusion
stands as the plan wrote it, after one call and without a second look. Two further observations:

- Most exclusions are about research itself, and leaving them out is defensible (`methodology`, `taxonomy`,
  `pitfall`, `problem-driven research`). 5a-5c added design-study frameworks and their terms (`nine stage framework`,
  `nested model`, `consideration space`, `proposal space`, `information location`, `stability of the task`) - "specific
  to one paper's method" is an allowed reason, but these have two or more sources each.
- Two of 5a's exclusions are bookkeeping errors: `objective uncertainty` and `uncertainty quantification` are
  "accounted for as ObjectiveUncertainty / UncertaintyQuantification in the Uncertainty module" - the plan put a
  modelled concept on the excluded list.

**Fixes (built, DECISIONS 131):**
1. Every exclusion of the plan goes through the completion step, not only the protected ones, so that each is
   decided twice and one noisy call no longer decides the count. The completion already batches 60 concepts per
   call; with 16-51 exclusions this adds no call in most runs.
2. An exclusion whose reason names a planned class ("accounted for as X") counts as an assignment to that class.

The next VA runs measure the effect (expected: a smaller spread of excluded central concepts). Note for comparisons:
`by_plan` no longer includes the plan's exclusions.

## Hold-out questions chosen by central concepts (DECISIONS 133) - a new series from here

The hold-out set of 5a-5c (and of all earlier runs) followed the order of the inventory: 415 of 416 literature
questions have one source, so "most sources first" decided nothing. It contained questions about single-paper details
(the Vega-Lite unit specification, multi-view composition operators) that failed in nearly every run. From DECISIONS
133 on, the set is chosen by the central concepts the questions name, spread over the themes, and stored with the
project. The 5c copy does not record which literature questions the suggestions of step 5 saw, so the first 40 of
the inventory stay excluded "to be safe", as before. (Corrected on 2026-10-31: the lists first written here were
computed without that exclusion and were not the sets tested; below are the sets as stored and tested.)

**Bridge (2026-10-31, 22:42 CET, commit 27d7468):** 5c evaluated once more with Evaluate 3x. In the review the
team removed two questions - one about specifying brushing, cross-filtering and the like, and one about which task
clarity and information location make a domain problem suitable for a design study - and the next candidates took
their place. The set tested, sharing no question with the old one:

1. Which actions can an analyst perform on data, models, visualizations and their mappings?
2. What provenance must be recorded to follow uncertainty through system operations and human insights?
3. Which data variable is mapped to each aesthetic, and which scale controls that mapping?
4. Which operations help an analyst focus on subsets, expose patterns, or derive new values?
5. Is a given uncertainty statistical, an error, or a range?
6. Which selected history views can be exported for a report or presentation?
7. Which elementary graphical-perception tasks does a graph require for decoding its quantitative values?
8. Which observations did users report as insights while analyzing a data set with a visualization tool?
9. Is a reported case study based on a domain expert, close collaboration, visualization researchers, or a
   hypothetical usage scenario?
10. How can user interactions be represented as sequences, grammars, models, or graphs?

14 model calls.

| 5c | Old hold-out set | New hold-out set |
|---|---|---|
| Hold-out questions full (3 runs) | 4, 5, 4 (mean 4.3) | 2, 2, 2 (mean 2.0) |
| ... partly (first test) | 4 | 8 |
| ... not answered (first test) | 2 | 0 |
| Answered at least partly (first test) | 8 of 10 | **10 of 10** |
| Questions that vary between runs | | 2 of 10 |
| Competency questions full (3 runs) | 9, 8, 10 | 9, 9, 10 |
| Reasoner | consistent | consistent |

**Reading the bridge.** No question of the new set goes unanswered: the ontology has the concepts of every question,
which is what selecting by central concepts aimed at, and the results are stable (sd 0). But only two are answered in
full. The check of partial answers (DECISIONS 107) gives its reasons, and they are about the wording, not missing
classes: six of the ten questions ask what *can* or *must* be the case or for *every* member of a set - "which
actions *can* an analyst perform" ("the query identifies recorded actions, not every action an analyst could
potentially perform"), "what provenance *must* be recorded" ("cannot establish that these records are required"),
"which views *can* be exported", "which tasks does a graph *require*", "which operations *help*", "how *can*
interactions be represented". An ontology with sample data shows what is recorded; a question about possibility,
necessity or completeness can only be answered in part. The old set failed for the opposite reason - concepts the
ontology did not have.

So "full" on the new set measures the wording of the questions as much as the ontology. Until that is settled, the
hold-out results are reported with both figures: in full, and at least partly.

**Decided (DECISIONS 134):** questions with modal, normative or exhaustive wording come after the plain ones. The
bridge is repeated on 5c with the new set (the two removed questions stay removed). It keeps four questions of the
first bridge set (3, 5, 8, 9) and adds six:

- How are findings, insights, hypotheses, and knowledge related during trust building?
- Which goals, outputs, questions, and methods are associated with each evaluation scenario?
- How are captured interactions and provenance encoded?
- Which guides are generated for position and non-position scales?
- Does a data assessment examine input quality, output performance, or fairness?
- Which characteristics of data and representation affect visualization complexity?

**Second bridge, first attempt (2026-10-31, 22:56 CET, commit dcf1be1): no hold-out result.** A query of the
hold-out test used `EXISTS { ... }` inside a SELECT expression; rdflib parses it but fails when the rows are read
("What do I do with this CompValue?"). That happened outside the error handling of the single test, so the whole
hold-out test was given up - all three runs (DECISIONS 135). The competency questions were tested (8, 8, 9 of 10).
7 model calls. To be repeated with the fix.

**Second bridge (2026-10-31, 23:07 CET, commit c0c7ffc):** Evaluate 3x on 5c with the same set, 12 model calls.

| 5c | Old set | First bridge (DECISIONS 133) | **Second bridge (DECISIONS 134)** |
|---|---|---|---|
| Hold-out questions full (3 runs) | 4, 5, 4 (mean 4.3) | 2, 2, 2 (2.0) | **4, 4, 3 (3.7)** |
| ... partly | 4 (first test) | 8, 8, 8 | 6, 5, 7 |
| ... not answered | 2 (first test) | 0, 0, 0 | 0, 1, 0 |
| Answered at least partly | 8 (first test) | 10, 10, 10 | **10, 9, 10** |
| Competency questions full (3 runs) | 9, 8, 10 | 9, 9, 10 | 9, 9, 8 |
| Reasoner | consistent | consistent | consistent |

Three questions are answered in full in every run (how findings, insights, hypotheses and knowledge relate; which
data variable is mapped to each aesthetic and which scale controls it; how captured interactions and provenance are
encoded), a fourth in two of three (the guides of position and non-position scales). The rest are partly answered,
now for reasons that concern the ontology or a causal claim rather than the wording of possibility: the evaluation
scenarios have no research questions ("the questions associated with each scenario"), whether a case study was
reported or the collaboration close is not recorded, and "which characteristics *affect* visualization complexity"
asks for an effect the data do not show. Twice in run 3 a query put `EXISTS` inside a SELECT expression again; with
DECISIONS 135 these questions counted as partly answered instead of ending the test.

**The new hold-out series starts here:** for 5c, 3.7 of 10 in full and 9.7 of 10 at least partly. Round 6 is
compared with these figures; earlier hold-out figures (4.1 for 5a-5c) belong to the old set.

## Runs 6a-6c - 2026-10-31/11-02, gpt-6-sol, commit 75b68b4 (DECISIONS 131-135)

**Setup.** Three copies of 5c as it was before its generation (`drafts/round6`, built from the tool's own export):
same inventory, use case, questions, context, vocabularies and the 39-relation core vocabulary as 5a-5c; all decisions
of the generation removed; the hold-out set of the second 5c bridge (with the team's two removals) stored with each
copy. Generate, then Evaluate 3x; no repair. 6a was generated on 2026-10-31 (23:27 CET), 6b and 6c on 2026-11-02
(13:09, 13:26 CET), all on the same code. New since 5a-5c: every exclusion of the plan gets a second look (131), root
classes through vocabularies (132), hold-out questions by central concepts and without modal wording (133, 134), a
failing query fails only its question (135). No failed step; 32-36 calls per run (17-18 for the generation).

| | 5a-5c (mean, sd) | **6a** | **6b** | **6c** | **6a-6c (mean, sd)** |
|---|---|---|---|---|---|
| Central concepts the plan excluded | 40.7 (10.0) | 40 | 65 | 32 | 45.7 (17.2) |
| ... given a second look | 19.3 (protected only) | 40 | 65 | 31 | |
| ... "accounted for as" a planned class | - | 0 | 0 | 1 | |
| **Central concepts excluded in the end** | 21.3 (4.5) | 5 | 8 | 3 | **5.3 (2.5)** |
| Central concepts placed by the completion | 31.3 (4.0) | 31 | 68 | 38 | 45.7 (19.7) |
| Central concepts as a class | 206.7 (7.6) / 78.3 % | 193 | 207 | 207 | 202.3 (8.1) / 76.6 % |
| ... as a property or an individual | 33.3 | 64 | 43 | 46 | 51.0 |
| ... planned but not built by a module | 4.0 | 3 | 7 | 8 | 6.0 |
| Central concepts represented or decided (%) | 98.5 | 98.9 | 97.3 | 97.0 | 97.7 |
| Classes / object properties / axioms | 268.3 / 123.7 / 28.0 | 243 / 114 / 18 | 262 / 128 / 32 | 262 / 118 / 33 | 255.7 / 120.0 / 27.7 |
| Root classes (DECISIONS 132) | 4.3 | 4 | 4 | 4 | 4.0 |
| Top-level relations per class | 0.29 | 0.33 | 0.30 | 0.29 | 0.31 |
| Links to reused vocabularies | 11.3 | 6 | 8 | 10 | 8.0 |
| Broader/narrower relations realized (%) | 55.3 | 42.7 | 59.9 | 59.4 | 54.0 |
| Competency questions full, Evaluate 3x | 7.0 / 8.3 / 9.0 (8.1) | 6.7 | 8.7 | 6.7 | **7.4** |
| Hold-out (new set) full, Evaluate 3x | 5c bridge: 3.7 | 2.3 | 3.7 | 2.7 | **2.9** |
| Hold-out (new set) answered at least partly, per run | 5c bridge: 10, 9, 10 | 9, 10, 10 | 10, 10, 10 | 10, 10, 9 | 9.8 |
| Reasoner | consistent (5b, 5c) | consistent | consistent | consistent | |

### Findings

1. **The second look works (DECISIONS 131):** the plan still excluded between 32 and 65 central concepts for the
   same input, but only 3-8 stayed excluded (5a-5c: 17-26). What stays out is research vocabulary in all three runs
   (`methodology`, `taxonomy`, `design study paper`, `science of interaction`, `technique-driven research`).
2. **The placed concepts became properties and individuals more than classes.** Concepts as a class did not rise
   (202 against 207, within the spread); concepts as a property or individual did (51 against 33): `Algorithm
   Performance` and `Evaluating Collaborative Data Analysis` as individuals of an evaluation scenario, `VIS4ML` as an
   individual, `pitfall` as a property `hasPitfall`, `expressiveness` as `hasTaxonomyExpressiveness`; others, such as
   `interaction primitive` and `reflection`, as classes. Whether research-side concepts belong in the ontology at all
   is the use case's question - one for the expert review. Slightly more planned concepts were not built by their
   module (3-8 against 3-5: `Mapping`, `stability of the task`, `chunking`, `feedback loop`).
3. **The competency questions are within the spread, and the same three are weak as in round 5:** the difference
   between filtering, selection, navigation and semantic zooming (0-1 of 3 in all six runs); tracing an insight back
   through interactions and states; how a person takes part in building an AI model. The reasons are the same in both
   rounds - the ontology records that something happened, not the before-and-after content or the causal and
   temporal order. 7.4 against 8.1 is within the run-to-run spread (5a alone: 7.0); 6a is the weaker run overall
   (243 classes, 42.7 % of the hierarchy realized, 18 axioms).
4. **Hold-out, new set:** 2.3-3.7 in full (5c bridge 3.7), and every question at least partly answered in nearly every
   run - the set is no longer dominated by single-paper details, and the failures are partial answers, not missing
   concepts.
5. **Structure is stable:** 4 root classes in every run, 0.29-0.33 top-level relations per class, reasoner consistent.

### Follow-ups (proposed)

- **Interaction effects and provenance order:** the three weak competency questions ask for what changes in a view and
  in which order things happened. A look at how the Interaction and Provenance modules model state changes and
  temporal order (the core relation `precedes` exists) could lift them in every run.
- **Placements of the second look:** check in the expert review whether research-side concepts (`VIS4ML`, `pitfall`,
  evaluation scenarios) belong to the use case or should stay excluded.
- **Planned but not built:** 3-8 central concepts the plan placed were not created by their module; the step 8 report
  lists them - a repair tool ("Add missing central concepts") exists, but the generation could check this itself.
