"""Tests for the one generation path (PLAN.md phase 2, DECISIONS 84): plan, then module by module - also without a
literature corpus and without key notions. Run with `pytest tests/test_generation.py`."""
import json


import app as A
import editing as E
import generation as G
import llm as L
import project as P
import corpus as C
from fastapi.testclient import TestClient
from helpers import CFG

client = TestClient(A.app)
USE_CASE = "Describe wines, the grapes they are made from and the dishes they go with."
CQS = ["Which wines are made from Merlot?", "Which wine goes with grilled fish?"]


class RoutedLLM:
    """Answers the plan call, the vocabulary-link call and each module call by what the prompt asks for."""
    def __init__(self, plan, modules, links=None, complete=None, after=None, hierarchy=None, core=None, missing=None):
        self.plan, self.modules, self.links, self.calls = plan, modules, links or {"links": []}, []
        self.missing = missing or {"summary": "", "ops": [], "skipped": []}
        self.complete = complete or {"assign": [], "excluded": []}
        self.after = after or {"links": [], "none": []}
        self.hierarchy = hierarchy or {"relations": []}
        self.core = core or {"relations": []}

    def __call__(self, cfg, messages, effort="high"):
        self.calls.append(messages)
        L._record_usage(100, 10)
        text = messages[-1]["content"]
        if "\n\nPlan the" in text:
            return json.dumps(self.plan)
        if "**Planned classes and candidate terms:**" in text:
            return json.dumps(self.links)
        if "**Central concepts without a place in the plan**" in text:
            return json.dumps(self.complete)
        if "**Own terms and candidate terms:**" in text:
            return json.dumps(self.after)
        if "**Relations:**" in text:
            return json.dumps(self.hierarchy)
        if "**Relations of the modules:**" in text:
            return json.dumps(self.core)
        if "but not yet represented in the ontology" in text:      # central concepts missing after the modules
            return json.dumps(self.missing)
        name = text.split("**THIS module:** ", 1)[1].split()[0]
        reply = self.modules[name]
        if isinstance(reply, Exception):
            raise reply
        return json.dumps(reply)

    def prompt(self, module=None):
        for m in self.calls:
            text = m[-1]["content"]
            if (module is None and "\n\nPlan the" in text) or (module and f"**THIS module:** {module}" in text):
                return m
        raise AssertionError(f"no call for {module or 'the plan'}")


def wine_project(notions=()):
    sid = client.post("/api/session/create").json()["session_id"]
    s = A.sessions[sid]
    s["momo"] = {"use_case": USE_CASE, "data_sources": "", "patterns": [],
                 "competency_questions": [{"question": q} for q in CQS], "key_notions": list(notions)}
    s["data_preview"] = "wines.csv: 120 rows; columns name (text), grape (text), colour (red|white|rose), vintage (year)"
    return sid, s


def module(name, classes, properties=()):
    return {"module": {"name": name, "documentation": f"The {name} module."},
            "classes": [{"name": c, "labels": {"en": c}, "description": f"A {c.lower()}.", "parent": p}
                        for c, p in classes],
            "properties": list(properties), "individuals": [], "axioms": []}


def generate(sid, extra=""):
    E.check_oops = lambda turtle: []
    return client.post("/api/generate", json={"session_id": sid, "llm_config": CFG,
                                              "domain_description": USE_CASE + extra})


def test_without_literature_and_key_notions_the_plan_proposes_the_modules():
    sid, s = wine_project()
    L.call_llm = RoutedLLM(
        {"ontology_name": "Wine Ontology", "summary": "s", "license": "",
         "modules": [{"name": "wine", "description": "wines and their properties",
                      "classes": [{"name": "Wine", "note": "an alcoholic drink made from grapes"},
                                  {"name": "red wine", "note": "a wine made from dark grapes"}],
                      "other": [{"term": "vintage", "as": "property", "hint": "a year"}]},
                     {"name": "Food", "description": "dishes", "classes": [{"name": "Dish", "note": "a prepared food"}]},
                     {"name": "Wine", "classes": [{"name": "Sparkling"}]}]},          # same module again: merged
        {"Wine": module("Wine", [("Wine", None), ("RedWine", "Wine")], [
            {"name": "goesWith", "type": "ObjectProperty", "domain": "Wine", "range": "Dish", "labels": {"en": "goes with"}},
            {"name": "relatesTo", "type": "ObjectProperty", "domain": "any", "range": "(any)"}]),   # copied from the core list
         "Food": {**module("Food", [("Dish", None)]), "axioms": [
             {"type": "SubClassOf", "classes": ["Dish", "isPartOf some Meal"]},          # a restriction: left out
             {"type": "DisjointClasses", "classes": ["Dish", "Wine"]}]}})
    r = generate(sid, "\n\nAdditional requirements:\nLabels in English.")
    assert r.status_code == 200, r.text
    d = r.json()
    plan = L.call_llm.prompt()
    assert "Divide the domain into 3-8 modules" in plan[0]["content"] and "Concept inventory" not in plan[-1]["content"]
    assert "Additional requirements:\nLabels in English." in plan[-1]["content"]           # the generation step's text
    assert "wines.csv: 120 rows" in plan[-1]["content"] and "Which wines are made from Merlot?" in plan[-1]["content"]
    wine = L.call_llm.prompt("Wine")[-1]["content"]
    assert "- planned as: a wine made from dark grapes" in wine and "wines.csv: 120 rows" in wine
    assert "- vintage -> as property (a year)" in wine and "**Food:** " not in wine and "- Food: Food, Dish" in wine
    assert [m["name"] for m in d["ontology"]["modules"]] == ["Wine", "Food"]
    names = {c["name"]: c for c in d["ontology"]["classes"]}
    assert names["RedWine"]["parent"] == "Wine" and names["Sparkling"]["module"] == "Wine"
    assert names["Food"]["module"] == "Food"                   # the key notion of a proposed module is a class too
    rel = next(p for p in d["ontology"]["properties"] if p["name"] == "relatesTo")
    assert rel["domain"] is None and rel["range"] is None and ":(any)" not in d["turtle"]
    assert [a["classes"] for a in d["ontology"]["axioms"]] == [["Dish", "Wine"]] and "some Meal" not in d["turtle"]
    assert d["modular_report"]["invalid_axioms"] == ["SubClassOf(Dish, isPartOf some Meal) in Food"]
    rep = d["modular_report"]
    assert rep["modules_proposed"] and not rep["inventory"] and rep["modules"] == 2


def test_without_literature_the_key_notions_are_the_modules():
    sid, s = wine_project([{"name": "Wine", "description": "drinks"}, {"name": "Grape", "description": "varieties"}])
    L.call_llm = RoutedLLM(
        {"ontology_name": "Wine", "modules": [
            {"name": "Wine", "classes": [{"name": "Wine", "note": "a drink"}]},
            {"name": "Region", "classes": [{"name": "Region"}]},                      # not a key notion: ignored
            {"name": "Grape", "classes": [{"name": "GrapeVariety", "note": "a cultivar of Vitis vinifera"}]}]},
        {"Wine": module("Wine", [("Wine", None)]), "Grape": RuntimeError("module failed")})
    d = generate(sid).json()
    assert "The modules are fixed: one per key notion" in L.call_llm.prompt()[0]["content"]
    assert "**Modules (key notions):**\n- Wine: drinks\n- Grape: varieties" in L.call_llm.prompt()[-1]["content"]
    names = {c["name"]: c for c in d["ontology"]["classes"]}
    assert "Region" not in names
    # the Grape module failed: its planned classes come from the plan, with the note as description
    assert names["GrapeVariety"]["description"] == "a cultivar of Vitis vinifera" and names["Grape"]["module"] == "Grape"
    assert d["modular_report"]["module_errors"][0]["module"] == "Grape" and not d["modular_report"]["modules_proposed"]


def test_empty_key_notions_are_not_key_notions():
    sid, s = wine_project()
    r = client.post("/api/momo/save", json={"session_id": sid, "use_case": USE_CASE, "data_sources": "",
                                            "competency_questions": [{"question": CQS[0]}, {"question": " "}],
                                            "key_notions": [{"name": "  ", "description": ""}], "patterns": []})
    assert s["momo"]["key_notions"] == [] and len(s["momo"]["competency_questions"]) == 1, r.text
    s["momo"]["key_notions"] = [{"name": "", "description": "a row saved by an older version"}]
    L.call_llm = RoutedLLM({}, {})
    r = client.post("/api/momo/suggest-patterns", json={"session_id": sid, "llm_config": CFG})
    assert r.status_code == 400 and "named key notions" in r.json()["detail"] and not L.call_llm.calls


def test_without_literature_the_plan_asks_for_expected_notions_and_named_individuals():
    sid, s = wine_project([{"name": ""}])
    plan, _ = G.build_plan_prompt(s, [], "")
    assert "a domain expert would expect" in plan["content"] and "as an individual" in plan["content"]
    assert "Divide the domain into 3-8 modules" in plan["content"]
    assert "a domain expert would expect" not in G._plan_system({"concepts": [], "themes": []}, True)


