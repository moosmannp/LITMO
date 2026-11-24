"""Tests for ontology_evaluation and the /api/evaluate endpoint: structure, coverage, traceability,
hold-out questions and the reasoner (needs Java; skipped without it)."""
import json

from fastapi.testclient import TestClient

import app as A
import corpus as C
import editing as E
import llm as L
import ontology_io as O
import project as P
import vocabularies as V
from ontology_evaluation import structural_metrics, concept_coverage, traceability, cq_level, cq_coverage, select_holdout_cqs, reasoner_check, java_available, holdout_details
from helpers import base, CFG, FakeLLM, cq_reply, gap_inventory

key = C.concept_key


def inventory():
    return {"concepts": [
        {"id": "c1", "label": "Task", "variants": ["analysis task"], "papers": 5},
        {"id": "c2", "label": "Low-level tasks", "variants": [], "papers": 3},       # matches LowLevelTask by name
        {"id": "c3", "label": "Glyph", "variants": [], "papers": 2},                 # not modeled
        {"id": "c4", "label": "Data table", "variants": ["dataset"], "papers": 1},   # matches Dataset via a variant
    ], "themes": [{"name": "Analysis", "concepts": ["c1", "c2"]}, {"name": "Representation", "concepts": ["c3"]}],
       "competency_questions": [
        {"question": "Which tasks does a visualization support?", "docs": ["d1", "d2", "d3"]},
        {"question": "Which tasks are supported by a visualization?", "docs": ["d4", "d5"]},   # near-duplicate
        {"question": "Which glyphs encode several attributes?", "docs": ["d1"]},
        {"question": "What data does a task use?", "docs": ["d2", "d3"]},                     # like the team's CQ
    ]}


def test_structural_metrics():
    onto = base()
    onto["classes"].append({"name": "Orphan", "labels": {"en": "Orphan"}, "parent": None, "module": "Data"})
    onto["classes"].append({"name": "HighLevelTask", "labels": {"en": "x", "de": "x"}, "parent": "Task", "module": "Tasks",
                            "description": "y"})
    m = structural_metrics(onto, ["en", "de"])
    assert m["classes"] == 5 and m["object_properties"] == 2 and m["datatype_properties"] == 1
    assert m["max_depth"] == 2 and m["root_classes"] == 3
    assert m["orphan_classes"] == ["Orphan"]
    assert m["sibling_groups"] == 1 and m["sibling_groups_with_disjointness"] == 0    # Low/HighLevelTask not disjoint
    assert m["entities_labelled_in_all_languages_pct"] < 20                          # base() has English labels only
    assert m["relationship_richness"] == round(2 / (2 + 2), 3)
    onto["axioms"].append({"type": "DisjointClasses", "classes": ["LowLevelTask", "HighLevelTask"]})
    assert structural_metrics(onto)["sibling_groups_with_disjointness"] == 1


def test_a_class_below_a_vocabulary_term_is_no_root_when_the_term_is_below_an_own_class():
    # VA 5c: User below prov:Person, and prov:Person SubClassOf Agent (DECISIONS 132)
    onto = base()
    onto["classes"] += [{"name": "Agent", "labels": {"en": "Agent"}, "parent": None, "module": "Tasks"},
                        {"name": "User", "labels": {"en": "User"}, "parent": "prov:Person", "module": "Tasks"},
                        {"name": "Role", "labels": {"en": "Role"}, "parent": "dcat:Role", "module": "Tasks"}]
    onto["axioms"].append({"type": "SubClassOf", "classes": ["prov:Person", "Agent"]})
    m = structural_metrics(onto)
    # roots: Task, Dataset, Agent and Role (below dcat:Role only); User is below Agent through prov:Person
    assert m["root_classes"] == 4 and m["classes_below_vocabulary_only"] == ["Role"]


