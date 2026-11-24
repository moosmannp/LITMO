"""Tests for the improvement actions on an existing ontology: missing concepts, hierarchy, upper layer,
core relations and alignment, with their decisions and the reasoner guard."""
import copy

from fastapi import HTTPException
from fastapi.testclient import TestClient

import app as A
import corpus as C
import editing as E
import improvements as IM
import llm as L
import ontology_io as O
import project as P
import vocabularies as V
from ontology_evaluation import structural_metrics, concept_coverage, traceability, reasoner_check, java_available
from helpers import base, CFG, FakeLLM, align_session, gap_inventory, property_onto

key = C.concept_key


REAL_CALL_LLM = L.call_llm          # tests replace L.call_llm with fakes; keep the real one


VOCAB = {"summary": "two relations", "relations": [
    {"name": "uses", "description": "makes use of", "domain": "Task", "range": "Dataset",
     "inverse": {"name": "usedBy", "description": "is used by"}, "characteristics": [], "covers": ["usesData", "usesSample", "nope"]},
    {"name": "partOf", "description": "is a part of", "domain": "", "range": "", "inverse": None,
     "characteristics": ["transitive"], "covers": []},
    {"name": "badOne", "description": "", "domain": "NoSuchClass", "range": "", "inverse": None, "characteristics": []},
    {"name": "Task", "description": "clashes with a class", "domain": "", "range": "", "inverse": None, "characteristics": []}]}


def test_gap_run_adds_concepts_records_skips_and_does_not_propose_them_again():
    client = TestClient(A.app)
    sid = client.post("/api/session/create").json()["session_id"]
    s = A.sessions[sid]
    s["ontology"], s["iterations"] = base(), 1
    s["corpus"] = {"docs": [{"id": "d1", "name": "a.pdf", "card": {"title": "Tasks", "authors": "Doe, J.", "year": "2020"}},
                            {"id": "d2", "name": "b.pdf", "card": {"title": "Brush", "authors": "Roe, R.", "year": "2021"}}],
                   "inventory": gap_inventory()}
    E.check_oops = lambda turtle: []
    preview = client.post("/api/gaps/start", json={"session_id": sid, "kind": "concepts", "dry_run": True}).json()
    assert (preview["batches"], preview["items"], s["iterations"]) == (1, 3, 1) and "gap_run" not in s
    start = client.post("/api/gaps/start", json={"session_id": sid, "kind": "concepts"}).json()
    assert start["iteration"] == 2
    request = s["gap_run"]["batches"][0]["request"]
    assert '"Glyph"' in request and "existing class Dataset" in request and "Doe, 2020: Tasks" in request
    llm = FakeLLM({"summary": "added Glyph", "ops": [
                       {"op": "add_class", "name": "Glyph", "parent": "Dataset", "module": "Data",
                        "sources": ["Doe, 2020: Tasks", "Invented, 1999: Nothing"]}],
                   "skipped": [{"concept": "Brushing", "reason": "interaction technique, out of scope"},
                               {"concept": "Encode", "reason": "covered by encodesAttribute"}]})
    L.call_llm = llm
    d = client.post("/api/gaps/step", json={"session_id": sid, "llm_config": CFG, "index": 0}).json()
    glyph = next(c for c in d["ontology"]["classes"] if c["name"] == "Glyph")
    assert glyph["parent"] == "Dataset" and glyph["sources"] == ["Doe, 2020: Tasks"]     # invented citation dropped
    assert s["gap_decisions"][key("Brushing")].startswith("interaction technique")
    fin = client.post("/api/gaps/finish", json={"session_id": sid, "llm_config": CFG}).json()
    assert fin["summary"]["applied"] == 1 and len(fin["summary"]["skipped"]) == 2 and "gap_run" not in s
    assert s["feedback_log"][-1]["feedback"].startswith("Add the central concepts")
    again = client.post("/api/gaps/start", json={"session_id": sid, "kind": "concepts", "dry_run": True}).json()
    assert again["items"] == 0                    # Glyph exists now, Brushing and Encode were decided
    cov = concept_coverage(s["ontology"], s["corpus"]["inventory"], key, s.get("gap_decisions"))
    assert cov["central_missing"] == 0 and cov["central_decided"] == 2


def test_gap_run_hierarchy_batches_relations_and_taxonomies():
    s = {"ontology": base(), "corpus": {"docs": [{"id": "d1", "name": "a.pdf", "card": {"title": "T", "year": "2020"}}],
                                        "inventory": gap_inventory()}}
    s["ontology"]["classes"][1]["parent"] = None
    batches = IM.build_gap_batches(s, "hierarchy")
    texts = "\n".join(b["request"] for b in batches)
    assert "LowLevelTask is a kind of Task" in texts and "Taxonomy 'Tasks'" in texts
    s["gap_hierarchy_decisions"] = [P._norm("LowLevelTask is a kind of Task"), P._norm("Tasks")]
    assert IM.build_gap_batches(s, "hierarchy") == []