def test_subclass_axioms_that_repeat_the_hierarchy_are_left_out():
    sid, s = wine_project([{"name": "Wine"}])
    wine = module("Wine", [("Wine", None), ("RedWine", "Wine"), ("Grape", None)])
    wine["axioms"] = [{"type": "SubClassOf", "classes": ["RedWine", "Wine"]},           # repeats parent
                      {"type": "SubClassOf", "classes": ["Grape", "Wine"]},             # says something new
                      {"type": "DisjointClasses", "classes": ["Wine", "Grape"]}]
    L.call_llm = RoutedLLM({"ontology_name": "W", "summary": "s", "license": "", "modules": [
        {"name": "Wine", "classes": [{"name": "Wine", "note": "n"}, {"name": "RedWine", "note": "n"}]}]}, {"Wine": wine})
    d = generate(sid).json()
    assert [a["classes"] for a in d["ontology"]["axioms"]] == [["Grape", "Wine"], ["Wine", "Grape"]]
    assert d["modular_report"]["redundant_axioms"] == 1


def test_modules_write_class_restrictions_that_are_checked_and_tested_with_the_reasoner():
    from ontology_evaluation import java_available
    sid, s = wine_project([{"name": "Wine"}])
    wine = module("Wine", [("Wine", None), ("Grape", None), ("Dish", None)], [
        {"name": "madeFrom", "type": "ObjectProperty", "domain": "Wine", "range": "Grape"},
        {"name": "goesWith", "type": "ObjectProperty", "domain": None, "range": None}])
    wine["axioms"] = [{"type": "DisjointClasses", "classes": ["Grape", "Dish"]}]
    wine["restrictions"] = [
        {"class": "Wine", "property": "madeFrom", "kind": "some", "value": "Grape"},
        {"class": "Wine", "property": "madeFrom", "kind": "min", "n": "1", "value": "Grape"},
        {"class": "Grape", "property": "madeFrom", "kind": "some", "value": "Grape"},       # outside the domain
        {"class": "Wine", "property": "madeFrom", "kind": "some", "value": "Cork"},         # no such class
        # together unsatisfiable, since Grape and Dish are disjoint
        {"class": "Dish", "property": "goesWith", "kind": "some", "value": "Grape"},
        {"class": "Dish", "property": "goesWith", "kind": "only", "value": "Dish"}]
    L.call_llm = RoutedLLM({"ontology_name": "W", "summary": "s", "license": "", "modules": [
        {"name": "Wine", "classes": [{"name": "Wine", "note": "n"}, {"name": "Grape", "note": "n"},
                                     {"name": "Dish", "note": "n"}]}]}, {"Wine": wine})
    d = generate(sid).json()
    assert "KEY RESTRICTIONS" in L.call_llm.prompt("Wine")[0]["content"]
    rs = d["modular_report"]["restrictions"]
    assert (rs["written"], rs["added"], len(rs["rejected"])) == (6, 4, 2)
    assert any("not below the domain" in x for x in rs["rejected"]) and any("Cork" in x for x in rs["rejected"])
    labels = lambda: sorted(f"{r['class']} {r['property']} {r['kind']} {r['value']}" for r in d["ontology"]["restrictions"])
    if not java_available():
        assert not rs["reasoner"]["checked"] and len(d["ontology"]["restrictions"]) == 4
        return
    assert rs["reasoner"]["checked"] and sorted(rs["reasoner"]["removed"]) == [
        "Dish SubClassOf goesWith only Dish", "Dish SubClassOf goesWith some Grape"]
    assert labels() == ["Wine madeFrom min Grape", "Wine madeFrom some Grape"] and not rs["reasoner"]["still_unsatisfiable"]
    assert d["ontology"]["restrictions"][0]["module"] == "Wine"


def test_patterns_can_be_suggested_for_new_key_notions_only():
    sid, s = wine_project([{"name": "Wine"}, {"name": "Dish"}])
    seen = []
    def fake(cfg, messages, effort="high"):
        seen.append(messages[-1]["content"])
        return json.dumps({"patterns": [{"notion": "dish", "pattern": None, "rationale": "r"},
                                        {"notion": "Vintage", "pattern": None, "rationale": "invented"}]})
    L.call_llm = fake
    r = client.post("/api/momo/suggest-patterns", json={"session_id": sid, "llm_config": CFG, "only": ["Dish"]}).json()
    assert [p["notion"] for p in r["patterns"]] == ["Dish"]        # the asked notion, spelled as in the list
    assert "Dish" in seen[0] and "- Wine" not in seen[0] and "**Wine**" not in seen[0]


def test_core_relations_are_proposed_before_generation_from_questions_and_key_notions():
    sid, s = wine_project([{"name": "Wine"}, {"name": "dish", "description": "what is eaten"}])
    seen = []
    def fake(cfg, messages, effort="high"):
        seen.append(messages)
        L._record_usage(100, 10)
        return json.dumps({"summary": "s", "relations": [
            {"name": "goesWellWith", "domain": "Wine", "range": "Dish", "covers": ["CQ2"],
             "labels": {"en": "goes well with", "de": "passt zu"},
             "inverse": {"name": "isPairedWith", "description": "d"}},
            {"name": "madeFrom", "domain": "Grape", "range": ""}]})            # Grape is no key notion: dropped
    L.call_llm = fake
    r = client.post("/api/properties/propose", json={"session_id": sid, "llm_config": CFG, "before_generation": True})
    assert r.status_code == 200, r.text
    v = r.json()["property_vocab"]
    assert [x["name"] for x in v["relations"]] == ["goesWellWith"] and v["relations"][0]["covers"] == ["CQ2"]
    # the key notions, then the upper layer (used by the generation by default, DECISIONS 97)
    assert v["basis"] == "plan" and v["classes"][:3] == ["Wine", "Dish", "Process"] and "not a key notion" in v["dropped"][0]
    prompt = seen[0][-1]["content"]
    assert "CQ2. Which wine goes with grilled fish?" in prompt and "**Classes for domain and range:** Wine, Dish, Process" in prompt
    s["context"] = {**(s.get("context") or {}), "use_upper_layer": False}
    from relations import relation_classes
    assert relation_classes(s) == ["Wine", "Dish"]
    s["context"].pop("use_upper_layer")
    # two key notions: two to four relations each (DECISIONS 138)
    assert "about 4 to 8 relations (two to four per key notion)" in seen[0][0]["content"]
    assert "literature" not in prompt.lower()
    assert "Never propose a catch-all such as hasDescription" in seen[0][0]["content"]
    assert v["relations"][0]["labels"] == {"en": "goes well with", "de": "passt zu"}
    # renamed in the table: the proposal's labels no longer fit and are dropped
    renamed = [{**v["relations"][0], "name": "pairsWith"}]
    assert "labels" not in client.post("/api/properties/vocab", json={"session_id": sid, "relations": renamed}).json()["property_vocab"]["relations"][0]
    # the team edits and approves; switching off leaves an empty vocabulary that the generation ignores
    ok = client.post("/api/properties/vocab", json={"session_id": sid, "approve": True,
                                                    "relations": v["relations"] + [{"name": "partOf", "domain": "", "range": ""}]})
    assert ok.json()["property_vocab"]["status"] == "approved"
    bad = client.post("/api/properties/vocab", json={"session_id": sid, "relations": [{"name": "x", "domain": "Grape"}]})
    assert bad.status_code == 400
    off = client.post("/api/properties/vocab", json={"session_id": sid, "off": True}).json()["property_vocab"]
    assert off == {"relations": [], "status": "off", "basis": "plan"}
    empty, _ = wine_project()
    s2 = A.sessions[empty]
    s2["momo"]["competency_questions"] = []
    assert client.post("/api/properties/propose", json={"session_id": empty, "llm_config": CFG,
                                                         "before_generation": True}).status_code == 400