def test_structural_metrics_count_class_restrictions():
    onto = base()
    assert (structural_metrics(onto)["restrictions"], structural_metrics(onto)["classes_with_restriction"]) == (0, 0)
    onto["restrictions"] = [{"class": "Task", "property": "usesData", "kind": "some", "value": "Dataset"},
                            {"class": "Task", "property": "hasName", "kind": "max", "value": "xsd:string", "n": 1}]
    m = structural_metrics(onto)
    assert (m["restrictions"], m["classes_with_restriction"]) == (2, 1)


def test_concept_coverage_by_link_name_and_variant():
    onto = base()
    cov = concept_coverage(onto, inventory(), key)
    assert cov["covered"] == 3 and cov["central_covered"] == 2 and cov["central_concepts"] == 3
    assert [m["label"] for m in cov["missing_central"]] == ["Glyph"]
    assert {t["name"]: t["covered_pct"] for t in cov["themes"]} == {"Analysis": 100.0, "Representation": 0.0}
    # a stored link from generation counts even if the class is named differently
    onto["classes"][2]["name"] = "Visual"
    onto["classes"][2]["inventory_concepts"] = ["Glyph"]
    assert concept_coverage(onto, inventory(), key)["central_covered"] == 3
    assert concept_coverage(onto, None, key) == {"available": False}


def test_traceability_and_untraceable_classes():
    onto = base()
    onto["classes"].append({"name": "Helper", "labels": {"en": "Helper"}, "module": "Tasks"})
    cq = {"tests": [{"status": "passed", "terms": ["Dataset", "usesData"]},
                    {"status": "failed", "terms": ["Helper"]}]}          # a failing query does not justify a class
    t = traceability(onto, [cq, None], inventory(), key)
    assert t["untraceable"] == ["Helper"]
    # Dataset is named by the query, Task is the domain of usesData: both are needed for the answer
    assert t["with_sources_pct"] == 25.0 and t["used_by_passing_cq_pct"] == 50.0
    assert "hasName" in t["properties_unused_by_cq"] and "usesData" not in t["properties_unused_by_cq"]


def test_without_literature_only_competency_questions_trace_classes():
    onto = base()
    for c in onto["classes"]:
        c.pop("sources", None)
    t = traceability(onto, [None, None], None, key)
    assert t["basis"] == "none" and t["untraceable_pct"] is None and t["untraceable"] == []
    t = traceability(onto, [{"tests": [{"status": "passed", "terms": ["Dataset"]}]}, None], None, key)
    assert t["basis"] == "competency questions" and "Dataset" not in t["untraceable"] and t["untraceable_pct"] > 0
    assert traceability(base(), [None, None], inventory(), key)["basis"] == "literature"


def test_cq_levels():
    assert cq_level({"status": "passed"}) == "full"
    assert cq_level({"status": "failed", "parses": True, "terms": ["Task"]}) == "partial"
    assert cq_level({"status": "failed", "parses": True, "terms": []}) == "none"
    assert cq_level({"status": "failed", "parses": False}) == "none"
    assert cq_level({"status": "not_answerable"}) == "none"
    c = cq_coverage({"tests": [{"status": "passed"}, {"status": "not_answerable"}]})
    assert (c["full"], c["none"], c["full_pct"]) == (1, 1, 50.0)


def test_holdout_selection_skips_team_questions_and_near_duplicates():
    picked = select_holdout_cqs(inventory(), ["What data does a task use?"], limit=10)
    assert picked == ["Which tasks does a visualization support?", "Which glyphs encode several attributes?"]
    assert select_holdout_cqs(None, []) == []
    # one paper with many questions does not fill the set while other papers have questions
    inv = {"competency_questions": [{"question": q, "docs": ["d1"]} for q in (
               "Which uncertainty events occur in the data source?", "How is uncertainty propagated between components?",
               "Which quantification technique suits a system event?", "Who is aware of model uncertainty?")] +
                                   [{"question": "Which glyphs encode several attributes?", "docs": ["d2"]}]}
    picked = select_holdout_cqs(inv, [], limit=3)
    assert len(picked) == 3 and "Which glyphs encode several attributes?" in picked