def test_reasoner_guard_corrects_or_reverts_packages_that_make_classes_unsatisfiable():
    if not java_available():
        print("   (skipped: no Java)")
        return
    client = TestClient(A.app)
    E.check_oops = lambda turtle: []
    bad = {"summary": "s", "ops": [{"op": "add_axiom", "type": "SubClassOf", "classes": ["LowLevelTask", "Dataset"]}]}
    undo = {"summary": "undo", "ops": [{"op": "remove_axiom", "type": "SubClassOf", "classes": ["LowLevelTask", "Dataset"]}]}
    for correction, expect_reverted, with_individual in (({"summary": "keep", "ops": []}, True, False),
                                                         (undo, False, False), ({"summary": "keep", "ops": []}, True, True)):
        sid = client.post("/api/session/create").json()["session_id"]
        s = A.sessions[sid]
        s["ontology"], s["iterations"] = base(), 1
        s["ontology"]["classes"][1]["parent"] = None           # gives the hierarchy action a relation to work on
        if not with_individual:
            s["ontology"]["individuals"] = []                 # otherwise the ontology becomes inconsistent, see below
        s["corpus"] = {"docs": [], "inventory": gap_inventory()}
        client.post("/api/gaps/start", json={"session_id": sid, "kind": "hierarchy"})
        # Task and Dataset are disjoint: LowLevelTask below both is unsatisfiable
        L.call_llm = FakeLLM({**bad, "ops": bad["ops"] + [{"op": "update_class", "name": "LowLevelTask", "parent": "Task"}]},
                             correction)
        d = client.post("/api/gaps/step", json={"session_id": sid, "llm_config": CFG, "index": 0}).json()
        rs = d["edit_report"]["reasoner"]
        # with an individual of LowLevelTask the whole ontology becomes inconsistent - also caught
        assert rs["new_unsatisfiable"] == (["(the ontology is inconsistent)"] if with_individual else ["LowLevelTask"])
        if with_individual:
            assert "INCONSISTENT" in L.call_llm.calls[1][-1]["content"]
        if expect_reverted:
            assert rs.get("reverted") and d["edit_report"]["applied"] == [] and s["ontology"]["classes"][1]["parent"] is None
        else:
            assert rs.get("corrected") and s["ontology"]["classes"][1]["parent"] == "Task"
            assert not any(a.get("type") == "SubClassOf" for a in s["ontology"]["axioms"])
        fin = client.post("/api/gaps/finish", json={"session_id": sid, "llm_config": CFG}).json()
        assert len(fin["summary"]["reverted"]) == (1 if expect_reverted else 0)


def test_gap_classes_are_linked_to_their_inventory_concepts():
    inv = gap_inventory()
    inv["concepts"].append({"id": "c7", "label": "Incomplete Knowledge", "variants": [], "papers": 2, "definition": "x",
                            "sources": []})
    inv["concepts"][4]["variants"] = ["linked brushing"]
    client = TestClient(A.app)
    sid = client.post("/api/session/create").json()["session_id"]
    s = A.sessions[sid]
    s["ontology"], s["iterations"] = base(), 1
    s["corpus"] = {"docs": [], "inventory": inv}
    E.check_oops = lambda turtle: []
    client.post("/api/gaps/start", json={"session_id": sid, "kind": "concepts"})
    L.call_llm = FakeLLM({"summary": "s", "ops": [
        # a variant is normalized to the concept's label; an invented concept is dropped
        {"op": "add_class", "name": "BrushAndLink", "parent": "Task", "module": "Tasks",
         "inventory_concepts": ["linked brushing", "Made-up concept"]},
        # the model forgot the link: the fallback finds it from the name
        {"op": "add_class", "name": "IncompleteKnowledgeEvent", "parent": "Task", "module": "Tasks"},
        # an existing class that already represents a concept is linked instead of duplicated
        {"op": "update_class", "name": "Dataset", "inventory_concepts": ["Glyph"]}],
        "skipped": [{"concept": "Encode", "reason": "a property"}]})
    d = client.post("/api/gaps/step", json={"session_id": sid, "llm_config": CFG, "index": 0}).json()
    by = {c["name"]: c for c in s["ontology"]["classes"]}
    assert by["BrushAndLink"]["inventory_concepts"] == ["Brushing"]
    assert by["IncompleteKnowledgeEvent"]["inventory_concepts"] == ["Incomplete Knowledge"]
    assert by["Dataset"]["inventory_concepts"] == ["Glyph"]
    assert d["edit_report"]["auto_linked"] == ["IncompleteKnowledgeEvent -> Incomplete Knowledge"]
    assert any("Made-up concept" in x for x in d["edit_report"]["dropped_provenance"])
    cov = concept_coverage(s["ontology"], inv, key, s.get("gap_decisions"))
    assert cov["central_missing"] == 0 and cov["central_decided"] == 1