def test_generation_uses_the_approved_core_relations():
    sid, s = wine_project([{"name": "Wine"}, {"name": "Dish"}])
    s["property_vocab"] = {"status": "approved", "basis": "plan", "relations": [
        {"name": "goesWellWith", "description": "pairs", "domain": "Wine", "range": "Dish", "characteristics": [],
         "labels": {"en": "pairs with", "fr": "va avec"}, "label_name": "goesWellWith",
         "inverse": {"name": "isPairedWith", "description": "inverse"}, "covers": []},
        {"name": "hasPart", "description": "parts", "domain": "Meal", "range": "", "characteristics": ["transitive"],
         "inverse": None, "covers": []}]}
    obj = lambda name, d, r, **kw: {"name": name, "type": "ObjectProperty", "domain": d, "range": r,
                                    "labels": {"en": name}, **kw}
    L.call_llm = RoutedLLM(
        {"ontology_name": "W", "summary": "s", "license": "", "modules": [
            {"name": "Wine", "classes": [{"name": "Wine", "note": "n"}, {"name": "RedWine", "note": "n"}]},
            {"name": "Dish", "classes": [{"name": "Dish", "note": "n"}, {"name": "FishDish", "note": "n"}]}]},
        {"Wine": module("Wine", [("Wine", None), ("RedWine", "Wine")], [
            obj("goesWellWith", "Wine", "Dish"),                                      # own version of a core relation
            obj("pairsRedWithFish", "RedWine", "FishDish", sub_property_of="goesWellWith"),
            obj("pairsDishWithWine", "Dish", "Wine", sub_property_of="goesWellWith"),    # outside the core domain
            obj("isMadeBy", "Wine", "Dish"),                                         # no core relation above
            obj("matchesDish", "RedWine", "Dish"),                                   # placed after the modules
            obj("growsIn", "Dish", "Wine")]),                                        # the inverse fits
         "Dish": module("Dish", [("Dish", None), ("FishDish", "Dish")], [
            obj("suitsWine", "Dish", "Wine", inverse_of="goesWellWith")])},          # own inverse of a core relation
        core={"relations": [{"item": 1, "decision": "none", "reason": "making is not pairing"},
                            {"item": 2, "decision": "below", "core": "goesWellWith"},
                            {"item": 3, "decision": "below", "core": "goesWellWith"}]})
    d = generate(sid).json()
    wine_prompt = L.call_llm.prompt("Wine")[-1]["content"]
    assert "a different kind of thing (such as a value set" in wine_prompt
    assert "**Core relations** (approved by the team" in wine_prompt and "- goesWellWith: Wine -> Dish, inverse isPairedWith" in wine_prompt
    by = {p["name"]: p for p in d["ontology"]["properties"]}
    assert by["goesWellWith"]["module"] == "CoreRelations" and by["isPairedWith"]["inverse_of"] == "goesWellWith"
    assert by["goesWellWith"]["labels"] == {"en": "pairs with"} and by["isPairedWith"]["labels"] == {"en": "is paired with"}
    m = A.structural_metrics(d["ontology"])
    assert "hasPart" not in m["properties_without_domain_or_range"] and m["entities_labelled_in_all_languages_pct"] == 100.0
    assert by["hasPart"]["domain"] is None and "Meal" not in {c["name"] for c in d["ontology"]["classes"]}
    assert "suitsWine" not in by and "CoreRelations" in [m["name"] for m in d["ontology"]["modules"]]
    cr = d["modular_report"]["core_relations"]
    assert cr["relations"] == 2 and cr["widened"] == ["hasPart domain Meal"]
    assert sorted(cr["skipped"]) == ["goesWellWith (Wine)", "suitsWine (Dish)"]
    assert cr["below_core"] == ["pairsRedWithFish", "pairsDishWithWine", "matchesDish"]
    assert cr["without_core"] == ["isMadeBy", "growsIn"]
    # after the modules (DECISIONS 112): candidates with domain and range inside, specific ones first
    call = next(m for m in L.call_llm.calls if "**Relations of the modules:**" in m[-1]["content"])
    text = call[-1]["content"]
    assert "1. isMadeBy (module Wine): Wine -> Dish" in text and "candidates: goesWellWith, hasPart" in text
    assert "3. growsIn (module Wine): Dish -> Wine\n   candidates: isPairedWith, hasPart" in text
    assert "- goesWellWith: Wine -> Dish: pairs" in text and "pairsRedWithFish (" not in text
    after = cr["after_modules"]
    assert after["relations"] == 3 and after["placed"] == ["matchesDish < goesWellWith"] and after["declined"] == 1
    assert after["rejected"] == ["growsIn < goesWellWith: not a candidate of this relation"]
    assert s["gap_property_decisions"]["isMadeBy"]["reason"] == "making is not pairing"
    assert by["matchesDish"]["sub_property_of"] == "goesWellWith"
    assert cr["violations"] == ["pairsDishWithWine: domain Dish is not within goesWellWith's domain Wine",
                                "pairsDishWithWine: range Wine is not within goesWellWith's range Dish"]


def test_without_approved_core_relations_the_generation_is_unchanged():
    sid, s = wine_project([{"name": "Wine"}])
    s["property_vocab"] = {"status": "proposed", "basis": "plan", "relations": [
        {"name": "goesWellWith", "description": "", "domain": "", "range": "", "characteristics": [], "inverse": None}]}
    L.call_llm = RoutedLLM({"ontology_name": "W", "summary": "s", "license": "", "modules": [
        {"name": "Wine", "classes": [{"name": "Wine", "note": "n"}]}]}, {"Wine": module("Wine", [("Wine", None)])})
    d = generate(sid).json()
    assert "Core relations" not in L.call_llm.prompt("Wine")[-1]["content"] and "core_relations" not in d["modular_report"]
    assert "CoreRelations" not in [m["name"] for m in d["ontology"]["modules"]]


def test_the_plan_sets_the_hierarchy_where_modules_leave_it_out():
    sid, s = wine_project([{"name": "Wine"}, {"name": "Place"}])
    L.call_llm = RoutedLLM(
        {"ontology_name": "W", "summary": "s", "license": "", "modules": [
            {"name": "Wine", "classes": [{"name": "Wine", "parent": None, "note": "n"},
                                         {"name": "RedWine", "parent": "Wine", "note": "n"},
                                         {"name": "Rose", "parent": "Grape", "note": "n"},         # not planned
                                         {"name": "A", "parent": "B", "note": "n"},
                                         {"name": "B", "parent": "A", "note": "n"}]},              # a cycle
            {"name": "Place", "classes": [{"name": "Place", "note": "n"},
                                          {"name": "Region", "parent": "Place", "note": "n"},
                                          {"name": "WineRegion", "parent": "Region", "note": "n"}]}]},
        {"Wine": module("Wine", [("Wine", None), ("RedWine", None), ("Rose", None), ("A", None), ("B", None)]),
         "Place": module("Place", [("Place", None), ("Region", None), ("Area", "Place"),
                                   ("WineRegion", "Area")])})            # the module put its own class between
    d = generate(sid).json()
    plan = L.call_llm.prompt()
    assert '"parent":"PlannedClass or null"' in plan[0]["content"] and "plan that broader class as well" in plan[0]["content"]
    assert "- below: Wine (planned superclass)" in L.call_llm.prompt("Wine")[-1]["content"]
    assert "- below: Place (planned superclass)" in L.call_llm.prompt("Place")[-1]["content"]
    by = {c["name"]: c.get("parent") for c in d["ontology"]["classes"]}
    assert by["RedWine"] == "Wine" and by["Region"] == "Place" and by["Rose"] is None
    assert {by["A"], by["B"]} == {None, "A"} or {by["A"], by["B"]} == {None, "B"}    # one link of the cycle kept
    stored = s["generation_report"]                         # kept in the project for a later look
    assert stored["modular_report"] == d["modular_report"] and stored["generated_at"]
    h = d["modular_report"]["hierarchy"]
    assert sorted(h["set_from_plan"]) == sorted(["RedWine", "Region"] + [c for c in ("A", "B") if by[c]])
    assert h["differ"] == ["WineRegion below Area instead of Region"]


def test_a_second_inverse_is_removed_at_the_merge_and_reported_by_the_evaluation():
    sid, s = wine_project([{"name": "Wine"}])
    obj = lambda name, d, r, inv: {"name": name, "type": "ObjectProperty", "domain": d, "range": r,
                                   "inverse_of": inv, "labels": {"en": name}}
    props = [obj("hasVintage", "Wine", "Vintage", "isVintageOf"), obj("isVintageOf", "Vintage", "Wine", "hasVintage"),
             obj("isVintageOfObservation", "Vintage", "Observation", "hasVintage")]          # wine run 5
    L.call_llm = RoutedLLM({"ontology_name": "W", "summary": "s", "license": "", "modules": [
        {"name": "Wine", "classes": [{"name": "Wine", "note": "n"}]}]},
        {"Wine": module("Wine", [("Wine", None), ("Vintage", None), ("Observation", None)], props)})
    d = generate(sid).json()
    by = {p["name"]: p for p in d["ontology"]["properties"]}
    assert by["isVintageOfObservation"]["inverse_of"] is None and by["isVintageOf"]["inverse_of"] == "hasVintage"
    assert d["modular_report"]["inverse_conflicts"] == ["isVintageOfObservation (declared inverse of hasVintage, which has isVintageOf)"]
    from ontology_evaluation import inverse_conflicts
    # a target without a declaration of its own keeps the first claim
    lone = [{"name": "p"}, {"name": "a", "inverse_of": "p"}, {"name": "b", "inverse_of": "p"}]
    assert inverse_conflicts(lone) == [("b", "p", "a")]
    assert A.structural_metrics({"classes": [], "properties": props})["inverse_conflicts"] == [
        "isVintageOfObservation (inverse of hasVintage, which already has isVintageOf)"]