def holdout_inventory():
    c = lambda i, label, papers: {"id": i, "label": label, "variants": [], "papers": papers}
    q = lambda text, doc: {"question": text, "docs": [doc]}
    return {"concepts": [c("c1", "Task", 5), c("c2", "Visualization", 4), c("c3", "Data", 6), c("c4", "Uncertainty", 3),
                         c("c5", "Vega-Lite", 1), c("c6", "unit specification", 1), c("c7", "Interaction", 3)],
            "themes": [{"name": "Analysis", "concepts": ["c1", "c3"]}, {"name": "Representation", "concepts": ["c2", "c7"]},
                       {"name": "Uncertainty", "concepts": ["c4"]}],
            "competency_questions": [
                q("What components define a Vega-Lite unit specification?", "d1"),   # only single-source concepts
                q("Which tasks use data?", "d2"),
                q("How does uncertainty affect a visualization?", "d3"),
                q("Which interaction supports a visualization of data?", "d4"),
                q("Which uncertainty arises in an interaction?", "d5"),
                q("Which tasks can a visualization of uncertain data help with?", "d6")]}   # modal: can, help


def test_holdout_questions_are_chosen_by_their_central_concepts_and_spread_over_the_themes():
    # DECISIONS 133: almost every literature question has one source, so the concepts it names decide
    inv = holdout_inventory()
    picked = select_holdout_cqs(inv, [], limit=3)
    # most central concepts first, one per theme, then a second one of a theme
    assert picked == ["Which interaction supports a visualization of data?",
                      "How does uncertainty affect a visualization?", "Which tasks use data?"]
    picked = select_holdout_cqs(inv, [], limit=10)
    assert picked[-1] == "What components define a Vega-Lite unit specification?"   # only to fill up
    # DECISIONS 134: a question about what can or must be comes after the plain ones, though it names more concepts
    assert picked[-2] == "Which tasks can a visualization of uncertain data help with?"
    # an earlier selection stays, as far as it is still eligible
    keep = ["Which uncertainty arises in an interaction?", "gone from the inventory"]
    assert select_holdout_cqs(inv, [], limit=2, keep=keep)[0] == "Which uncertainty arises in an interaction?"
    d = holdout_details(inv, ["What components define a Vega-Lite unit specification?", "Which tasks use data?"])
    assert d[0]["central"] == [] and d[0]["single_source"] == ["Vega-Lite", "unit specification"]
    assert d[1]["central"] == ["data", "tasks"] and d[1]["theme"] == "Analysis"     # the words of the question
    assert d[1]["modal"] == [] and holdout_details(inv, ["Which tasks can data help with?"])[0]["modal"] == ["can", "help"]


def test_the_holdout_set_is_stored_and_the_team_can_remove_questions():
    client = TestClient(A.app)
    sid = client.post("/api/session/create").json()["session_id"]
    s = A.sessions[sid]
    s["corpus"] = {"docs": [], "inventory": holdout_inventory()}
    first = client.post("/api/holdout", json={"session_id": sid}).json()
    qs = [q["question"] for q in first["questions"]]
    assert len(qs) == 3 and qs[0] == "Which interaction supports a visualization of data?"   # at most half of 6 (DECISIONS 137)
    assert first["questions"][0]["central"] == ["data", "visualization", "interaction"]
    d = client.post("/api/holdout/remove", json={"session_id": sid, "question": qs[0]}).json()
    assert qs[0] not in [q["question"] for q in d["questions"]] and d["removed"] == [qs[0]]
    # the evaluation tests the stored set; without a model it only selects
    s["ontology"], s["iterations"] = base(), 1
    client.post("/api/evaluate", json={"session_id": sid})
    assert qs[0] not in s["holdout"]["questions"] and len(s["holdout"]["questions"]) == 3
    # a set chosen by older rules is chosen again once; removed questions stay removed
    s["holdout"] = {"questions": ["Which tasks can a visualization of uncertain data help with?"], "removed": [qs[0]]}
    d = client.post("/api/holdout", json={"session_id": sid}).json()
    assert [q["question"] for q in d["questions"]][0] == "Which tasks use data?" and qs[0] not in str(d["questions"])
    d = client.post("/api/holdout/reset", json={"session_id": sid}).json()
    assert d["removed"] == [] and [q["question"] for q in d["questions"]] == qs