def test_link_new_classes_only_links_unambiguous_matches():
    inv = {"concepts": [{"id": "a", "label": "Area", "variants": []},
                        {"id": "b", "label": "Data uncertainty", "variants": []},
                        {"id": "c", "label": "Model uncertainty", "variants": []}]}
    onto = {"classes": [{"name": "AreaMark"}, {"name": "DataUncertaintyEvent"}, {"name": "Uncertainty"}]}
    linked = IM.link_new_classes({"classes": []}, onto, ["Area", "Data uncertainty", "Model uncertainty"], inv)
    assert linked == ["DataUncertaintyEvent -> Data uncertainty"]   # "Area" is too short to match on its own


def test_upper_layer_is_created_once_and_reuses_existing_classes():
    onto = base()
    onto["classes"].append({"name": "Agent", "labels": {"en": "agent"}, "parent": None, "module": "Data",
                            "description": "responsible for an activity"})
    r = IM.ensure_upper_layer(onto, ["en", "de"])
    assert r["reused"] == ["Agent"]
    assert r["created"] == ["Process", "PhysicalObject", "InformationObject", "Specification", "Quality"]
    by = {c["name"]: c for c in onto["classes"]}
    assert by["Agent"]["module"] == "Data" and by["Agent"]["description"] == "responsible for an activity"   # untouched
    assert by["Specification"]["parent"] == "InformationObject" and by["Process"]["labels"] == {"en": "process", "de": "Prozess"}
    assert IM.ensure_upper_layer(onto, ["en"])["created"] == []
    disj = [a for a in onto["axioms"] if a["type"] == "DisjointClasses" and "Quality" in a["classes"]]
    assert len(disj) == 1 and set(disj[0]["classes"]) == {"Process", "Agent", "PhysicalObject", "InformationObject", "Quality"}
    assert sum(1 for m in onto["modules"] if m["name"] == IM.UPPER_MODULE) == 1
    # upper classes are traceable by design
    assert not set(traceability(onto, [], None, key)["untraceable"]) & {"Process", "Quality", "Specification"}


def test_upper_run_places_roots_and_records_what_does_not_fit():
    client = TestClient(A.app)
    sid = client.post("/api/session/create").json()["session_id"]
    s = A.sessions[sid]
    s["ontology"], s["iterations"] = base(), 1         # no inventory needed for this action
    E.check_oops = lambda turtle: []
    roots = [c["name"] for c in base()["classes"] if not c.get("parent")]
    preview = client.post("/api/gaps/start", json={"session_id": sid, "kind": "upper", "dry_run": True}).json()
    assert preview["items"] == len(roots) and not any(c["name"] == "Process" for c in s["ontology"]["classes"])
    start = client.post("/api/gaps/start", json={"session_id": sid, "kind": "upper"}).json()
    assert start["upper"]["created"][0] == "Process"
    request = s["gap_run"]["batches"][0]["request"]
    assert "Process, Agent, PhysicalObject, InformationObject and Quality are disjoint" in request
    assert "- Task (module" in request
    L.call_llm = FakeLLM({"summary": "Task is an abstract description.", "ops": [
        {"op": "update_class", "name": "Task", "parent": "Specification"}],
        "skipped": [{"item": r, "reason": "fits none"} for r in roots if r != "Task"]})
    client.post("/api/gaps/step", json={"session_id": sid, "llm_config": CFG, "index": 0})
    assert next(c for c in s["ontology"]["classes"] if c["name"] == "Task")["parent"] == "Specification"
    fin = client.post("/api/gaps/finish", json={"session_id": sid, "llm_config": CFG}).json()
    assert fin["summary"]["summaries"] == ["Task is an abstract description."]
    # empty upper classes are removed again; InformationObject stays because Specification (with Task) is below it
    assert set(fin["summary"]["upper"]["removed"]) == {"Process", "Agent", "PhysicalObject", "Quality"}
    names = {c["name"] for c in s["ontology"]["classes"]}
    assert {"InformationObject", "Specification"} <= names and not names & {"Process", "PhysicalObject"}
    assert not any(a["type"] == "DisjointClasses" and a.get("module") == IM.UPPER_MODULE for a in s["ontology"]["axioms"])
    assert IM.upper_candidates(s) == []                 # placed or deliberately left out
    assert s["feedback_log"][-1]["feedback"] == "Group the root classes under the upper layer"
    d = client.post("/api/evaluate", json={"session_id": sid, "llm_config": None}).json()
    assert d["upper_candidates"] == 0