def test_a_regeneration_starts_the_cq_tests_from_fresh_sample_data():
    sid, s = wine_project([{"name": "Wine"}])
    s["cq_test_report"] = {"iteration": 1, "result": {"tests": [], "sample_data": ":old :goesWellWith :thing ."}}
    s["holdout_test_report"] = {"tests": []}
    L.call_llm = RoutedLLM({"ontology_name": "W", "summary": "s", "license": "", "modules": [
        {"name": "Wine", "classes": [{"name": "Wine", "note": "n"}]}]}, {"Wine": module("Wine", [("Wine", None)])})
    assert generate(sid).status_code == 200
    assert "cq_test_report" not in s and "holdout_test_report" not in s and s["iterations"] == 1


def test_the_plan_puts_top_classes_below_the_upper_layer():
    sid, s = wine_project([{"name": "Wine"}, {"name": "Dish"}])
    s["property_vocab"] = {"status": "approved", "basis": "plan", "relations": [
        {"name": "producedBy", "description": "", "domain": "Wine", "range": "Agent", "characteristics": [],
         "inverse": None, "covers": []}]}
    plan = {"ontology_name": "W", "summary": "s", "license": "", "modules": [
        {"name": "Wine", "classes": [{"name": "Wine", "parent": "PhysicalObject", "note": "n"},
                                     {"name": "RedWine", "parent": "Wine", "note": "n"}]},
        {"name": "Dish", "classes": [{"name": "Dish", "parent": None, "note": "n"},
                                     {"name": "Course", "parent": "Nonsense", "note": "n"}]}]}
    L.call_llm = RoutedLLM(plan, {"Wine": module("Wine", [("Wine", None), ("RedWine", "Wine")]),
                                  "Dish": module("Dish", [("Dish", None), ("Course", None), ("Recipe", "InformationObject")])})
    d = generate(sid).json()
    p = L.call_llm.prompt()
    assert "**Upper layer** (exists in the ontology" in p[-1]["content"] and "- Specification (below InformationObject):" in p[-1]["content"]
    assert "The UPPER LAYER listed in the task" in p[0]["content"]
    wine = L.call_llm.prompt("Wine")[-1]["content"]
    assert "- below: PhysicalObject (upper layer class)" in wine and "- below: Wine (planned superclass)" in wine
    assert "**Upper layer** (exists in the ontology; never define these classes): Process, Agent" in wine
    by = {c["name"]: c for c in d["ontology"]["classes"]}
    assert by["Wine"]["parent"] == "PhysicalObject" and by["PhysicalObject"]["layer"] == "upper"
    assert by["Recipe"]["parent"] == "InformationObject" and by["Course"]["parent"] is None
    u = d["modular_report"]["upper_layer"]
    assert u["used"] == ["Agent", "InformationObject", "PhysicalObject"]          # Agent: range of a core relation
    assert sorted(u["removed"]) == ["Process", "Quality", "Specification"] and u["outside"] == ["Course", "Dish"]
    props = {x["name"]: x for x in d["ontology"]["properties"]}
    assert props["producedBy"]["range"] == "Agent" and d["modular_report"]["core_relations"]["widened"] == []
    assert any(a["type"] == "DisjointClasses" and set(a["classes"]) == {"Agent", "InformationObject", "PhysicalObject"}
               for a in d["ontology"]["axioms"])
    # switched off in step 4: no upper layer, the plan's upper parent is dropped
    s["context"] = {**(s.get("context") or {}), "use_upper_layer": False}
    L.call_llm = RoutedLLM(plan, {"Wine": module("Wine", [("Wine", None)]), "Dish": module("Dish", [("Dish", None)])})
    d = generate(sid).json()
    assert "Upper layer" not in L.call_llm.prompt()[-1]["content"] and "upper_layer" not in d["modular_report"]
    assert {c["name"]: c.get("parent") for c in d["ontology"]["classes"]}["Wine"] is None
    assert "UpperLayer" not in [m["name"] for m in d["ontology"]["modules"]]


def test_planned_classes_are_linked_to_loaded_vocabularies_after_planning():
    sid, s = wine_project([{"name": "Wine"}])
    term = lambda name, label: {"name": name, "kind": "class", "label": label, "definition": f"A {label}.", "parents": [],
                                "disjoint": []}
    s["vocabularies"] = {"wn": {"name": "Wine vocabulary", "namespace": "http://example.org/wn#",
                                "classes": [term("Wine", "wine"), term("RedWine", "red wine"), term("Grape", "grape")],
                                "properties": []},
                         "geo": {"name": "Places", "namespace": "http://example.org/geo#",
                                 "classes": [term("Place", "place"), term("Estate", "estate")], "properties": []}}
    s["suggested_standards"] = [{"name": "Wine vocabulary", "prefix": "wn", "namespace": "http://example.org/wn#",
                                 "decision": "align"},
                                {"name": "Places", "prefix": "geo", "namespace": "http://example.org/geo#",
                                 "decision": "use_terms"}]
    plan = {"ontology_name": "W", "summary": "s", "license": "", "modules": [
        {"name": "Wine", "classes": [{"name": "Wine", "note": "an alcoholic drink"},
                                     {"name": "RedWine", "parent": "Wine", "note": "n"},
                                     {"name": "Grape", "note": "n"},
                                     {"name": "Place", "note": "where a wine comes from"},
                                     {"name": "Region", "parent": "Place", "note": "n"},
                                     {"name": "WhiteWine", "parent": "Wine", "note": "n"},       # candidate wn:Wine
                                     {"name": "Vintner", "note": "n"},
                                     {"name": "WineEstate", "note": "a vineyard with its winery"}]}]}
    links = {"links": [{"class": "Wine", "term": "wn:Wine", "as": "equivalent"},
                       {"class": "RedWine", "term": "wn:RedWine", "as": "subclass"},
                       {"class": "Grape", "term": "wn:Grape", "as": "use"},        # wn is 'align': stays a class
                       {"class": "Place", "term": "geo:Place", "as": "use"},       # geo is 'use terms directly'
                       {"class": "Region", "term": "wn:Grape", "as": "subclass"},  # not a candidate of Region
                       {"class": "WineEstate", "term": "geo:Estate", "as": "use"}],  # broader: stays a class (VA run 2)
             "none": [{"class": "WhiteWine", "reason": "a white wine is not every wine"}]}
    L.call_llm = RoutedLLM(plan, {"Wine": module("Wine", [("Wine", None), ("RedWine", "Wine"), ("Grape", None),
                                                          ("Region", None), ("WhiteWine", "Wine"),
                                                          ("Vintner", None)])}, links)
    d = generate(sid).json()
    # the plan no longer sees the vocabularies (wine run 11: it planned their terms as own classes)
    assert "wn:" not in L.call_llm.prompt()[-1]["content"] and "Vocabulary terms" not in L.call_llm.prompt()[0]["content"]
    link_call = next(m for m in L.call_llm.calls if "**Planned classes and candidate terms:**" in m[-1]["content"])
    text = link_call[-1]["content"]
    assert "- Wine (module Wine): an alcoholic drink" in text and '    candidate wn:Wine "wine": A wine.' in text
    assert "- geo: Places - use terms directly" in text and "- Region" not in text       # no candidate for Region
    wine = L.call_llm.prompt("Wine")[-1]["content"]
    assert "- linked to: wn:Wine (same meaning" in wine and "- linked to: wn:RedWine (a kind of it" in wine
    assert "- Place -> use the vocabulary term geo:Place directly" in wine and "### Place" not in wine
    assert "- below: geo:Place" in wine
    by = {c["name"]: c for c in d["ontology"]["classes"]}
    assert "Place" not in by and by["Region"]["parent"] == "geo:Place"
    axioms = {(a["type"], tuple(a["classes"])) for a in d["ontology"]["axioms"]}
    assert {("EquivalentClasses", ("Wine", "wn:Wine")), ("SubClassOf", ("RedWine", "wn:RedWine")),
            ("SubClassOf", ("Grape", "wn:Grape"))} <= axioms
    r = d["modular_report"]["reuse"]
    assert r["links"] == ["Wine = wn:Wine", "RedWine -> wn:RedWine", "Grape -> wn:Grape", "WineEstate -> geo:Estate"]
    assert r["terms"] == ["Place -> geo:Place"] and "WineEstate" in by
    assert r["dropped"] == ["Grape -> wn:Grape: the team chose 'align' for wn, so it stays an own class",
                            "Region -> wn:Grape: not a candidate of this class",
                            "WineEstate -> geo:Estate: a term replaces a class only under the same name or label, so it "
                            "stays an own class below the term"] and r["candidates"] == 6
    assert "only if the term means the SAME as the planned class" in link_call[0]["content"]
    assert r["declined"] == ["WhiteWine"] and "Vintner" not in text          # Vintner has no candidate at all
    # the declined class is an align decision now: the evaluation's "Align" does not offer it again
    assert s["gap_align_decisions"]["WhiteWine"]["reason"] == "a white wine is not every wine"
    assert "WhiteWine" not in {c["name"] for c in A.align_candidates(s)}
    assert "only if the term's definition says the same" in link_call[0]["content"]
    # inverses only where needed (wine run 12: every module relation had one)
    system = L.call_llm.prompt("Wine")[0]["content"]
    assert "an inverse only where a competency question or the data need both" in system
    assert "consistent inverses" not in system and "where an inverse is meaningful" not in system
    # without loaded vocabularies there is no link call
    s.pop("vocabularies")
    L.call_llm = RoutedLLM({"ontology_name": "W", "summary": "s", "license": "", "modules": [
        {"name": "Wine", "classes": [{"name": "Wine", "note": "n"}]}]}, {"Wine": module("Wine", [("Wine", None)])})
    generate(sid)
    assert len(L.call_llm.calls) == 2                                     # plan and one module