def test_holdout_excludes_questions_the_cq_suggestions_saw():
    seen = ["Which tasks does a visualization  SUPPORT?"]                  # compared case- and space-insensitively
    picked = select_holdout_cqs(inventory(), [], limit=10, exclude=seen)
    assert "Which tasks does a visualization support?" not in picked
    assert "Which glyphs encode several attributes?" in picked


def test_suggest_cqs_records_shown_questions_and_evaluate_excludes_them():
    client = TestClient(A.app)
    sid = client.post("/api/session/create").json()["session_id"]
    s = A.sessions[sid]
    assert s["cqs_shown_to_model"] == []
    inv = {**inventory(), "doc_ids": [], "themes": []}               # complete enough for inventory_overview
    inv["concepts"] = [{**c, "sources": []} for c in inv["concepts"]]
    s["corpus"] = {"docs": [], "inventory": inv}
    L.call_llm = FakeLLM({"competency_questions": [{"question": "What data does a task use?"}]})
    client.post("/api/momo/suggest-cqs", json={"session_id": sid, "llm_config": CFG})
    # DECISIONS 137: the hold-out set is chosen first (at most half of the 4) and not shown to the suggestions
    held = s["holdout"]["questions"]
    assert len(held) == 2
    assert s["cqs_shown_to_model"] == [q["question"] for q in inventory()["competency_questions"] if q["question"] not in held]
    assert not any(q in L.call_llm.calls[0][-1]["content"] for q in held)
    s["ontology"], s["iterations"] = base(), 1
    s["momo"]["competency_questions"] = [{"question": "What data does a task use?"}]
    d = client.post("/api/evaluate", json={"session_id": sid}).json()       # no model: hold-out is only selected
    # a held question the team takes as its own leaves the set (it is no longer a question the ontology was not built for)
    assert d["holdout_excluded"] == 2 and s["holdout"]["questions"] == [q for q in held if q != "What data does a task use?"]
    # a session from before the recording: the first questions are excluded to be safe, with a note
    del s["cqs_shown_to_model"]
    d = client.post("/api/evaluate", json={"session_id": sid}).json()
    assert d["holdout_excluded"] == 4 and any("to be safe" in n for n in d["notes"])


def test_reconsider_withdraws_decisions_and_updates_the_stored_coverage():
    client = TestClient(A.app)
    sid = client.post("/api/session/create").json()["session_id"]
    s = A.sessions[sid]
    inv = gap_inventory()
    inv["concepts"][4]["variants"] = ["linked brushing"]
    s["ontology"], s["iterations"] = base(), 1
    s["corpus"] = {"docs": [], "inventory": inv}
    s["gap_decisions"] = {key("linked brushing"): "out of scope", key("Glyph"): "too specific",
                          key("Encode"): "a property"}
    s["evaluation"] = {"coverage": concept_coverage(s["ontology"], inv, key, s["gap_decisions"])}
    assert s["evaluation"]["coverage"]["central_decided"] == 3
    # by the label shown in the evaluation; the decision was stored under a variant
    d = client.post("/api/gaps/reconsider", json={"session_id": sid, "labels": ["Brushing"]}).json()
    assert d["removed"] == 1 and d["remaining"] == 2 and key("linked brushing") not in s["gap_decisions"]
    assert d["evaluation"]["coverage"]["central_decided"] == 2
    assert "Brushing" in [m["label"] for m in d["evaluation"]["coverage"]["missing_central"]]
    preview = client.post("/api/gaps/start", json={"session_id": sid, "kind": "concepts", "dry_run": True}).json()
    assert preview["items"] == 1                                            # Brushing is proposed again
    d = client.post("/api/gaps/reconsider", json={"session_id": sid, "all": True}).json()
    assert d["removed"] == 2 and s["gap_decisions"] == {} and d["evaluation"]["coverage"]["central_decided"] == 0