def test_project_can_adjust_and_reset_its_upper_layer():
    client = TestClient(A.app)
    sid = client.post("/api/session/create").json()["session_id"]
    view = client.get(f"/api/session/{sid}").json()["project"]["context"]
    assert view["upper_layer_default"] and [x["name"] for x in view["upper_layer"]][:3] == ["Process", "Agent", "PhysicalObject"]
    save = lambda body: client.post("/api/context/save", json={"session_id": sid, **body})
    layer = [{"name": "Process", "parent": "", "disjoint": True, "definition": "happens"},
             {"name": "Ingredient", "parent": "", "disjoint": True, "definition": "goes into a dish"},
             {"name": "Spice", "parent": "Ingredient", "disjoint": True, "definition": "for flavour"}]
    d = save({"upper_layer": layer}).json()
    assert not d["upper_layer_default"] and d["upper_layer"][2]["disjoint"] is False      # only top level is disjoint
    assert d["upper_layer"][0]["labels"]["de"] == "Prozess" and d["upper_layer"][1]["labels"] == {}
    for bad in ([{"name": "1x", "definition": ""}], [{"name": "A", "parent": "Nope"}],
                [{"name": "A", "parent": "B"}, {"name": "B", "parent": "A"}], [{"name": "A"}, {"name": "a"}], []):
        assert save({"upper_layer": bad}).status_code == 400
    s = A.sessions[sid]
    s["ontology"], s["iterations"] = base(), 1
    s["context"]["conventions"]["label_languages"] = "en"
    request = IM.build_gap_batches(s, "upper")[0]["request"]
    assert "- Spice (below Ingredient): for flavour" in request and "Process and Ingredient are disjoint" in request
    assert "PhysicalObject" not in request
    IM.ensure_upper_layer(s["ontology"], ["en"], IM.upper_layer_of(s))
    by = {c["name"]: c for c in s["ontology"]["classes"]}
    assert by["Ingredient"]["labels"] == {"en": "ingredient"} and by["Spice"]["parent"] == "Ingredient"
    assert save({"reset_upper_layer": True}).json()["upper_layer_default"]


def test_property_vocabulary_is_proposed_cleaned_and_must_be_approved():
    client = TestClient(A.app)
    sid = client.post("/api/session/create").json()["session_id"]
    s = A.sessions[sid]
    s["ontology"], s["iterations"] = property_onto(), 1
    L.call_llm = FakeLLM(VOCAB)
    d = client.post("/api/properties/propose", json={"session_id": sid, "llm_config": CFG}).json()
    v = d["property_vocab"]
    assert [r["name"] for r in v["relations"]] == ["uses", "partOf"] and v["status"] == "proposed"
    assert v["relations"][0]["covers"] == ["usesData", "usesSample"] and len(v["dropped"]) == 2   # unknown names dropped
    prompt = L.call_llm.calls[0][-1]["content"]
    assert "usesSample (module Tasks): LowLevelTask -> Dataset, inverse sampleUsedBy" in prompt
    assert "sampleUsedBy (module" not in prompt                         # one direction per inverse pair
    # not approved yet: the run cannot start
    assert client.post("/api/gaps/start", json={"session_id": sid, "kind": "properties"}).status_code == 400
    save = lambda body: client.post("/api/properties/vocab", json={"session_id": sid, **body})
    bad = [dict(v["relations"][0], characteristics=["transitive", "functional"])]
    assert "not allowed in OWL 2 DL" in save({"relations": bad}).json()["detail"]
    assert save({"relations": [dict(v["relations"][1], characteristics=["symmetric"], inverse={"name": "hasPart"})]}).status_code == 400
    assert save({"approve": True}).json()["property_vocab"]["status"] == "approved"
    # an edit after the approval needs a new approval
    edited = save({"relations": v["relations"][:1]}).json()["property_vocab"]
    assert edited["status"] == "proposed" and len(edited["relations"]) == 1
    assert save({"discard": True}).json()["property_vocab"] is None and "property_vocab" not in s


