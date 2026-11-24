# Evaluating the generated ontologies

How the ontologies this tool generates can be evaluated: what the literature does (as of October 2026), what this
means for the tool, what the built-in evaluation (stage A) measures, and which reference domains the study uses. The design decisions behind it are in
[`DECISIONS.md`](DECISIONS.md) (53–63).

The literature review was done with web searches on 2026-10-09. Sources were checked against arXiv, publisher or
proceedings pages; items that could only be confirmed from abstracts or secondary summaries are marked
*(abstract only)*, items that could not be confirmed *(unverified)*. Treat exact figures as provisional.

---

## 1. Literature overview

### 1.1 Classic frameworks

| Approach | What it measures | Automatable | Note |
|---|---|---|---|
| Brank, Grobelnik & Mladenić (2005); Raad & Cruz (2015) | Families of evaluation: gold standard, corpus/data-driven, application/task-based, human assessment | — | The usual classification |
| Gómez-Pérez criteria; Vrandečić, *Ontology Evaluation*, Handbook on Ontologies (2009), DOI 10.1007/978-3-540-92673-3_13 | Accuracy, adaptability, clarity, completeness, computational efficiency, conciseness, consistency, organizational fitness | Partly | Criteria, not procedures |
| **OOPS!** — Poveda-Villalón et al., IJSWIS 10(2), 2014, DOI 10.4018/ijswis.2014040102 | Modeling pitfalls (catalogue P01–P41), critical/important/minor | Yes, REST API | Already in the tool. Rule-based; a 2025 workshop paper (CEUR Vol-4246) argues it misses pitfalls typical of LLM output such as semantic redundancy |
| **FOOPS!** — Garijo, Corcho & Poveda-Villalón, ISWC 2021 demo, CEUR Vol-2980 | FAIR principles: persistent IRIs, metadata, license, accessibility | Yes, REST API | Only meaningful for a published ontology |
| **OntoClean** — Guarino & Welty, CACM 45(2), 2002 | Formal correctness of the taxonomy (rigidity, identity, unity) | Constraint check yes, tagging no | LLM-assisted tagging: Zhao et al., arXiv 2403.15864 (2024), no peer-reviewed follow-up found |
| **OntoQA** — Tartir et al., 2005; **OQuaRE** — Duque-Ramos et al., 2011/2013 | Structural metrics (relationship and attribute richness, inheritance …) | Yes | Descriptive only, no agreed thresholds |
| **NEOntometrics** — Reiz & Sandkuhl, TGDK 2(2), 2024, DOI 10.4230/TGDK.2.2.2 | 160+ metrics incl. OntoQA and OQuaRE | REST API, Docker | Successor of OntoMetrics (offline) |
| **Gold standard** — Dellschaft & Staab, ISWC 2006, DOI 10.1007/11926078_17 | Lexical and taxonomic precision/recall against a reference ontology | Yes | Exact label matching; needs a gold standard |
| **eXtreme Design testing** — Blomqvist, Seil Sepour & Presutti, EKAW 2012 | CQ verification, inference verification, error provocation | Yes (rdflib + reasoner) | Tools: OWLUnit, XDTesting |
| **ROBOT** — Jackson et al., BMC Bioinformatics 20:407, 2019 | Best-practice report, SPARQL "violation" checks, reasoning | Java CLI | Backbone of the OBO tooling |
| Reasoners (HermiT, Pellet, ELK) | Consistency, unsatisfiable classes, inferred hierarchy | owlready2 (Java) | Consistency proves little without individuals (open world) |
| Survey: Wilson et al., *Semantic Web* 14(6), 2023, DOI 10.3233/SW-233393 | Conceptual model of ontology quality | — | Most complete recent general survey |

### 1.2 Evaluation of LLM-generated ontologies (2023–2026)

**Requirements-driven generation (Linköping / Bologna).**
- Saeedizade & Blomqvist, *Navigating Ontology Development with Large Language Models*, ESWC 2024.
  - Compared 11 LLMs and 6 prompting techniques.
  - Phase 1 used reasoner tests (error provocation, inference verification); phase 2 used 8 binary criteria
    checked by hand. Binary criteria were chosen deliberately to reduce subjectivity.
  - Main measure: the share of CQs for which a SPARQL query can be written, strict and relaxed.
  - Baseline: student ontologies. GPT-4 with CQbyCQ reached roughly novice level.