def test_reasoner_finds_unsatisfiable_classes_and_inconsistent_data():
    if not java_available():
        print("   (skipped: no Java)")
        return
    onto = base()
    onto["classes"].append({"name": "Impossible", "labels": {"en": "x"}, "parent": "Task", "module": "Tasks"})
    onto["axioms"].append({"type": "SubClassOf", "classes": ["Impossible", "Dataset"]})   # Task and Dataset are disjoint
    turtle = O.ontology_to_turtle(onto)
    sample = ("@prefix : <https://example.org/t#> .\n:x a :Task , :Dataset .")            # violates the disjointness
    r = reasoner_check(turtle, sample)
    assert r["available"] and r["ontology"]["consistent"] is True
    assert r["ontology"]["unsatisfiable"] == ["Impossible"]
    assert r["with_sample_data"]["consistent"] is False
    assert reasoner_check(O.ontology_to_turtle(base()))["ontology"] == {"consistent": True, "unsatisfiable": []}


def test_datatypes_outside_owl2_are_replaced_for_the_reasoner_and_reported():
    if not java_available():
        print("   (skipped: no Java)")
        return
    onto = base()
    onto["properties"].append({"name": "hasYear", "type": "DatatypeProperty", "domain": "Dataset", "range": "xsd:gYear",
                               "labels": {"en": "has year"}, "module": "Data"})
    sample = ('@prefix : <https://example.org/t#> .\n@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n'
              ':d a :Dataset ; :hasYear "1990"^^xsd:gYear .\n:t a :Task ; :hasName "2020-01-01"^^xsd:date .')
    r = reasoner_check(O.ontology_to_turtle(onto), sample)
    assert r["ontology"] == {"consistent": True, "unsatisfiable": []} and r["with_sample_data"]["consistent"] is True
    assert r["datatypes_outside_owl2"] == {"xsd:date": [], "xsd:gYear": ["hasYear"]}
    assert "datatypes_outside_owl2" not in reasoner_check(O.ontology_to_turtle(base()))


def test_evaluate_endpoint_reuses_fresh_cq_tests_and_runs_holdout():
    client = TestClient(A.app)
    sid = client.post("/api/session/create").json()["session_id"]
    s = A.sessions[sid]
    s["ontology"] = base()
    s["iterations"] = 1
    s["momo"]["competency_questions"] = [{"question": "What data does a task use?"}]
    s["corpus"] = {"docs": [], "inventory": inventory()}
    q = "PREFIX : <https://example.org/t#> SELECT ?d WHERE { ?t a :Task ; :usesData ?d }"
    E.check_oops = lambda turtle: []
    # first call: no CQ test of this iteration yet -> team CQs are tested, then the hold-out questions
    llm = FakeLLM(cq_reply(1, q), cq_reply(2, q))
    L.call_llm = llm
    d = client.post("/api/evaluate", json={"session_id": sid, "llm_config": CFG}).json()
    assert len(llm.calls) == 2 and d["cq_tests"]["passed"] == 1
    assert (d["cq"]["full"], d["holdout"]["total"], d["holdout"]["full"], d["holdout"]["none"]) == (1, 2, 1, 1)
    assert [c["step"] for c in d["usage"]["calls"]] == ["CQ tests", "Hold-out CQ tests"]
    assert d["coverage"]["central_covered"] == 2 and "Glyph" in [m["label"] for m in d["coverage"]["missing_central"]]
    assert "Dataset" not in d["traceability"]["untraceable"]
    assert s["evaluation"]["iteration"] == 1
    if java_available():
        assert d["reasoner"]["ontology"]["consistent"] and d["reasoner"]["with_sample_data"]["consistent"]
    # second call in the same iteration: the team's CQ results are reused, only the hold-out costs a call
    llm2 = FakeLLM(cq_reply(2, q))
    L.call_llm = llm2
    d2 = client.post("/api/evaluate", json={"session_id": sid, "llm_config": CFG, "holdout": True}).json()
    assert len(llm2.calls) == 1 and d2["cq_tests"] is None and d2["cq"]["full"] == 1
    # without a model: deterministic parts only, with notes
    s["iterations"] = 2
    d3 = client.post("/api/evaluate", json={"session_id": sid, "llm_config": None}).json()   # as the browser sends it
    assert d3["cq"] is None and d3["holdout"] is None and len(d3["notes"]) == 1 and d3["metrics"]["classes"] == 3