def test_property_consolidation_run_merges_places_keeps_and_retests_cqs():
    client = TestClient(A.app)
    sid = client.post("/api/session/create").json()["session_id"]
    s = A.sessions[sid]
    s["ontology"], s["iterations"] = property_onto(), 1
    s["momo"]["competency_questions"] = [{"question": "Which samples does a task use?"}]
    # the team's query used usesSample, which is about to be merged into the core relation `uses`
    q = "PREFIX : <https://example.org/t#> SELECT ?d WHERE { ?t :usesSample ?d }"
    s["cq_test_report"] = {"iteration": 1, "result": {"tests": [{"question": "Which samples does a task use?",
        "status": "passed", "sparql": q, "terms": ["usesSample"]}], "passed": 1, "total": 1,
        "sample_data": ":t1 a :LowLevelTask ; :usesSample :d1 . :d1 a :Dataset ."}}
    E.check_oops = lambda turtle: []
    L.call_llm = FakeLLM(VOCAB)
    client.post("/api/properties/propose", json={"session_id": sid, "llm_config": CFG})
    client.post("/api/properties/vocab", json={"session_id": sid, "approve": True})
    preview = client.post("/api/gaps/start", json={"session_id": sid, "kind": "properties", "dry_run": True}).json()
    assert preview["items"] == 3                       # usesData, usesSample, describesTask (one per inverse pair)
    start = client.post("/api/gaps/start", json={"session_id": sid, "kind": "properties"}).json()
    by = {p["name"]: p for p in s["ontology"]["properties"]}
    assert by["uses"]["inverse_of"] == "usedBy" and by["usedBy"]["domain"] == "Dataset"
    assert by["partOf"]["characteristics"] == ["transitive"] and not start["core"]["rejected"]
    request = s["gap_run"]["batches"][0]["request"]
    assert "- uses: Task -> Dataset, inverse usedBy: makes use of" in request and "- partOf: (any) -> (any) [transitive]" in request
    L.call_llm = FakeLLM({"summary": "s", "ops": [
        {"op": "merge_property", "name": "usesSample", "into": "uses"},
        {"op": "update_property", "name": "usesData", "sub_property_of": "uses"},
        {"op": "merge_property", "name": "describesTask", "into": "uses"}],      # Dataset is not below Task: rejected
        "skipped": [{"item": "describesTask", "reason": "no core relation fits"}]},
        {"summary": "retry", "ops": []},
        # the CQ re-test: the old query fails on the merged property, the model finds no new one
        {"sample_data": "", "tests": [{"cq": 1, "sparql": None, "missing": "nothing"}]})
    d = client.post("/api/gaps/step", json={"session_id": sid, "llm_config": CFG, "index": 0}).json()
    by = {p["name"]: p for p in s["ontology"]["properties"]}
    assert "usesSample" not in by and "sampleUsedBy" not in by and by["usesData"]["sub_property_of"] == "uses"
    assert "sub_property_of" not in by["usedByTask"]     # OWL entails usedByTask below usedBy; not written twice
    assert "describesTask" in by and any("is not below" in r["reason"] for r in d["edit_report"]["rejected"])
    assert s["gap_property_decisions"] == {"describesTask": {"item": "describesTask", "reason": "no core relation fits"}}
    fin = client.post("/api/gaps/finish", json={"session_id": sid, "llm_config": CFG}).json()
    sm = fin["summary"]
    assert sm["core"]["before"]["relations"] == 3 and sm["core"]["after"]["object_properties"] == 6
    # the old query and its data were translated from usesSample to uses: it still passes, without a model call
    assert sm["cq"]["regressions"] == [] and (sm["cq"]["passed_before"], sm["cq"]["passed_after"]) == (1, 1)
    assert sm["cq"]["translated"] >= 2 and ":uses " in fin["cq_tests"]["tests"][0]["sparql"]
    assert len(L.call_llm.replies) == 1                # the prepared CQ reply was not needed
    assert s["property_vocab"]["status"] == "applied"
    assert client.post("/api/gaps/start", json={"session_id": sid, "kind": "properties", "dry_run": True}).json()["items"] == 0
    m = structural_metrics(s["ontology"])
    assert (m["relations"], m["top_level_relations"], m["properties_with_superproperty"]) == (4, 3, 1)
    assert m["top_level_relations_per_class"] == round(3 / m["classes"], 2)


def test_the_core_vocabulary_size_follows_the_ontology_size():
    # DECISIONS 130: 0.15-0.25 core relations per class, at least 3 to 5; VA with 264 classes as before about 40-70
    assert IM.core_relations_range(264) == (40, 66)
    assert IM.core_relations_range(18) == (3, 5)
    assert IM.core_relations_range(0) == (3, 5)
    system = IM.build_property_vocab_prompt({"ontology": property_onto()})[0]["content"]
    assert "about 3 to 5, fewer if fewer are needed" in system and "{size}" not in system


def test_core_relation_with_an_existing_name_drops_the_old_inverse():
    onto = property_onto()
    vocab = IM.clean_property_vocab([{"name": "usesData", "domain": "", "range": "", "inverse": None},
                                    {"name": "usesSample", "domain": "", "range": "",
                                     "inverse": {"name": "isSampleOf", "description": ""}}], onto)
    IM.ensure_core_module(onto)
    new, rep = A.apply_edits(onto, IM.core_relation_ops(vocab, onto))
    by = {p["name"]: p for p in new["properties"]}
    assert not rep["rejected"], rep["rejected"]
    assert by["isSampleOf"]["module"] == IM.CORE_MODULE and by["usesData"]["module"] == IM.CORE_MODULE
    assert by["isSampleOf"]["labels"] == {"en": "is sample of"}         # lowercase, like the model's labels
    # the narrow inverse usedByTask (Dataset -> Task) would retype every subject of the widened usesData
    assert by["usesData"]["inverse_of"] is None and by["usedByTask"]["inverse_of"] is None
    assert by["usesSample"]["inverse_of"] == "isSampleOf" and by["isSampleOf"]["inverse_of"] == "usesSample"
    assert by["sampleUsedBy"]["inverse_of"] is None and by["usesSample"]["domain"] is None