def test_upper_classes_module_classes_and_properties_are_linked_after_the_modules():
    sid, s = wine_project([{"name": "Wine"}])
    cls = lambda name, label: {"name": name, "kind": "class", "label": label, "definition": f"A {label}.", "parents": [],
                               "disjoint": []}
    prop = lambda name, label, dom, rng: {"name": name, "kind": "object", "label": label, "definition": f"{label}.",
                                          "domain": dom, "range": rng, "parents": []}
    s["vocabularies"] = {"pv": {"name": "Provenance", "namespace": "http://example.org/pv#",
                                "classes": [cls("Agent", "agent"), cls("Activity", "activity"), cls("Estate", "estate")],
                                "properties": [prop("wasDerivedFrom", "was derived from", "", ""),
                                               prop("used", "used", "pv:Activity", "pv:Estate")]}}
    s["suggested_standards"] = [{"name": "Provenance", "prefix": "pv", "namespace": "http://example.org/pv#",
                                 "decision": "align"}]
    s["corpus"] = {"docs": [{"id": "d1", "name": "a.pdf", "card": {"title": "Wines", "authors": "Doe, J.", "year": "2020"}}],
                   "inventory": {"themes": [], "relations": [], "taxonomies": [], "concepts": [
                       {"id": "c1", "label": "Winery", "variants": ["Wine estate"], "papers": 1, "definition": "d",
                        "sources": [{"doc": "d1", "definition": "d"}]}]}}
    plan = {"ontology_name": "W", "summary": "s", "license": "", "modules": [
        {"name": "Wine", "classes": [{"name": "Wine", "note": "n"},
                                     {"name": "Winery", "concepts": ["c1"], "note": "n"},     # found by its variant
                                     {"name": "Winemaker", "parent": "Agent", "note": "n"}]}]}
    L.call_llm = RoutedLLM(
        plan,
        {"Wine": module("Wine", [("Wine", None), ("Winery", None), ("Winemaker", "Agent"), ("Fermentation", None),
                                 ("TastingActivity", None)],      # added by the module, not planned
                        [{"name": "derivedFrom", "type": "ObjectProperty", "domain": "Wine", "range": "Wine",
                          "labels": {"en": "derived from"}},
                         {"name": "used", "type": "ObjectProperty", "domain": "Fermentation", "range": "Wine",
                          "labels": {"en": "used"}}])},
        links={"links": [{"class": "Winery", "term": "pv:Estate", "as": "subclass"}]},
        after={"links": [{"item": "Agent", "term": "pv:Agent", "as": "equivalent"},
                         {"item": "derivedFrom", "term": "pv:wasDerivedFrom", "as": "subproperty"},
                         {"item": "used", "term": "pv:used", "as": "subproperty"},         # domain outside pv:Activity
                         {"item": "Winemaker", "term": "pv:Agent", "as": "subclass"}],     # not one of its candidates
               "none": [{"item": "TastingActivity", "reason": "a tasting is an event, not a provenance activity"}]})
    d = generate(sid).json()
    plan_link = next(m for m in L.call_llm.calls if "**Planned classes and candidate terms:**" in m[-1]["content"])
    assert '- Winery (module Wine): n\n    candidate pv:Estate "estate"' in plan_link[-1]["content"]
    after = next(m for m in L.call_llm.calls if "**Own terms and candidate terms:**" in m[-1]["content"])
    text = after[-1]["content"]
    assert "- Agent (class" in text and "- TastingActivity (class, module Wine)" in text
    assert "- derivedFrom (ObjectProperty, module Wine): Wine -> Wine" in text and "candidate pv:used (object)" in text
    assert "- Winery" not in text and "- Wine (" not in text       # linked by the plan; no candidate
    assert "lies within nothing narrower" in after[0]["content"]
    o = d["ontology"]
    axioms = {(a["type"], tuple(a["classes"])) for a in o["axioms"]}
    assert ("EquivalentClasses", ("Agent", "pv:Agent")) in axioms and ("SubClassOf", ("Winery", "pv:Estate")) in axioms
    props = {p["name"]: p for p in o["properties"]}
    assert props["derivedFrom"]["sub_property_of"] == "pv:wasDerivedFrom" and not props["used"].get("sub_property_of")
    r = d["modular_report"]["reuse"]["after_modules"]
    assert r["links"] == ["Agent = pv:Agent", "derivedFrom < pv:wasDerivedFrom"] and r["candidates"] == 4
    assert r["rejected"][0].startswith("Winemaker -> pv:Agent: not a candidate")
    assert r["rejected"][1] == "used < pv:used: used cannot be a subproperty of pv:used: its domain Fermentation is " \
        "not below the domain pv:Activity of pv:used - choose a broader relation, link the class first, or widen that one first"
    assert r["declined"] == ["TastingActivity"] and r["errors"] == []
    store = s["gap_align_decisions"]
    assert store["TastingActivity"]["reason"] == "a tasting is an event, not a provenance activity"
    assert "used" not in store                       # refused by the server: stays open for "Align"
    assert A.align_candidates(s) and {c["name"] for c in A.align_candidates(s)} == {"used"}


def test_the_plan_receives_the_literatures_hierarchy_and_its_declined_relations_are_remembered():
    sid, s = wine_project([{"name": "Wine"}])
    src = lambda broader: {"doc": "d1", "definition": "d", "broader": broader}
    s["corpus"] = {"docs": [{"id": "d1", "name": "a.pdf", "card": {"title": "Wines", "authors": "Doe, J.", "year": "2020"}}],
                   "inventory": {"themes": [], "relations": [], "concepts": [
                       {"id": "c1", "label": "Wine", "variants": [], "papers": 3, "definition": "a drink",
                        "sources": [src("beverage"), src("beverage")]},
                       {"id": "c2", "label": "Red wine", "variants": [], "papers": 2, "definition": "a red one",
                        "sources": [src("wine"), src("wine"), src("wine style")]},
                       {"id": "c3", "label": "White wine", "variants": [], "papers": 2, "definition": "a white one",
                        "sources": [src("Wine")]},
                       {"id": "c4", "label": "Bottle", "variants": [], "papers": 2, "definition": "a container",
                        "sources": [src("wine")]}],
                       "taxonomies": [{"name": "Wine colours", "categories": ["Red wine", "White wine", "Rose"], "doc": "d1"},
                                      {"name": "Colours of wine", "categories": ["red wine", "white wine"], "doc": "d1"}]}}
    L.call_llm = RoutedLLM(
        {"ontology_name": "W", "summary": "s", "license": "",
         "hierarchy_declined": [{"narrower": "Bottle", "broader": "Wine", "reason": "a bottle holds wine, it is not one"}],
         "modules": [{"name": "Wine", "classes": [{"name": "Wine", "concepts": ["c1"], "note": "n"},
                                                  {"name": "RedWine", "parent": "Wine", "concepts": ["c2"], "note": "n"},
                                                  {"name": "Bottle", "concepts": ["c4"], "note": "n"}]}]},
        {"Wine": module("Wine", [("Wine", None), ("RedWine", "Wine"), ("Bottle", None)])},
        complete={"excluded": [{"concept": "c3", "reason": "not needed"}]})
    d = generate(sid).json()
    plan = L.call_llm.prompt()
    text = plan[-1]["content"]
    assert "c2 | Red wine | 2 | broader: c1, 'wine style' | a red one" in text       # most frequent first, as ids
    assert "c1 | Wine | 3 | broader: 'beverage'" in text
    assert "- 'Wine colours': Red wine (c2); White wine (c3); Rose" in text and "Colours of wine" not in text  # same taxonomy once
    assert "hierarchy_declined" in plan[0]["content"] and "say 'broader' loosely" in plan[0]["content"]
    assert d["modular_report"]["hierarchy"]["declined"] == 1
    store = s["gap_hierarchy_decisions"]
    assert store[P._norm("Bottle is a kind of Wine")] == {"item": "Bottle is a kind of Wine",
                                                          "reason": "a bottle holds wine, it is not one"}