def test_the_previous_evaluation_of_another_iteration_is_kept_for_comparison():
    # DECISIONS 136: Evaluate - repair - Evaluate; before, the second evaluation overwrote the first (VA class restrictions)
    client = TestClient(A.app)
    sid = client.post("/api/session/create").json()["session_id"]
    s = A.sessions[sid]
    s["ontology"], s["iterations"] = base(), 1
    d1 = client.post("/api/evaluate", json={"session_id": sid, "holdout": False}).json()
    assert d1["previous"] is None
    d1b = client.post("/api/evaluate", json={"session_id": sid, "holdout": False}).json()   # same iteration again
    assert d1b["previous"] is None and "evaluation_previous" not in s
    s["ontology"]["classes"].append({"name": "Glyph", "labels": {"en": "Glyph"}, "parent": None, "module": "Data"})
    s["iterations"] = 2                                                    # a repair step
    d2 = client.post("/api/evaluate", json={"session_id": sid, "holdout": False}).json()
    assert d2["previous"]["iteration"] == 1 and d2["previous"]["figures"]["classes"] == 3
    assert d2["metrics"]["classes"] == 4
    d2b = client.post("/api/evaluate", json={"session_id": sid, "holdout": False}).json()   # still compared with 1
    assert d2b["previous"]["iteration"] == 1


def test_evaluate_3x_tests_the_questions_three_times_from_scratch_and_reports_mean_and_spread():
    import threading
    client = TestClient(A.app)
    sid = client.post("/api/session/create").json()["session_id"]
    s = A.sessions[sid]
    s["ontology"], s["iterations"] = base(), 1
    s["momo"]["competency_questions"] = [{"question": "What data does a task use?"}]
    s["corpus"] = {"docs": [], "inventory": inventory()}
    q = "PREFIX : <https://example.org/t#> SELECT ?d WHERE { ?t a :Task ; :usesData ?d }"
    E.check_oops = lambda turtle: []
    lock, team_calls = threading.Lock(), []

    def fake(cfg, messages, effort="high"):      # the runs 2 and 3 call from threads, in any order
        L._record_usage(100, 10)
        if "Which glyphs" in messages[-1]["content"]:                                    # the hold-out questions
            return json.dumps(cq_reply(2, q))
        with lock:
            team_calls.append(1)
            n = len(team_calls)
        return json.dumps(cq_reply(1, q) if n != 2 else {"sample_data": "", "tests": [
            {"cq": 1, "sparql": None, "missing": "nothing models this"}]})                 # one run fails the question
    L.call_llm = fake
    d = client.post("/api/evaluate", json={"session_id": sid, "llm_config": CFG, "repeats": 3}).json()
    r = d["cq_repeats"]
    assert r["runs"] == 3 and sorted(r["full"]["runs"]) == [0, 1, 1] and r["full"]["mean"] == 0.7 and r["full"]["sd"] == 0.6
    q = r["questions"][0]
    assert (q["question"], q["full"], sorted(q["levels"])) == ("What data does a task use?", 2, ["full", "full", "none"])
    assert sorted(q["errors"])[:2] == ["", ""] and sorted(q["errors"])[2]          # why the one run failed
    assert r["varying"] == 1 and d["holdout_repeats"]["full"] == {"runs": [1, 1, 1], "mean": 1, "sd": 0.0}
    steps = sorted(c["step"] for c in d["usage"]["calls"])
    assert steps == sorted(["CQ tests", "Hold-out CQ tests", "CQ tests (run 2 of 3)", "CQ tests (run 3 of 3)",
                            "Hold-out CQ tests (run 2 of 3)", "Hold-out CQ tests (run 3 of 3)"])
    # the first run is the stored one; a single evaluation has no repeats
    assert s["cq_test_report"]["result"]["passed"] == 1 and d["cq"]["full"] == 1
    d1 = client.post("/api/evaluate", json={"session_id": sid, "llm_config": CFG, "repeats": 1}).json()
    assert d1["cq_repeats"] is None and d1["holdout_repeats"] is None