def test_align_run_links_terms_and_reasons_with_the_vocabulary():
    client = TestClient(A.app)
    sid, s = align_session(client)
    cands = {c["name"]: [t["ref"] for t in c["candidates"]] for c in V.align_candidates(s)}
    assert cands["AnalysisActivity"][0] == "pl:Activity"                    # head word of the own name
    assert cands["isGeneratedBy"] == ["pl:wasGeneratedBy"]                  # same words without is/was/by
    E.check_oops = lambda turtle: []
    start = client.post("/api/gaps/start", json={"session_id": sid, "kind": "align"}).json()
    request = s["gap_run"]["batches"][0]["request"]
    assert "- pl: " in request and "candidate pl:wasGeneratedBy (object)" in request
    L.call_llm = FakeLLM({"summary": "s", "ops": [
        {"op": "update_property", "name": "isGeneratedBy", "sub_property_of": "pl:wasGeneratedBy"},
        {"op": "add_axiom", "type": "SubClassOf", "classes": ["Dataset", "pl:Entity"]},
        {"op": "add_axiom", "type": "SubClassOf", "classes": ["Task", "pl:Activity"]}],
        "skipped": [{"item": "AnalysisActivity", "reason": "covered through Task"}]})
    d = client.post("/api/gaps/step", json={"session_id": sid, "llm_config": CFG, "index": 0}).json()
    assert not d["edit_report"]["rejected"], d["edit_report"]["rejected"]
    assert list(s["gap_align_decisions"]) == ["AnalysisActivity"]
    assert s["gap_align_decisions"]["AnalysisActivity"]["reason"] == "covered through Task"
    turtle = O.ontology_to_turtle(s["ontology"], [], P.session_prefixes(s))
    assert "@prefix pl: <https://w3id.org/pl#>" in turtle and "rdfs:subPropertyOf pl:wasGeneratedBy" in turtle
    assert "pl:wasGeneratedBy a owl:ObjectProperty ." in turtle and ":Dataset rdfs:subClassOf pl:Entity" in turtle
    assert V.align_candidates(s) == []                                       # all linked or decided
    m = structural_metrics(s["ontology"])
    assert m["external_links"] >= 3 and m["linked_vocabularies"] == ["pl"]
    # the reasoner sees the vocabulary's disjointness: a class below both pl:Activity and pl:Entity is unsatisfiable
    reasoning = V.turtle_for_reasoning(s, turtle)
    assert "pl:Activity owl:disjointWith pl:Entity ." in reasoning and "pl:Plan" not in reasoning   # only used terms
    if java_available():
        onto = copy.deepcopy(s["ontology"])
        onto["axioms"].append({"type": "SubClassOf", "classes": ["LowLevelTask", "pl:Entity"]})
        t2 = V.turtle_for_reasoning(s, O.ontology_to_turtle(onto, [], P.session_prefixes(s)))
        assert reasoner_check(t2)["ontology"]["consistent"] is False        # taskExample is a LowLevelTask
        onto["individuals"] = []
        t3 = V.turtle_for_reasoning(s, O.ontology_to_turtle(onto, [], P.session_prefixes(s)))
        assert reasoner_check(t3)["ontology"]["unsatisfiable"] == ["LowLevelTask"]
        assert reasoner_check(reasoning)["ontology"] == {"consistent": True, "unsatisfiable": []}


def test_decisions_keep_their_reasons_and_can_be_reconsidered_per_action():
    client = TestClient(A.app)
    sid, s = align_session(client)
    s["gap_upper_decisions"] = ["Dataset"]                                     # an older project: only a list
    s["gap_hierarchy_decisions"] = {"lowleveltaskisakindoftask": {"item": "LowLevelTask is a kind of Task",
                                                                  "reason": "already so"}}
    E.check_oops = lambda turtle: []
    client.post("/api/gaps/start", json={"session_id": sid, "kind": "align"})
    L.call_llm = FakeLLM({"summary": "s", "ops": [],
                          "skipped": [{"item": "AnalysisActivity", "reason": "too specific"},
                                      {"item": "isGeneratedBy", "reason": "different direction"}]})
    client.post("/api/gaps/step", json={"session_id": sid, "llm_config": CFG, "index": 0})
    client.post("/api/gaps/finish", json={"session_id": sid, "llm_config": CFG})
    rep = client.post("/api/evaluate", json={"session_id": sid, "llm_config": None}).json()
    d = rep["decisions"]
    assert d["upper"] == [{"key": "Dataset", "item": "Dataset", "reason": ""}]           # converted, no reason known
    assert d["hierarchy"][0]["item"] == "LowLevelTask is a kind of Task"
    assert {x["key"]: x["reason"] for x in d["align"]} == {"AnalysisActivity": "too specific",
                                                             "isGeneratedBy": "different direction"}
    assert rep["align_candidates"] == 0
    r = client.post("/api/gaps/reconsider", json={"session_id": sid, "kind": "align", "keys": ["isGeneratedBy"]}).json()
    assert r["removed"] == 1 and r["evaluation"]["align_candidates"] == 1
    assert [x["key"] for x in r["evaluation"]["decisions"]["align"]] == ["AnalysisActivity"]
    r = client.post("/api/gaps/reconsider", json={"session_id": sid, "kind": "upper", "all": True}).json()
    assert r["removed"] == 1 and r["evaluation"]["decisions"]["upper"] == []
    assert client.post("/api/gaps/reconsider", json={"session_id": sid, "kind": "nope"}).status_code == 400