def test_every_central_concept_is_planned_or_excluded_with_a_reason():
    sid, s = wine_project([{"name": "Wine"}])
    c = lambda i, label, papers: {"id": i, "label": label, "variants": [], "papers": papers, "definition": f"a {label}",
                                  "sources": [{"doc": "d1", "definition": f"a {label}"}]}
    s["corpus"] = {"docs": [{"id": "d1", "name": "a.pdf", "card": {"title": "Wines", "authors": "Doe, J.", "year": "2020"}}],
                   "inventory": {"themes": [], "relations": [], "taxonomies": [], "concepts": [
                       c("c1", "Wine", 4), c("c2", "Tannin", 3), c("c3", "Sommelier", 2), c("c4", "Cork", 2),
                       c("c5", "Survey method", 2), c("c6", "Vintage", 2), c("c7", "Decanter", 2), c("c8", "Glass", 1)]}}
    s["gap_decisions"] = {"decanter": "declined earlier by the team"}     # counts as excluded, not asked again
    L.call_llm = RoutedLLM(
        {"ontology_name": "W", "summary": "s", "license": "",
         "excluded": [{"concept": "c5", "reason": "a paper's method"}],
         "modules": [{"name": "Wine", "classes": [{"name": "Wine", "concepts": ["c1"], "note": "n"}],
                      "other": [{"concepts": ["c2"], "as": "property", "hint": "a level"}]}]},
        {"Wine": module("Wine", [("Wine", None), ("Sommelier", None)])},
        complete={"assign": [{"concept": "c3", "module": "Wine", "class": "Sommelier", "new": True, "parent": "Agent"},
                             {"concept": "c4", "module": "Wine", "class": "Wine"},           # same as a planned class
                             {"concept": "c6", "module": "Nowhere", "class": "Vintage"}],    # unknown module: ignored
                  "excluded": []})
    d = generate(sid).json()
    plan = L.call_llm.prompt()
    assert "is CENTRAL and must be accounted for" in plan[0]["content"] and '"excluded":[{"concept":"c12"' in plan[0]["content"]
    assert "{{" not in plan[0]["content"]                                   # format hints with single braces
    done = next(m for m in L.call_llm.calls if "**Central concepts without a place in the plan**" in m[-1]["content"])
    text = done[-1]["content"]
    assert "c3 | Sommelier | 2 sources" in text and "c6 | Vintage" in text
    # the plan's exclusion is reviewed too (DECISIONS 131); decided earlier by the team or not central: not shown
    assert 'c5 | Survey method | 2 sources | a Survey method | REVIEW: excluded by the plan ("a paper\'s method")' in text
    assert "although" not in text.split("c5 |")[1].split("\n")[0]
    assert "c7 |" not in text and "c8 |" not in text
    assert "**Upper layer:** Agent" in text
    wine = L.call_llm.prompt("Wine")[-1]["content"]
    assert "### Sommelier" in wine and "- below: Agent (upper layer class)" in wine
    by = {x["name"]: x for x in d["ontology"]["classes"]}
    assert by["Sommelier"]["parent"] == "Agent" and by["Wine"]["inventory_concepts"] == ["Wine", "Cork"]
    r = d["modular_report"]["central"]
    # by_plan counts what the plan placed; its exclusions went to the review (placed + completed + excluded + open = 7)
    assert (r["central"], r["by_plan"], r["earlier_decisions"], r["completion_assigned"], r["completion_excluded"]) == \
        (7, 2, 1, 2, 0)
    assert r["excluded"] == ["Decanter", "Survey method"] and r["unassigned"] == ["Vintage"]
    assert (r["reviewed"], r["reviewed_protected"], r["review_kept"]) == (1, 0, ["Survey method"])
    assert s["gap_decisions"][C.concept_key("Survey method")] == "a paper's method"


def test_excluded_taxonomy_categories_and_concepts_of_the_questions_are_reviewed():
    sid, s = wine_project([{"name": "Wine"}])
    c = lambda i, label, variants=(): {"id": i, "label": label, "variants": list(variants), "papers": 2,
                                       "definition": f"a {label}", "sources": [{"doc": "d1", "definition": f"a {label}"}]}
    s["corpus"] = {"docs": [{"id": "d1", "name": "a.pdf", "card": {"title": "Wines", "authors": "Doe, J.", "year": "2020"}}],
                   "inventory": {"themes": [], "relations": [], "concepts": [
                       c("c1", "Wine"), c("c2", "Ice wine"), c("c3", "Late harvest"), c("c4", "Grilled fish"),
                       c("c5", "Wine press"), c("c6", "Fortified wine"), c("c7", "Method")],
                       "taxonomies": [{"name": "Dessert wine styles", "categories": ["Ice wine", "Late harvest",
                                                                                    "Fortified wine"], "doc": "d1"}]}}
    s["momo"]["competency_questions"].append({"question": "Which method was used for the wine?"})
    s["gap_decisions"] = {C.concept_key("Fortified wine"): "the team leaves fortified wines out"}
    L.call_llm = RoutedLLM(
        {"ontology_name": "W", "summary": "s", "license": "",
         "excluded": [{"concept": "c2", "reason": "a narrowly named style in one taxonomy"},
                      {"concept": "c3", "reason": "too specific"},
                      {"concept": "c4", "reason": "a dish, not a wine"},      # named in a competency question
                      {"concept": "c5", "reason": "equipment, out of scope"},
                      {"concept": "c6", "reason": "too specific"},            # the team decided earlier: no review
                      {"concept": "c7", "reason": "generic research vocabulary"}],   # "method" in a CQ
         "modules": [{"name": "Wine", "classes": [{"name": "Wine", "concepts": ["c1"], "note": "n"}]}]},
        {"Wine": module("Wine", [("Wine", None), ("IceWine", "Wine")])},
        complete={"assign": [{"concept": "c2", "module": "Wine", "class": "IceWine", "new": True, "parent": "Wine"},
                             {"concept": "c4", "module": "Wine", "as": "individual", "hint": "a dish"}],
                  "excluded": [{"concept": "c7", "reason": "the same as the evaluation method concept"}]})
    d = generate(sid).json()
    plan = L.call_llm.prompt()[0]["content"]
    assert "is not excluded for being narrow, specific or part of one framework" in plan
    done = next(m for m in L.call_llm.calls if "**Central concepts without a place in the plan**" in m[-1]["content"])
    assert "being narrow, specific or part of one framework is no reason" in done[0]["content"]
    text = done[-1]["content"]
    assert ('c2 | Ice wine | 2 sources | a Ice wine | REVIEW: excluded by the plan ("a narrowly named style in one '
            'taxonomy") although a category of the literature\'s taxonomy "Dessert wine styles"') in text
    assert 'REVIEW: excluded by the plan ("a dish, not a wine") although named in competency question 2' in text
    assert "c7 | Method" in text and "named in competency question 3" in text
    assert 'c5 | Wine press | 2 sources | a Wine press | REVIEW: excluded by the plan ("equipment, out of scope")' in text
    assert "c6 |" not in text                                 # decided by the team: not reviewed again
    r = d["modular_report"]["central"]
    assert (r["reviewed"], r["reviewed_protected"]) == (5, 4)
    assert r["review_kept"] == ["Late harvest", "Method", "Wine press"]   # not placed: the plan's reason stands
    assert r["excluded"] == ["Fortified wine", "Late harvest", "Method", "Wine press"] and r["unassigned"] == []
    assert s["gap_decisions"][C.concept_key("Late harvest")] == "too specific"
    assert s["gap_decisions"][C.concept_key("Method")] == "the same as the evaluation method concept"
    assert {x["name"]: x for x in d["ontology"]["classes"]}["IceWine"]["parent"] == "Wine"


def test_central_concepts_missing_after_the_modules_are_linked_or_added():
    # VA 6a-6c (DECISIONS 136): a module built "stability of the task" as hasTaskStability, which the evaluation could
    # not find; others (chunking, feedback loop) no module built at all
    sid, s = wine_project([{"name": "Wine"}])
    c = lambda i, label: {"id": i, "label": label, "variants": [], "papers": 2, "definition": f"a {label}",
                          "sources": [{"doc": "d1", "definition": f"a {label}"}]}
    s["corpus"] = {"docs": [{"id": "d1", "name": "a.pdf", "card": {"title": "Wines", "authors": "Doe, J.", "year": "2020"}}],
                   "inventory": {"themes": [], "relations": [], "taxonomies": [], "concepts": [
                       c("c1", "Wine"), c("c2", "Tannin level"), c("c3", "Cork"), c("c4", "Decanting")]}}
    mod = module("Wine", [("Wine", None)], [{"name": "hasTannin", "type": "DatatypeProperty", "domain": "Wine",
                                             "range": "xsd:string", "concepts": ["c2", "c99"]}])
    L.call_llm = RoutedLLM(
        {"ontology_name": "W", "summary": "s", "license": "", "excluded": [],
         "modules": [{"name": "Wine", "classes": [{"name": "Wine", "concepts": ["c1"], "note": "n"}],
                      "other": [{"concepts": ["c2"], "as": "property", "hint": "a level"},
                                {"concepts": ["c3"], "as": "property", "hint": "the closure"},
                                {"concepts": ["c4"], "as": "individual", "hint": "a practice"}]}]},
        {"Wine": mod},
        missing={"summary": "added", "skipped": [{"concept": "Decanting", "reason": "a serving practice, out of scope"}],
                 "ops": [{"op": "add_class", "name": "Cork", "parent": "Wine", "module": "Wine",
                          "labels": {"en": "Cork"}, "description": "A closure.", "inventory_concepts": ["Cork"]}]})
    d = generate(sid).json()
    wine = L.call_llm.prompt("Wine")
    assert "- [c2] Tannin level -> as property" in wine[-1]["content"] and '"concepts":["c12"]' in wine[0]["content"]
    by = {p["name"]: p for p in d["ontology"]["properties"]}
    assert by["hasTannin"]["inventory_concepts"] == ["Tannin level"] and "concepts" not in by["hasTannin"]
    r = d["modular_report"]["central_after_modules"]
    # Tannin level counts through the link; Cork and Decanting went to the step, Cork was added, Decanting declined
    assert r["missing"] == ["Cork", "Decanting"] and r["added"] == ["Cork"] and r["declined"] == 1
    assert "Cork" in {x["name"] for x in d["ontology"]["classes"]}
    assert s["gap_decisions"][C.concept_key("Decanting")] == "a serving practice, out of scope"
    missing_call = [m for m in L.call_llm.calls if "but not yet represented in the ontology" in m[-1]["content"]]
    assert len(missing_call) == 1 and '"Tannin level"' not in missing_call[0][-1]["content"]