- Lippolis et al., *Ontology Generation Using Large Language Models*, ESWC 2025, LNCS 15718, DOI
  10.1007/978-3-031-94575-5_18, arXiv 2503.05388.
  - Data: 10 ontologies, 100 CQs.
  - Measures: CQ-modelled ratio judged by 2 engineers, the **rate of superfluous elements**, OOPS!, and a blind
    review by 2 other engineers (Cohen's κ = 0.61). No LLM judge.
  - Frequent errors: multiple domains/ranges (P19), wrong inverses, cycles. Results vary from run to run.

**Benchmarks and metrics.**
- Lo et al., *End-to-End Ontology Learning with LLMs* (OLLM), NeurIPS 2024, arXiv 2410.23584.
  - Literal F1 **rewards memorization**.
  - Proposes Fuzzy, Continuous and Graph F1: embedding matching with one-to-one assignment.
- Li, Wang, Garijo & Poveda-Villalón, *CQ4OE*, arXiv 2609.26029 (2026, preprint).
  - Gold ontologies whose CQs are traced to the terms and axioms they need.
  - Measures CQ-conditioned coverage: at least one, mean, or full.
  - Partial coverage is far higher than full coverage (about 89 % vs. 23.5 %).
  - Calls lexical overlap with a whole reference ontology "an unfair proxy for requirement satisfaction".
- LLMs4OL (Babaei Giglou et al., ISWC 2023, arXiv 2307.16648) and the LLMs4OL challenges 2024/2025: term typing,
  taxonomy discovery and relation extraction, scored by P/R/F1 against gold sources.
- Bench4KE (Lippolis et al., arXiv 2505.24554): a benchmark for generated CQs.
- NeOn-GPT (Fathallah et al., ESWC 2024; extended in the Semantic Web journal *(volume unverified)*): structural,
  lexical and embedding similarity to a gold ontology, plus verify-and-repair loops.

**The LLM as evaluator: weak evidence.**
- OE-Assist (Lippolis et al., arXiv 2507.14552, 2025): automatic verification of whether a CQ is modelled reaches
  at most macro-F1 0.66 (o1-preview); GPT-4o was partly below chance.
  - In the user study, correct LLM suggestions raised engineers' accuracy from 70 % to 83 %; wrong ones lowered it
    from 72 % to 44 %.
- RIGOR (Fathallah et al., arXiv 2506.01232, accepted ISWC 2026): an LLM judge and 10 experts agreed on the
  best-ranked system but not on absolute scores (baseline 1.38 vs. 2.74).
- LITE (Zhang et al., arXiv 2504.01369, 2025) proposes rubric-based LLM evaluation of taxonomies *(abstract only)*.
  General studies report κ ≈ 0.72–0.84 with humans on knowledge-graph extraction, but only 64–68 % agreement with
  domain experts on expert tasks (Szymanski et al., arXiv 2410.20266).

**Grounding and provenance.**
- MiniCheck (Tang, Laban & Durrett, EMNLP 2024): a small local fact-checker that checks whether a text supports
  a claim, at about GPT-4 level per the authors.
- DRAGON-AI (Toro, Mungall et al., *J. Biomed. Semantics* 15:19, 2024): LLM-written definitions are acceptable
  but worse than human ones. Confident experts find the most errors.

**Corpus coverage.** Zaitoun, Sagi & Hose, WWW '23 Companion, DOI 10.1145/3543873.3587617: coverage measured
against concepts extracted from a domain corpus, plus a language model judging parent–child relations. There is
no standard "ontology–corpus fit" metric yet.

**Comparison with a reference ontology.**
- OntoAligner (Babaei Giglou et al., ESWC 2025, `pip install ontoaligner`): lexical, retrieval, LLM and RAG
  matchers, intended for small ontologies.
- LLM matchers: OLaLa (Hertling & Paulheim, K-CAP 2023) and MILA (Taboada et al., *Information Fusion* 2025).
- Visual analytics has no recent evaluation; the candidate references are VIS4ML (Sacha et al., IEEE TVCG 2019)
  and VISO (Polowinski & Voigt, 2013).

**Surveys.**
- Li, Garijo & Poveda-Villalón, *LLMs for Ontology Engineering: A Systematic Literature Review* (Semantic Web
  journal, under review): no shared task definitions, datasets or metrics, protocols rarely published, and the LLM
  increasingly used as evaluator.
- Nejah et al., EvalLLM @ CORIA-TALN 2026: evaluation at three levels (task, artifact, pipeline). Task-level
  P/R/F1 does not penalize incoherent output such as cycles. Prompts and protocols are poorly reported.

### 1.3 What is new compared to the classic frameworks

1. **CQ coverage as the main measure**, split into **full and partial**, instead of a single yes/no.
2. **Rate of superfluous elements**, which penalizes over-generation.
3. **Student or novice baselines** besides gold standards.
4. **Embedding matching with one-to-one assignment** instead of literal matching against a reference.
5. **Reference ontologies traced to CQs**, with a reasoner-closure comparison.
6. **The LLM as judge, used with caution**: at most for ranking variants, calibrated against experts, and never
   shown to experts during their review.
7. **Grounding checks** for generated definitions against their sources.

---

## 2. Consequences for this tool

The tool already has properties most of the literature lacks: every class can carry **sources with verified
quotes**, the **concept inventory** is a domain corpus with known provenance, and competency questions are
**executed** as SPARQL against sample data (rdflib decides, not the model).

| Recommendation | Basis |
|---|---|
| Keep CQ tests as SPARQL execution; report **full / partial / none** | OE-Assist (LLM verification is unreliable), CQ4OE |
| Test **hold-out CQs** the generation did not see, taken from the paper cards | Our own design; no paper names hold-out CQs as standard practice |
| Report **untraceable classes** as candidates for superfluous elements | Lippolis et al. 2025 |
| **Corpus coverage** via the class ↔ inventory-concept link stored at generation; embeddings only as a fallback | Zaitoun et al. 2023; the link makes it exact |
| **Reasoner** on the ontology *and* on the CQ sample data | XD testing; open-world caveat |
| **Grounding check**: does the verified quote support the definition? | MiniCheck, DRAGON-AI |
| **Reference comparison** with VIS4ML/VISO via embedding matching, read as precision/overlap | OLLM, CQ4OE, OntoAligner |
| **Expert review**: blind, binary criteria, ≥2 experts, κ | Saeedizade & Blomqvist, Lippolis et al., OE-Assist |
| **LLM judge** only to rank variants, from a different model family, calibrated on 50–100 expert labels | RIGOR, OE-Assist, Szymanski et al. |
| **Study design**: variants, ≥3 runs each, baseline, published prompts and protocols | The surveys' main criticism |
| Deprioritized: FOOPS! (until publication), OntoClean (manual, LLM support immature), large metric suites | — |

### Plan

| Stage | Contents | Status |
|---|---|---|
| **A. Automatic evaluation** | CQ coverage full/partial, hold-out from literature CQs, inventory coverage, hierarchy against the literature, traceability, structure, HermiT; actions to close concept and hierarchy gaps | **Built** (section 3) |
| B. Grounding check | Definition vs. verified quote: MiniCheck locally, or a judge from a different model family | Open |
| C. Reference comparison | VIS4ML/VISO via OntoAligner; precision and overlap, not completeness | Open |
| D. Expert review | Exported sheet per module, binary criteria, blind, ≥2 experts, κ | Open |
| E. Study design | Variants (with/without literature, patterns, models; one-shot vs. modular), ≥3 runs each, baseline, published protocols; reference domains and memorization probe (section 5) | Planning |

---

## 3. Stage A: what the built-in evaluation measures

In step 9, **📊 Evaluate ontology** (`POST /api/evaluate`; logic in `ontology_evaluation.py`). The report belongs to
one iteration; after a change it is marked as outdated. **⬇ Download report (JSON)** saves it for comparing runs and
variants.

**Model calls.** The model is used only to translate competency questions into SPARQL and to write sample data.
Whether a question is covered is decided by rdflib. The CQ results of the current iteration are reused, so an
evaluation usually costs **one** call (for the hold-out questions). Without an API key only the deterministic parts
run.

### 3.1 Competency questions

| Level | Definition |
|---|---|
| **full** | The query parses, uses only declared terms, returns a result that depends on data (sample data or the ontology's individuals - a result of ontology terms only counts if the query returns nothing on the schema alone), and its author does not report leaving part of the question unanswered |
| **partial** | A query could be written and uses ontology terms, but a needed term is missing, there is no answer on the sample data, or the query answers only part of the question (`leaves_out`, e.g. a list where the question asks for the best) |
| **none** | No query could be written, or it does not parse |

- **Sample data** are checked before the queries run: triples with undeclared terms, schema statements about
  ontology terms, and triples whose subject or object has asserted types outside the property's domain or range
  (a grape variety as the subject of a relation between wines and dishes) are dropped and listed. Without
  disjointness axioms the reasoner would silently give the individual the second type. Individuals of the sample
  data need no type to be named in a query.
- **Sample data are kept between iterations of one generation** and only extended, so results stay comparable; a new
  generation starts with new sample data.
- **Limit:** whether a query answers the whole question rests on its author's own statement (`leaves_out`), which can
  only lower a result. A query that answers an easier question without saying so still counts as full; the queries
  are shown in the report for review. `leaves_out` names information the query cannot return, not judgements the
  asker makes from the returned facts (what to consider, whether a value is good enough) - otherwise every question
  with an evaluative word would count as partial. Since the authors still state such judgements, a **separate short
  check** sees each partial answer (question, query, first rows, stated gap) and decides whether the gap is
  information the question asks for (stays partial) or goes beyond it (counts as full; the remark is shown). When in
  doubt it keeps the answer partial (DECISIONS 107).
- **A query without result on its own sample data** gets one correction round before that check: the model sees the
  query, the terms it uses and the sample data, may add sample triples or correct the query, and all queries run
  again (DECISIONS 109).
- **Your questions:** the competency questions of step 5, the ones the generation was given.
- **Hold-out questions:** up to 10 questions from the paper cards that the generation did not see. Selection rules:
  - ordered by how many papers support them
  - questions similar to yours, or to each other, are skipped (word overlap after stop words and stemming ≥ 0.5)
  - at most two per paper, while other papers still have questions

  They show whether the ontology answers what the literature asks, not only what it was built for.

### 3.2 Concept inventory coverage

An inventory concept is covered if a class represents it. Two routes count:
- **the stored link:** module-by-module generation stores the planned concepts on each class
  (`inventory_concepts`, as terms, so it survives a rebuilt inventory)
- **name matching:** the class name or a label matches the concept's label or one of its variants (ignoring case,
  hyphens, plural and CamelCase)

Every concept ends up in one of four categories:

| Category | Meaning |
|---|---|
| **Class** | Represented by a class (via the stored link or a name match) |
| **Represented otherwise** | An individual of that name, or the concept's words occur in a property name (e.g. "Encode" in `encodesAttribute`); a name-based estimate |
| **Deliberately not modeled** | Recorded with a reason when gaps were filled (section 3.7) |
| **Missing** | None of the above |

Reported: all concepts, the **central** concepts (two or more sources) as a class and represented in any form,
coverage per theme, and the lists per category. Coverage of all concepts is low by design; most concepts occur in one paper only. The figure to
watch is central-concept coverage.

### 3.3 Traceability

A class is traceable if at least one of these holds:
- it has **sources**
- it is **linked to the inventory**
- it is used by a **CQ query that passes**, by name or as the domain or range of a property the query uses
- it is a module's **key notion**

Untraceable classes are listed as *candidates* for superfluous elements, to be reviewed; a helper class can be
legitimate. Also reported: the share of properties used by any CQ query.

The report names its **basis**: without literature (no sources, no inventory) only passing CQ queries and key notions
can trace a class; without tested questions either, traceability is not measured.

### 3.4 Structure

| Group | Metrics |
|---|---|
| Size | Classes, object and datatype properties, individuals, axioms, modules |
| Hierarchy | Maximum and mean depth, root classes, mean subclasses per parent |
| OntoQA-style richness | Relationship richness (object properties ÷ (object properties + subclass links)); attribute richness (datatype properties per class) |
| Annotations | Share of classes with a description; share of entities labelled in all convention languages |
| Problems | Unconnected classes; properties without domain or range (core relations excepted); properties declared as a second inverse of a property |
| Disjointness | Sibling groups (≥ 2 subclasses of one parent) with a DisjointClasses axiom (OOPS! P10) |

### 3.5 Hierarchy against the literature

A taxonomic recall with the literature as the reference. The relations come from two places:
- the paper cards' **broader terms**
- their **taxonomies** (category → taxonomy name)

Only relations between terms that are both classes of the ontology are counted. A relation is realized if the class
hierarchy contains it, directly or transitively (parent chain and `SubClassOf` axioms).

Also reported:
- **Declined relations:** relations the plan, the hierarchy step after the modules or "Build hierarchy" declined with
  a reason (a part of it, related to it, the word in another sense). They stay in the denominator of the realized
  share, so it stays comparable with earlier evaluations, and are also counted as **realized or declined**, like
  decided central concepts (DECISIONS 111).
- **Which share to compare:** "realized or declined". The realized share alone is not comparable between two
  ontologies, because a relation only counts when both of its terms are classes, and every generation has a different
  set of classes: of the 99 relations the VA baseline realizes, 56-63 do not exist at all in a later run, and each
  run realizes 49-64 that the baseline does not have (DECISIONS 118).
- **Attachable concepts:** missing central concepts whose broader term already is a class.
- **Relevant taxonomies:** taxonomies whose categories or name match classes.

### 3.6 Reasoner

HermiT via `owlready2` checks consistency and unsatisfiable classes, for the ontology alone and together with the
CQ sample data. It needs **Java**; without it the check is skipped with a note. It runs in a separate process with
a 180-second limit. HermiT accepts only the OWL 2 datatype map: ranges and literals of other XML Schema types (such as
`xsd:gYear`) are replaced by `rdfs:Literal` and plain literals for the check, and listed in the report.

### 3.6a Decided definitions

When the team has decided conflicting definitions in step 4 (DECISIONS 83), the evaluation checks without a model
that every decided class exists and carries its decided definition as description (whitespace, case and a final
period are ignored). It reports the conflicts that are still undecided or left open, the classes whose description
differs and the missing ones; **📌 Apply decided definitions** repairs both with edit operations.

### 3.7 Improving from the literature

The evaluation box offers two actions. Both change the **existing** ontology with edit operations; nothing is
regenerated.

**➕ Add missing central concepts.** Packages of 12 concepts. Each concept comes with its definitions, broader terms
(marked if they already are a class), citations and existing-ontology URIs. The model adds each one as a class (below
a fitting superclass), an individual or a property, or declines it with a reason.

**🌳 Build hierarchy from the literature.** Packages of 25 unrealized broader/narrower relations or 6 taxonomies. The
model sets superclasses where the relation holds (or adds `SubClassOf` axioms if the class already has another
valid superclass), arranges taxonomy categories below their class, and adds disjointness where categories cannot
overlap. Relations used loosely in the papers (part-of, related-to) are declined.

How a run works:
- The work is counted first and only starts after confirmation.
- The browser sends the packages one by one, with visible progress and a stop button.
- Declined items are recorded with their reason and are not proposed again.
- **After each package HermiT checks** whether a class became unsatisfiable or the ontology inconsistent, measured
  against the state before the run. If so, the model gets one correction request; otherwise the package is rolled
  back.
- One action is one iteration and one entry in the feedback log. An OOPS! check runs at the end.

**Test run on a copy of the VA ontology** (229 classes), with a simulated model that applies everything it is
offered:

| | Before | After |
|---|---|---|
| Central concepts as a class | 134 of 264 (50.8 %) | 182 (68.9 %); 47 declined, 0 missing |
| Unsatisfiable classes, without the reasoner check | — | 27 |
| Unsatisfiable classes, with the reasoner check | — | 0 (two relation packages rolled back) |

A real model judges the relations instead of applying them all, so it should lose fewer packages.

---

## 4. Limits of stage A

- **CQ results depend on the generated SPARQL and sample data.** A question can fail because of a poor query. The
  query and data are shown so this can be checked.
- **Name matching is lexical.** Synonyms that are neither stored links nor inventory variants are missed.
  Embedding matching is the planned fallback.
- **Untraceable is not superfluous**, and traceable is not correct: a class with sources can still be modeled
  wrongly. Correctness needs stages B and D.
- **A consistent ontology can still be wrong.** OWL's open-world semantics catch little without disjointness
  axioms — which is why the disjointness of sibling groups is reported.

---

## 5. Reference domains for the study (stage E)

Researched on 2026-10-16 (web searches, GitHub API, the ontology files themselves). Counts were taken from the files
with a simple script and are approximate. The concern behind the choice: a generated ontology that resembles a
well-known reference may only show that the model has seen the reference, not that the tool works.

### 5.1 Contamination

- Paulheim, *Towards Evaluating Knowledge Graph Construction and Ontology Learning with LLMs without Test Data
  Leakage*, KBC-LM @ ISWC 2025, CEUR Vol-4041 paper 2.
  - A second LLM generates synthetic replicas of an ontology, which are used once and discarded.
  - Originals: Pizza and the **W3C Wine ontology**. Results on the beer, gin and whiskey replicas are worse, which the
    author reads as a hint that LLMs learned part of their ontology engineering on the wine ontology.
- Golchin & Surdeanu, *Time Travel in LLMs*, arXiv 2308.08493: "guided instruction" - the dataset name and the first
  part of an instance, the model completes it; a near-exact completion flags contamination.
- Deng et al., TS-Guessing, NAACL 2024: mask an unlikely word of a benchmark item and let the model fill it in.
- Shi et al., Min-K% Prob, ICLR 2024: membership inference from token log-probabilities (open-weight models only).
- Bombieri et al., *Do LLMs Dream of Ontologies?*, ACM TIST 2025 (arXiv 2401.14931): LLMs reproduce ID-label pairs of
  GO, Uberon and ICD-10 in proportion to how often the concepts appear on the web.
- **Not found:** a published test that asks a model to reproduce a whole ontology from its name alone.

Consequence: before a run on a reference domain, a **memorization probe** with the model that will generate (the
generating model's training cutoff counts, not the assistant's): (1) name only - "list the classes and properties of
ontology X"; (2) guided - the name plus the first lines of the reference's Turtle, continue. Both are scored against
the reference with the same matching as the comparison. A high score means the domain cannot support a
generalization claim.

### 5.2 Candidates

| Ontology | Domain | Published | CQs | Size | Licence | Notes |
|---|---|---|---|---|---|---|
| W3C Wine (+ Food) | wine, food | OWL Guide 2004 | 7 source / 5 annotated (CQ4OE) | 74 classes, 13 properties, 161 individuals, 116 restrictions (Food: 63 classes, 59 restrictions) | W3C | very likely memorized (Paulheim); in CQ4OE, so directly comparable |
| UC Davis wine-ontology | wine | draft, last push 2020 | - | 3.8 KB, does not parse | MIT | unusable |
| **SAREF4WATR** | water (ETSI TS 103 410-10) | v2.1.1, 2025-04-25 | 43 source / 21 annotated (CQ4OE) | 54 classes (40 own), 34 object (8 own) and 19 datatype properties | ETSI software licence | in CQ4OE; hardest medium domain there (global domain/range triple F1 at most 3.5 %), which speaks against memorization; link, do not redistribute |
| **OntoPFAS** | PFAS ("forever chemicals"), environment | ESWC 2026 Resources Track (LNCS 16550); repo since 2025-02 | 30 from experts, each with SPARQL (file added 2025-12) | ~15 own + ~25 reused classes, 34 object, 22 data properties | CC BY 4.0 | not in CQ4OE; paper with references gives a literature corpus; a first version public since Feb 2025 |
| COPI | petroleum installations | repo 2026-02, release 2026-09 | full ORSD, 176 rows | very large (BFO/IOF imports) | CC BY 4.0 | axioms drafted with an LLM tool - confound as gold standard; usable only as a subset |
| PIIRRITE | inclusive pedestrian navigation | repo 2026-02, v1.0.0 2026-07 | 29 with SPARQL | ~41 classes | CC BY 4.0 (header only) | no peer-reviewed paper |
| VGO | video games | 2014, unmaintained | 68 source (CQ4OE) | ~32 classes | CC BY-NC-SA 2.0 | outdated, non-commercial |

**CQ4OE** (Li, Wang, Garijo & Poveda-Villalón, arXiv 2609.26029, Sep 2026): data and code under Apache-2.0
(github.com/oeg-upm/cq4oe-benchmark, Zenodo 10.5281/zenodo.20080309, HuggingFace oeg/CQ4OE). Six ontologies - Wine,
African Wildlife, ODRL, SAREF4WATR, Video Game, Software Ontology - with 255 source CQs, 118 traced to terms and
axioms, and results of 9 open models (one-shot, CQ by CQ, multi-agent). Average class F1 59.7 %, property F1 31.8 %;
full CQ coverage 23.5 %, for Wine 0 % for every model.

### 5.3 Choice

| Domain | Role | Literature |
|---|---|---|
| Visual analytics | case study of the full workflow (56 papers) | yes |
| Wine | **development test project** (PLAN.md phase 2: small, well known, no literature); in the paper only as a deliberately "known" domain comparable with CQ4OE, with the contamination caveat | no |
| SAREF4WATR | **generalization claim**, comparable with CQ4OE | optional (ETSI TR 103 547) |
| OntoPFAS | second generalization case if time allows | yes (paper references) |

Every reference run starts with the memorization probe of 5.1; its result is reported with the comparison.