def test_second_consolidation_keeps_links_of_existing_core_relations():
    onto = property_onto()
    vocab = IM.clean_property_vocab([{"name": "uses", "domain": "Task", "range": "Dataset",
                                     "inverse": {"name": "usedBy", "description": ""}}], onto)
    IM.ensure_core_module(onto)
    first, rep = A.apply_edits(onto, IM.core_relation_ops(vocab, onto))
    assert not rep["rejected"]
    for p in first["properties"]:
        if p["name"] == "uses":
            p["sub_property_of"] = "pl:uses"                  # e.g. linked to a vocabulary by the align action
    second, rep = A.apply_edits(first, IM.core_relation_ops(vocab, first))
    by = {p["name"]: p for p in second["properties"]}
    assert not rep["rejected"] and by["uses"]["sub_property_of"] == "pl:uses" and by["uses"]["inverse_of"] == "usedBy"


def test_an_answer_without_ops_but_with_decisions_changes_nothing():
    client = TestClient(A.app)
    sid, s = align_session(client)
    E.check_oops = lambda turtle: []
    client.post("/api/gaps/start", json={"session_id": sid, "kind": "align"})
    before = copy.deepcopy(s["ontology"])
    # the model found nothing to link and answered without an "ops" field - this used to end in HTTP 500
    L.call_llm = FakeLLM({"summary": "No candidate fits.",
                          "skipped": [{"item": "AnalysisActivity", "reason": "different meaning"}]})
    r = client.post("/api/gaps/step", json={"session_id": sid, "llm_config": CFG, "index": 0})
    assert r.status_code == 200 and r.json()["edit_report"]["operations"] == 0
    assert s["ontology"]["classes"] == before["classes"]
    assert s["gap_align_decisions"]["AnalysisActivity"]["reason"] == "different meaning"


def test_provider_errors_become_clear_http_errors():
    cfg = A.LLMConfig(provider="rwthgpt", api_key="x", model="gpt-6-sol")
    def err(name, status=None, message="boom"):
        e = type(name, (Exception,), {})(message)
        e.status_code, e.message = status, message
        return e
    cases = [(err("RateLimitError", 429), 429), (err("APIStatusError", 403, "Message limit reached for this model"), 429),
             (err("AuthenticationError", 401), 401), (err("APITimeoutError"), 504), (err("APIStatusError", 500), 502)]
    for ex, code in cases:
        mapped = L._provider_error(cfg, ex)
        assert mapped is not None and mapped.status_code == code, (type(ex).__name__, mapped and mapped.status_code)
    assert "choose another model" in L._provider_error(cfg, cases[1][0]).detail
    assert L._provider_error(cfg, ValueError("bad json")) is None              # our own errors stay as they are
    real, real_sleep, waits = L._call_llm, L._sleep, []
    L._call_llm = lambda *a, **k: (_ for _ in ()).throw(err("RateLimitError", 429, "quota exceeded"))
    L._sleep = waits.append                      # the waits at a rate limit (DECISIONS 108), without waiting
    try:
        try:
            REAL_CALL_LLM(cfg, [{"role": "user", "content": "x"}])
            assert False
        except HTTPException as ex:
            assert ex.status_code == 429 and "gpt-6-sol" in ex.detail
        # an improvement action passes the 429 on, so the browser can stop the run
        client = TestClient(A.app)
        sid, s = align_session(client)
        E.check_oops = lambda turtle: []
        client.post("/api/gaps/start", json={"session_id": sid, "kind": "align"})
        L.call_llm = REAL_CALL_LLM
        r = client.post("/api/gaps/step", json={"session_id": sid, "llm_config": CFG, "index": 0})
        assert r.status_code == 429 and waits[:3] == [15, 30, 60]
    finally:
        L._call_llm, L._sleep = real, real_sleep


def test_upper_disjointness_text_follows_the_classes():
    onto = base()
    IM.ensure_upper_layer(onto, ["en"])
    ax = next(a for a in onto["axioms"] if a.get("module") == IM.UPPER_MODULE)
    assert ax["natural_language"] == ("Nothing is at the same time a process, an agent, a physical object, "
                                      "an information object and a quality.")
    onto["classes"][0]["parent"] = "Specification"                         # Task below Specification
    IM.remove_unused_upper(onto, ["Process", "PhysicalObject", "InformationObject", "Specification", "Quality"])
    ax = next(a for a in onto["axioms"] if a.get("module") == IM.UPPER_MODULE)
    assert "physical object" not in ax["natural_language"] and "an information object" in ax["natural_language"]


