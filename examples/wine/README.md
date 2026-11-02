# Test project: wine (no literature)

The development test project of [PLAN.md](../../PLAN.md) phase 2: a small, well-known domain without a literature
corpus. It checks that the tool runs end to end without literature and stays domain-independent; every later phase is
checked on it too. Background and the choice of domains: [EVALUATION.md](../../EVALUATION.md) section 5.

**Caveat.** The W3C wine ontology is very likely known to the models (Paulheim, KBC-LM @ ISWC 2025). A result that
resembles it shows that the tool works, not that it generalizes; for that the study uses less known domains.

## Inputs

**Step 2 - use case** (paste as the use case description; no data files):

> A wine shop wants to help its customers choose a wine. The ontology describes wines by their characteristics,
> their origin and their vintage, and says which wines go well with which dishes, so that a recommendation service
> can answer customers' questions.

**Step 4 - conventions:** namespace `https://example.org/wine#`, prefix `wine`, label languages `en`. Let the tool
draft the context; there is no inventory, so there are no conflicting definitions to decide.

**Step 5 - competency questions** (the seven questions of Noy & McGuinness, *Ontology Development 101*, 2001, as
distributed with the CQ4OE benchmark, Apache-2.0, `Annotations/Wine_CQs_Annotations.xlsx`):

1. Which wine characteristics should I consider when choosing a wine?
2. Is Bordeaux a red or white wine?
3. Does Cabernet Sauvignon go well with seafood?
4. What is the best choice of wine for grilled meat?
5. Which characteristics of a wine affect its appropriateness for a dish?
6. Does a bouquet or body of a specific wine change with vintage year?
7. What were good vintages for Napa Zinfandel?

**Step 6 - key notions:** let the tool suggest them and accept what fits. A second run without key notions tests the
modules the plan proposes itself.

**Step 7:** no patterns or standards needed.

## What to record per run

Recorded runs: [RUNS.md](RUNS.md).

| | |
|---|---|
| Model, date, commit | |
| Modules (from key notions or proposed by the plan) | |
| Classes, object/datatype properties, individuals | generation report and evaluation "Structure" |
| Root classes, hierarchy depth | evaluation "Structure" |
| Competency questions fully / partially covered | evaluation tiles |
| Reasoner | evaluation tiles |
| Input / output tokens | token display of the run |

## References for a later comparison (stage C)

- W3C OWL Guide: [wine.rdf](https://www.w3.org/TR/owl-guide/wine.rdf) (74 classes, 13 properties, 161 individuals)
  and [food.rdf](https://www.w3.org/TR/owl-guide/food.rdf) (63 classes, 4 properties).
- CQ4OE gold standard for these questions: `CQ2Onto/00_gold_standard/wine/ontology/sub_wine.owl` with the
  question-to-term and question-to-axiom annotations, and the results of nine models for comparison
  (github.com/oeg-upm/cq4oe-benchmark).