def test_an_exclusion_that_names_a_planned_class_is_an_assignment():
    # VA 5a: the plan "excluded" concepts as "accounted for as ObjectiveUncertainty" (DECISIONS 131)
    classes = {"ObjectiveUncertainty": ({}, {}), "Uncertainty": ({}, {}), "Interaction": ({}, {})}
    assert G._named_class("Accounted for as ObjectiveUncertainty in the Uncertainty module.", classes) == "ObjectiveUncertainty"
    assert G._named_class("the same as the class `Uncertainty`", classes) == "Uncertainty"
    assert G._named_class("Covered by the Uncertainty module.", classes) is None              # a module, not a class
    assert G._named_class("A primitive of one model, not the general Interaction notion.", classes) is None
    assert G._named_class("modelled as UncertaintyKind", classes) is None                     # not planned
    assert G._named_class("represented as ObjectiveUncertainties", classes) is None           # no partial names

    sid, s = wine_project([{"name": "Wine"}])
    c = lambda i, label: {"id": i, "label": label, "variants": [], "papers": 2, "definition": f"a {label}",
                          "sources": [{"doc": "d1", "definition": f"a {label}"}]}
    s["corpus"] = {"docs": [{"id": "d1", "name": "a.pdf", "card": {"title": "Wines", "authors": "Doe, J.", "year": "2020"}}],
                   "inventory": {"themes": [], "relations": [], "taxonomies": [],
                                 "concepts": [c("c1", "Wine"), c("c2", "Red wine"), c("c3", "Wine press")]}}
    L.call_llm = RoutedLLM(
        {"ontology_name": "W", "summary": "s", "license": "",
         "excluded": [{"concept": "c2", "reason": "Accounted for as RedWine in the Wine module."},
                      {"concept": "c3", "reason": "equipment, out of scope"}],
         "modules": [{"name": "Wine", "classes": [{"name": "Wine", "concepts": ["c1"], "note": "n"},
                                                  {"name": "RedWine", "concepts": [], "note": "n", "parent": "Wine"}]}]},
        {"Wine": module("Wine", [("Wine", None), ("RedWine", "Wine")])},
        complete={"assign": [], "excluded": [{"concept": "c3", "reason": "equipment, not a wine"}]})
    d = generate(sid).json()
    r = d["modular_report"]["central"]
    assert r["accounted_as"] == ["Red wine"] and r["excluded"] == ["Wine press"]
    assert r["reviewed"] == 1 and r["review_kept"] == ["Wine press"]
    assert {x["name"]: x for x in d["ontology"]["classes"]}["RedWine"]["inventory_concepts"] == ["Red wine"]
    assert s["gap_decisions"][C.concept_key("Wine press")] == "equipment, not a wine"
    assert C.concept_key("Red wine") not in s["gap_decisions"]


def test_relations_of_the_literature_the_modules_leave_out_are_decided_after_the_modules():
    sid, s = wine_project([{"name": "Wine"}])
    c = lambda i, label, broader: {"id": i, "label": label, "variants": [], "papers": 2, "definition": f"a {label}",
                                   "sources": [{"doc": "d1", "definition": "d", "broader": broader}] * 2}
    s["corpus"] = {"docs": [{"id": "d1", "name": "a.pdf", "card": {"title": "Wines", "authors": "Doe, J.", "year": "2020"}}],
                   "inventory": {"themes": [], "relations": [], "taxonomies": [], "concepts": [
                       c("c1", "Wine", None), c("c2", "RedWine", "wine"), c("c3", "Rose", "wine"),
                       c("c4", "Bottle", "wine"), c("c5", "Cork", "wine"), c("c6", "Glass", "wine"),
                       c("c7", "Pink", None), c("c8", "Closure", None),
                       c("c9", "Sparkling", "wine"), c("c10", "Festive", None),
                       {**c("c11", "Sparkling", "festive"), "id": "c11"}]}}
    plan = {"ontology_name": "W", "summary": "s", "license": "",
            "hierarchy_declined": [{"narrower": "Glass", "broader": "Wine", "reason": "a glass holds wine"}],
            "modules": [{"name": "Wine", "classes": [{"name": n, "concepts": [i], "note": "n"} for n, i in
                        [("Wine", "c1"), ("RedWine", "c2"), ("Rose", "c3"), ("Bottle", "c4"), ("Cork", "c5"),
                         ("Glass", "c6"), ("Pink", "c7"), ("Closure", "c8"), ("Sparkling", "c9"),
                         ("Festive", "c10")]]}]}
    wine = module("Wine", [("Wine", None), ("RedWine", None), ("Rose", "Pink"), ("Bottle", None), ("Cork", "Closure"),
                           ("Glass", None), ("Pink", None), ("Closure", None), ("Sparkling", None), ("Festive", None)])
    wine["axioms"] = [{"type": "DisjointClasses", "classes": ["Closure", "Wine"]}]
    L.call_llm = RoutedLLM(plan, {"Wine": wine}, hierarchy={"relations": [
        {"item": 1, "decision": "kind_of", "reason": "a red wine is a wine"},
        {"item": 2, "decision": "kind_of", "reason": "a rose is a wine as well as a pink thing"},
        {"item": 3, "decision": "decline", "reason": "a bottle holds wine"},
        {"item": 4, "decision": "kind_of", "reason": "wrong"},
        {"item": 5, "decision": "kind_of"}, {"item": 6, "decision": "kind_of"}]})   # two broader terms of Sparkling
    d = generate(sid).json()
    call = next(m for m in L.call_llm.calls if "**Relations:**" in m[-1]["content"])
    text = call[-1]["content"]
    assert "1. RedWine is a kind of Wine? (2 sources)\n   RedWine" in text and "   Rose (below Pink): A rose." in text
    assert "Glass is a kind of Wine" not in text                          # declined by the plan: not asked again
    assert "a category of it rather than a kind" in call[0]["content"]
    by = {x["name"]: x for x in d["ontology"]["classes"]}
    assert by["RedWine"]["parent"] == "Wine" and by["Rose"]["parent"] == "Pink" and by["Cork"]["parent"] == "Closure"
    assert ["Rose", "Wine"] in [a["classes"] for a in d["ontology"]["axioms"] if a["type"] == "SubClassOf"]
    r = d["modular_report"]["hierarchy"]["after_modules"]
    items = [line.split(". ", 1)[1].split("?")[0] for line in text.splitlines() if line[:1].isdigit()]
    assert items[4:] == ["Sparkling is a kind of Wine", "Sparkling is a kind of Festive"]
    # the first sets the superclass, the second adds a SubClassOf axiom instead of overwriting it
    assert by["Sparkling"]["parent"] == "Wine" and ["Sparkling", "Festive"] in [a["classes"] for a in d["ontology"]["axioms"]]
    assert r["relations"] == 6 and r["declined"] == 1
    assert r["realized"] == ["RedWine -> Wine", "Rose -> Wine", "Sparkling -> Wine", "Sparkling -> Festive"]
    assert r["rejected"] == ["Cork -> Wine: Closure and Wine are disjoint"]
    assert s["gap_hierarchy_decisions"]["bottleisakindofwine"]["reason"] == "a bottle holds wine"
    # the evaluation reports declined relations apart
    from ontology_evaluation import hierarchy_coverage
    h = hierarchy_coverage(d["ontology"], s["corpus"]["inventory"], C.concept_key, None, P.declined_relations(s))
    assert (h["relations"], h["realized"], h["declined_count"], h["unrealized_count"]) == (7, 4, 2, 1)
    assert h["realized_or_declined_pct"] == 85.7 and h["unrealized"][0]["narrower"] == "Cork"