def test_an_upper_class_named_in_an_axiom_is_kept():
    onto = base()
    IM.ensure_upper_layer(onto, ["en"])
    onto["axioms"].append({"type": "DisjointClasses", "classes": ["Dataset", "Quality"], "module": "Data"})
    IM.remove_unused_upper(onto, ["Process", "PhysicalObject", "InformationObject", "Specification", "Quality"])
    names = {c["name"] for c in onto["classes"]}
    assert "Quality" in names and "PhysicalObject" not in names
    ax = next(a for a in onto["axioms"] if a.get("module") == IM.UPPER_MODULE)
    assert "Quality" in ax["classes"] and "PhysicalObject" not in ax["classes"]


def test_a_reasoner_that_does_not_run_leaves_the_package_unchecked():
    old = IM._unsatisfiable
    IM._unsatisfiable = lambda turtle, session=None: None
    try:
        onto = base()
        r = IM._reasoner_guard({}, CFG, {"unsat_baseline": []}, onto, onto, "ttl", "label", [])
        assert r[0] is onto and r[2] == {"checked": False, "reason": "the reasoner could not run"}
    finally:
        IM._unsatisfiable = old


def test_restriction_run_offers_loosely_connected_class_pairs_and_records_decisions():
    client = TestClient(A.app)
    sid = client.post("/api/session/create").json()["session_id"]
    s = A.sessions[sid]
    s["ontology"], s["iterations"] = base(), 1
    s["ontology"]["classes"].append({"name": "Glyph", "labels": {"en": "Glyph"}, "description": "", "parent": None,
                                     "module": "Data"})
    E.check_oops = lambda turtle: []
    # an edit merged usesSample (LowLevelTask -> Dataset) into usesData: the class pair is recorded
    L.call_llm = FakeLLM({"summary": "s", "ops": [
        {"op": "add_property", "name": "usesSample", "type": "ObjectProperty", "domain": "LowLevelTask", "range": "Dataset"},
        {"op": "merge_property", "name": "usesSample", "into": "usesData"}]})
    s["ontology"], _ = E.edit_ontology(s, CFG, s["ontology"], "merge", "test")
    assert s["merge_records"] == [{"property": "usesSample", "into": "usesData", "type": "ObjectProperty",
                                   "domain": "LowLevelTask", "range": "Dataset"}]
    s["corpus"] = {"docs": [], "inventory": {"themes": [], "taxonomies": [], "concepts": [
        {"id": "c1", "label": "dataset", "variants": [], "papers": 2, "sources": []},
        {"id": "c2", "label": "glyph", "variants": [], "papers": 2, "sources": []}], "relations": [
        {"subject": "dataset", "relation": "is shown by", "object": "glyph", "subject_id": "c1", "object_id": "c2",
         "docs": ["d1", "d2"]},
        {"subject": "glyph", "relation": "encodes", "object": "dataset", "subject_id": "c2", "object_id": "c1",
         "docs": ["d1"]}]}}                                                     # one paper only: not offered
    cands = IM.restriction_candidates(s)
    assert [c["item"] for c in cands] == ["LowLevelTask -> Dataset", "Dataset -> Glyph"]   # module order
    assert cands[0]["properties"] == ["usesData"]
    d = client.post("/api/gaps/start", json={"session_id": sid, "kind": "restrictions"}).json()
    assert (d["batches"], d["items"]) == (1, 2)
    L.call_llm = FakeLLM({"summary": "one holds", "ops": [
        {"op": "add_restriction", "class": "LowLevelTask", "property": "usesData", "kind": "some", "value": "Dataset"}],
        "skipped": [{"item": "Dataset -> Glyph", "reason": "not every dataset is shown"}]})
    step = client.post("/api/gaps/step", json={"session_id": sid, "llm_config": CFG, "index": 0}).json()
    prompt = L.call_llm.calls[0][-1]["content"]
    assert "merged property usesSample (into usesData)" in prompt and "'dataset is shown by glyph' (2 papers)" in prompt
    assert step["edit_report"]["applied"][0]["summary"] == "added restriction LowLevelTask SubClassOf usesData some Dataset"
    fin = client.post("/api/gaps/finish", json={"session_id": sid, "llm_config": CFG}).json()
    assert fin["summary"]["applied"] == 1 and len(fin["ontology"]["restrictions"]) == 1
    assert "owl:someValuesFrom :Dataset" in fin["turtle"]
    # decided or done: not offered again; the evaluation counts what is left for the repair tool
    assert P.decision_store(s, "restrictions")["Dataset -> Glyph"]["reason"] == "not every dataset is shown"
    assert IM.restriction_candidates(s) == []
    ev = client.post("/api/evaluate", json={"session_id": sid, "llm_config": None}).json()
    assert ev["restriction_candidates"] == 0 and ev["metrics"]["restrictions"] == 1