def test_coverage_distinguishes_other_representations_and_decisions():
    onto = base()
    onto["properties"].append({"name": "encodesAttribute", "type": "ObjectProperty", "domain": "Task", "range": "Dataset"})
    cov = concept_coverage(onto, gap_inventory(), key, {key("Brushing"): "out of scope"})
    assert (cov["central_covered"], cov["central_other"], cov["central_decided"], cov["central_missing"]) == (2, 1, 1, 1)
    assert cov["other_central"][0]["as"] == "encodesAttribute" and cov["missing_central"][0]["label"] == "Glyph"
    assert cov["central_represented_pct"] == 80.0


def test_hierarchy_coverage_counts_realized_relations_and_attachable_concepts():
    from ontology_evaluation import hierarchy_coverage
    onto = base()                     # LowLevelTask has parent Task -> the 'broader' and the taxonomy relation hold
    h = hierarchy_coverage(onto, gap_inventory(), key)
    assert (h["relations"], h["realized"], h["unrealized_count"]) == (1, 1, 0)
    assert [a["label"] for a in h["attachable"]] == ["Glyph"] and h["attachable"][0]["broader"] == "Dataset"
    onto["classes"][1]["parent"] = None                               # remove the subclass link
    h = hierarchy_coverage(onto, gap_inventory(), key)
    assert h["realized"] == 0 and h["unrealized"][0] == {"narrower": "LowLevelTask", "broader": "Task", "support": 2,
                                                         "origins": ["broader term", "taxonomy"]}
    # the taxonomy is open while its category is not below its root, and once decided it is no longer open
    assert (h["relevant_taxonomies"], h["open_taxonomies"]) == (1, 1)
    decided = P.declined_relations({"gap_hierarchy_decisions": {P._norm("Taxonomy 'Tasks'"): {"item": "x", "reason": "y"}}})
    assert hierarchy_coverage(onto, gap_inventory(), key, None, decided)["open_taxonomies"] == 0
    onto["axioms"].append({"type": "SubClassOf", "classes": ["LowLevelTask", "Task"]})   # an axiom also realizes it
    h = hierarchy_coverage(onto, gap_inventory(), key)
    assert h["realized"] == 1 and (h["relevant_taxonomies"], h["open_taxonomies"]) == (1, 0)


def test_module_names_used_as_prefixes_are_repaired():
    onto = base()                                          # modules Tasks and Data
    onto["properties"][0]["range"] = "Data:Dataset"
    onto["classes"][1]["parent"] = "Tasks:Task"
    onto["axioms"].append({"type": "SubClassOf", "classes": ["Dataset", "pl:Entity"]})   # a real vocabulary term
    onto["properties"][1]["domain"] = "Other:Unknown"       # unknown class: left for the other checks
    fixed, repaired = V.repair_module_prefixes(onto, {"pl", "xsd"})
    by = {p["name"]: p for p in fixed["properties"]}
    assert by["usesData"]["range"] == "Dataset" and fixed["classes"][1]["parent"] == "Task"
    assert ["Dataset", "pl:Entity"] in [a["classes"] for a in fixed["axioms"]] and by["usedByTask"]["domain"] == "Other:Unknown"
    assert repaired == ["repaired Data:Dataset -> Dataset", "repaired Tasks:Task -> Task"] or \
        sorted(repaired) == sorted(["repaired Data:Dataset -> Dataset", "repaired Tasks:Task -> Task"])
    onto2 = base()
    onto2["properties"][0]["range"] = "Data:Dataset"
    assert structural_metrics(onto2)["external_links"] == 0                 # a module name is no vocabulary