def test_the_hierarchy_step_keeps_upper_layer_classes_at_the_top():
    session = {"momo": {"use_case": "u"}, "corpus": {"docs": [], "inventory": {"themes": [], "relations": [],
               "taxonomies": [], "concepts": [{"id": "c1", "label": "Process", "variants": [], "papers": 2,
                                               "sources": [{"doc": "d1", "broader": "workflow"}] * 2},
                                              {"id": "c2", "label": "Workflow", "variants": [], "papers": 2,
                                               "sources": [{"doc": "d1"}]}]}}}
    onto = {"modules": [{"name": "M"}], "properties": [], "individuals": [], "axioms": [], "classes": [
        {"name": "Process", "layer": "upper", "parent": None, "module": "M", "labels": {"en": "Process"}},
        {"name": "Workflow", "parent": None, "module": "M", "labels": {"en": "Workflow"}}]}
    L.call_llm = lambda cfg, messages, effort="high": json.dumps({"relations": [{"item": 1, "decision": "kind_of"}]})
    new, r = G.hierarchy_after_modules(session, CFG, onto)
    assert r["relations"] == 1 and r["realized"] == [] and new["classes"][0]["parent"] is None
    assert r["rejected"] == ["Process -> Workflow: an upper-layer class stays at the top"]


def test_a_failed_link_call_is_no_decision_and_a_new_generation_drops_the_old_evaluation():
    sid, s = wine_project([{"name": "Wine"}])
    term = {"name": "Wine", "kind": "class", "label": "wine", "definition": "A wine.", "parents": [], "disjoint": []}
    s["vocabularies"] = {"wn": {"name": "Wine vocabulary", "namespace": "http://example.org/wn#", "classes": [term],
                                "properties": []}}
    s["suggested_standards"] = [{"name": "Wine vocabulary", "prefix": "wn", "namespace": "http://example.org/wn#",
                                 "decision": "align"}]
    s["evaluation"] = {"iteration": 1, "cq": {"full": 7}}             # of the previous ontology
    routed = RoutedLLM({"ontology_name": "W", "summary": "s", "license": "", "modules": [
        {"name": "Wine", "classes": [{"name": "Wine", "note": "n"}]}]}, {"Wine": module("Wine", [("Wine", None)])})
    def llm_call(cfg, messages, effort="high"):
        if "**Planned classes and candidate terms:**" in messages[-1]["content"]:
            raise L.LLMTruncatedError(32000)                           # a truncated answer: the step is skipped
        return routed(cfg, messages, effort)
    L.call_llm = llm_call
    r = generate(sid)
    assert r.status_code == 200, r.text
    reuse = r.json()["modular_report"]["reuse"]
    assert reuse["error"] and reuse["declined"] == []
    # not stored as "no link" from the failed call: the class is offered again after the modules
    after = [m for m in routed.calls if "**Own terms and candidate terms:**" in m[-1]["content"]]
    assert after and "- Wine (class" in after[0][-1]["content"]
    assert "linking the plan" not in (s.get("gap_align_decisions") or {}).get("Wine", {}).get("reason", "")
    assert "evaluation" not in s


def test_the_hierarchy_step_checks_disjointness_with_the_batch_and_the_subclasses():
    cls = lambda n, p=None: {"name": n, "parent": p}
    onto = {"classes": [cls("Process"), cls("Agent"), cls("Task"), cls("Analysis", "Task")], "properties": [],
            "individuals": [], "axioms": [{"type": "DisjointClasses", "classes": ["Process", "Agent"]}]}
    assert G._disjoint_conflict(onto, "Task", "Process") == ""
    # a second broader term of the same batch is checked against the first
    assert G._disjoint_conflict(onto, "Task", "Agent", pending=[("Task", "Process")]) == "Agent and Process are disjoint"
    # a subclass that is already below Agent would fall under Process as well
    onto["axioms"].append({"type": "SubClassOf", "classes": ["Analysis", "Agent"]})
    assert G._disjoint_conflict(onto, "Task", "Process") == "Agent and Process are disjoint"
    # a clash that existed before is not blamed on an unrelated new edge
    onto["classes"].append(cls("Robot", "Agent"))
    onto["axioms"].append({"type": "SubClassOf", "classes": ["Robot", "Process"]})
    assert G._disjoint_conflict(onto, "Robot", "Task") == ""          # Robot clashed before; nothing new


def test_renamed_or_list_valued_names_from_the_modules_keep_their_references():
    sid, s = wine_project([{"name": "Wine"}])
    mod = module("Wine", [("Wine", None), ("Wine_Region", None), ("Qualitätswein", ["Wine", "Drink"])], [
        {"name": "comesFrom", "type": "ObjectProperty", "domain": ["Wine", "Dish"], "range": "Wine_Region",
         "labels": {"en": "comes from"}}])
    mod["individuals"] = [{"name": "bordeaux", "class": "Wine_Region"}]
    L.call_llm = RoutedLLM({"ontology_name": "W", "summary": "s", "license": "", "modules": [
        {"name": "Wine", "classes": [{"name": "Wine", "parent": ["Drink"], "concepts": [["c1", "c2"]], "note": "n"}]}]},
        {"Wine": mod})
    r = generate(sid)
    assert r.status_code == 200, r.text
    d = r.json()
    by = {c["name"]: c for c in d["ontology"]["classes"]}
    assert "WineRegion" in by and "Wine_Region" not in by and d["modular_report"]["placeholder_classes"] == []
    assert by["Qualitaetswein"]["parent"] == "Wine"                       # umlaut kept, first of a list of parents
    prop = next(p for p in d["ontology"]["properties"] if p["name"] == "comesFrom")
    assert (prop["domain"], prop["range"]) == ("Wine", "WineRegion")
    assert d["ontology"]["individuals"][0]["class"] == "WineRegion"


def test_core_relations_get_feedback_after_a_generation_and_the_proposal_asks_for_upper_layer_relations():
    import relations as R
    sid, s = wine_project([{"name": "Wine"}])
    vocab = [{"name": "goesWellWith", "domain": "Wine", "range": "Dish", "inverse": {"name": "isPairedWith"}},
             {"name": "hasPart", "domain": "", "range": "", "inverse": None}]
    cls = lambda n, p=None, **kw: {"name": n, "parent": p, **kw}
    obj = lambda n, d, r, sup=None, module="Wine": {"name": n, "type": "ObjectProperty", "domain": d, "range": r,
                                                    "sub_property_of": sup, "module": module}
    s["ontology"] = {"modules": [], "individuals": [], "axioms": [], "classes": [
        cls("Quality", layer="upper"), cls("Process", layer="upper"), cls("Wine"), cls("Dish"),
        cls("Scope", "Quality"), cls("Clarity", "Quality"), cls("Level", "Quality"), cls("Tasting", "Process")],
        "properties": [obj("goesWellWith", "Wine", "Dish", module="CoreRelations"),
                       obj("isPairedWith", "Dish", "Wine", module="CoreRelations"),
                       obj("hasPart", None, None, module="CoreRelations"),
                       obj("pairsRedWithFish", "Wine", "Dish", "isPairedWith"),       # below the inverse counts too
                       obj("hasScope", "Wine", "Scope"), obj("hasClarity", "Wine", "Clarity"),
                       obj("hasLevel", "Dish", "Level"), obj("observedIn", "Wine", "Tasting")]}
    u = R.core_usage(s["ontology"], vocab)
    assert u["below"] == {"goesWellWith": 1} and u["unused"] == ["hasPart"] and u["without_core"] == 4
    assert u["groups"] == [{"upper": "Quality", "relations": ["hasClarity", "hasLevel", "hasScope"]}]   # Process: only 1
    r = client.get(f"/api/properties/usage?session_id={sid}").json()
    assert r == {"available": False}                                        # no approved core relations
    s["property_vocab"] = {"status": "approved", "basis": "plan", "relations": vocab}
    r = client.get(f"/api/properties/usage?session_id={sid}").json()
    assert r["available"] and r["groups"][0]["upper"] == "Quality"
    system = R.build_core_vocab_prompt(s)[0]["content"]
    assert "8. A core relation is general enough" in system and 'propose "has quality" with range Quality' in system
    s["context"] = {"use_upper_layer": False}
    assert "9. The upper layer" not in R.build_core_vocab_prompt(s)[0]["content"]


def test_a_plan_without_modules_is_reported():
    sid, s = wine_project()
    L.call_llm = RoutedLLM({"summary": "I cannot plan this."}, {})
    r = generate(sid)
    assert r.status_code == 502 and "The plan contains no modules" in r.json()["detail"]


def test_long_data_previews_are_cut_in_the_prompts():
    sid, s = wine_project()
    s["data_preview"] = "x" * (G.DATA_PROMPT_LIMIT + 500)
    block = G._data_block(s)
    assert block.endswith("[... data preview truncated]") and len(block) < G.DATA_PROMPT_LIMIT + 200
    s["data_preview"] = ""
    assert G._data_block(s) == ""
