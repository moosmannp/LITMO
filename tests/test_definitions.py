"""Tests for the decided definitions (PLAN.md phase 1, DECISIONS 83). Run with `pytest tests/test_definitions.py`."""
import json


import app as A
import definitions as D
import editing as E
import generation as G
import llm as L
import momo_steps as M
import project as P
from fastapi.testclient import TestClient
from helpers import base, CFG, FakeLLM
client = TestClient(A.app)


def project():
    """A project whose inventory has two conflicts: Visualization (3 positions) and Task (2 positions)."""
    sid = client.post("/api/session/create").json()["session_id"]
    s = A.sessions[sid]
    docs = [{"id": f"d{i}", "name": f"p{i}.pdf", "status": "done",
             "card": {"title": f"Paper {i}", "authors": f"Author{i}, A.", "year": "2020"}} for i in (1, 2, 3)]
    src = lambda d, text: {"doc": d, "term": "x", "definition": text, "broader": "", "page": 1, "quote": "",
                           "quote_ok": False, "uri": ""}
    s["corpus"] = {"docs": docs, "inventory": {
        "doc_ids": ["d1", "d2", "d3"],
        "concepts": [
            {"id": "c1", "label": "Visualization", "variants": ["visualisation"], "papers": 3, "definition": "",
             "conflict": True, "sources": [src("d1", "a process"), src("d2", "an image"), src("d3", "a method")]},
            {"id": "c2", "label": "Task", "variants": [], "papers": 2, "definition": "", "conflict": True,
             "sources": [src("d1", "a goal"), src("d2", "an activity")]},
            {"id": "c3", "label": "Dataset", "variants": [], "papers": 2, "definition": "A collection of data.",
             "conflict": False, "sources": [src("d1", "data")]},
        ],
        "conflicts": [
            {"concept": "c2", "label": "Task", "issue": "goal or activity",
             "positions": [{"view": "Task is a goal.", "docs": ["d1"]}, {"view": "Task is an activity.", "docs": ["d2"]}]},
            {"concept": "c1", "label": "Visualization", "issue": "process, artifact or method",
             "positions": [{"view": "Visualization is a process.", "docs": ["d1"]},
                           {"view": "Visualization is a visual representation.", "docs": ["d2"]},
                           {"view": "Visualization is a post-hoc method.", "docs": ["d3"]}]}],
        "themes": [{"name": "Vis", "description": "", "concepts": ["c1", "c3"]}],
        "relations": [], "taxonomies": [], "competency_questions": [], "vocabularies": []}}
    s["momo"] = {"use_case": "Analysts explore data", "data_sources": "", "patterns": [],
                 "competency_questions": [{"question": "Which visualizations show a dataset?"}],
                 "key_notions": [{"name": "Vis", "description": "visual things"}, {"name": "Tasks", "description": ""}]}
    return sid, s


def decide(sid, key, decision):
    return client.post("/api/definitions/decide", json={"session_id": sid, "key": key, "decision": decision})


SPLIT = {"choice": "split", "reason": "both are needed",
         "parts": [{"name": "Visualization", "definition": "A visual representation of data."},
                   {"name": "visualization process", "definition": "The process of creating a visualization."}]}


def test_conflicts_are_listed_with_positions_and_sources():
    sid, s = project()
    d = client.get(f"/api/definitions?session_id={sid}").json()
    assert [c["concept"] for c in d["conflicts"]] == ["Visualization", "Task"]          # most sources first
    vis = d["conflicts"][0]
    assert vis["key"] == "visualization" and len(vis["positions"]) == 3
    assert vis["positions"][1]["sources"] == ["Author2, 2020: Paper 2"]
    assert d["summary"] == {"conflicts": 2, "decided": 0, "open": 0, "recommended": 0}


def test_decisions_are_validated():
    sid, s = project()
    bad = [{"choice": "position", "position": 3, "parts": [{"name": "V", "definition": "x"}]},   # no 4th position
           {"choice": "split", "parts": [{"name": "V", "definition": "x"}]},                     # one class only
           {"choice": "own", "parts": [{"name": "V", "definition": " "}]},                       # empty definition
           {"choice": "split", "parts": [{"name": "A", "definition": "x"}, {"name": "a", "definition": "y"}]},
           {"choice": "maybe"}]
    for b in bad:
        assert decide(sid, "visualization", b).status_code == 400, b
    assert decide(sid, "nothing", SPLIT).status_code == 404
    r = decide(sid, "visualization", SPLIT)
    assert r.status_code == 200
    parts = s["context"]["definition_decisions"]["visualization"]["decision"]["parts"]
    assert [p["name"] for p in parts] == ["Visualization", "VisualizationProcess"]       # names normalized
    # a class name may belong to one decision only
    r = decide(sid, "task", {"choice": "own", "parts": [{"name": "VisualizationProcess", "definition": "x"}]})
    assert r.status_code == 400 and "already used by the decision on Visualization" in r.json()["detail"]


def test_decided_definitions_reach_every_prompt_and_open_ones_do_not():
    sid, s = project()
    decide(sid, "visualization", SPLIT)
    decide(sid, "task", {"choice": "open", "reason": "does not matter here"})
    block = P.context_block(s)
    assert "**Decided definitions**" in block
    assert "Visualization -> split into 2 classes: Visualization: A visual representation of data." in block
    assert "Task ->" not in block
    summary = client.get(f"/api/definitions?session_id={sid}").json()["summary"]
    assert summary["decided"] == 2 and summary["open"] == 1
    # the context draft no longer resolves conflicts itself, but uses the decided definitions
    draft = M.build_context_draft_prompt(s)[-1]["content"]
    assert "proposed resolution" not in draft and "do not resolve them in the document" in draft
    assert "Visualization: Visualization: A visual representation of data." in draft
    decide(sid, "visualization", None)                                                  # withdraw
    assert "**Decided definitions**" not in P.context_block(s)


def test_recommendations_are_stored_apart_and_accepted_on_request():
    sid, s = project()
    L.call_llm = FakeLLM({"recommendations": [
        {"conflict": "k1", "choice": "split", "parts": SPLIT["parts"], "reason": "both appear in the questions"},
        {"conflict": "k2", "choice": "position", "position": 2, "parts": [{"name": "Task", "definition": "An activity."}],
         "reason": "the questions ask what a task uses"},
        {"conflict": "k7", "choice": "open", "reason": "unknown conflict"}]})
    r = client.post("/api/definitions/recommend", json={"session_id": sid, "llm_config": CFG}).json()
    assert r["result"]["recommended"] == 2 and r["result"]["invalid"] == 1 and r["usage"]["input_tokens"] == 100
    prompt = L.call_llm.calls[0][-1]["content"]
    assert "k1 | Visualization (3 sources)" in prompt and "  2. Visualization is a visual representation." in prompt
    by = {c["key"]: c for c in r["conflicts"]}
    assert by["task"]["decision"] is None and by["task"]["recommendation"]["position"] == 1   # 1-based in the prompt
    assert "**Decided definitions**" not in P.context_block(s)                               # not a decision yet
    r = client.post("/api/definitions/accept", json={"session_id": sid, "keys": ["task"]}).json()
    assert r["result"]["accepted"] == 1 and r["summary"]["decided"] == 1
    by = {c["key"]: c for c in r["conflicts"]}
    assert by["task"]["decision"]["accepted_recommendation"] and by["visualization"]["decision"] is None
    r = client.post("/api/definitions/accept", json={"session_id": sid}).json()                # all the rest
    assert r["summary"]["decided"] == 2
    # nothing left to recommend
    assert client.post("/api/definitions/recommend", json={"session_id": sid, "llm_config": CFG}).status_code == 400


def test_planning_creates_the_decided_classes():
    sid, s = project()
    decide(sid, "visualization", SPLIT)
    decide(sid, "task", {"choice": "position", "position": 1,
                         "parts": [{"name": "Task", "definition": "An activity a user performs."}]})
    plan = {"modules": [{"name": "Vis", "classes": [{"name": "VisualArtifact", "concepts": ["c1"]},
                                                    {"name": "Dataset", "concepts": ["c3"]}], "other": []},
                        {"name": "Tasks", "classes": [], "other": []}]}
    rep = D.apply_to_plan(plan, s)
    vis = {c["name"]: c for c in plan["modules"][0]["classes"]}
    assert rep["renamed"] == [["VisualArtifact", "Visualization"]] and vis["Visualization"]["concepts"] == ["c1"]
    assert vis["VisualizationProcess"]["concepts"] == ["c1"]                      # same module, carries the concept
    # Task was not planned at all: it goes to the first module (no theme), with its concept
    assert {"name": "Task", "concepts": ["c2"]} in plan["modules"][0]["classes"]
    assert set(rep["added"]) == {"VisualizationProcess", "Task"}
    prompt = G.build_module_prompt(s, {"name": "Vis"}, {**plan, "ontology_name": "O"}, [], "")[-1]["content"]
    assert "- DECIDED DEFINITION (by the team - use it word for word as the description): A visual representation of data." in prompt
    assert "the team split the concept 'Visualization' into the classes Visualization, VisualizationProcess" in prompt
    assert "sources disagree; the team decided" in prompt and "SOURCES DISAGREE" not in prompt


def test_generation_enforces_the_decided_definitions_and_reports_deviations():
    sid, s = project()
    decide(sid, "visualization", SPLIT)
    E.check_oops = lambda turtle: []
    plan = {"ontology_name": "Vis Onto", "summary": "s", "license": "",
            "modules": [{"name": "Vis", "classes": [{"name": "Visualization", "concepts": ["c1"]},
                                                    {"name": "Dataset", "concepts": ["c3"]}]},
                        {"name": "Tasks", "classes": [{"name": "Task", "concepts": ["c2"]}]}]}
    vis = {"module": {"name": "Vis", "documentation": "d"}, "classes": [
        {"name": "Visualization", "labels": {"en": "Visualization"}, "description": "A process that shows data.",
         "parent": None, "sources": ["d2"]},
        {"name": "VisualizationProcess", "labels": {"en": "Visualization process"},
         "description": "The process of creating a visualization.", "parent": None},
        {"name": "Dataset", "labels": {"en": "Dataset"}, "description": "A collection of data.", "parent": None}],
        "properties": [], "individuals": [], "axioms": []}
    tasks = {"module": {"name": "Tasks", "documentation": "d"}, "classes": [
        {"name": "Task", "labels": {"en": "Task"}, "description": "A goal.", "parent": None}],
        "properties": [], "individuals": [], "axioms": []}
    replies = {"Vis": vis, "Tasks": tasks}
    calls = []
    def llm_fake(cfg, messages, effort="high"):
        calls.append(messages)
        text = messages[-1]["content"]
        if "Plan the classes of every module." in text:
            return json.dumps(plan)
        return json.dumps(replies["Vis" if "**THIS module:** Vis" in text else "Tasks"])
    L.call_llm = llm_fake
    d = client.post("/api/generate", json={"session_id": sid, "domain_description": "x", "llm_config": CFG}).json()
    assert "7. A concept listed under 'Decided definitions'" in calls[0][0]["content"]
    assert "**Decided definitions**" in calls[0][-1]["content"]                     # the plan sees them
    by = {c["name"]: c for c in d["ontology"]["classes"]}
    assert by["Visualization"]["description"] == "A visual representation of data."
    assert d["definitions_report"] == {"classes": 2, "deviated": ["Visualization"], "missing": []}
    assert d["modular_report"]["decided_plan"]["classes"] == ["Visualization", "VisualizationProcess"]
    assert by["VisualizationProcess"]["inventory_concepts"] == ["Visualization"]   # planned with the concept
    assert by["Visualization"]["module"] == by["VisualizationProcess"]["module"] == "Vis"
    ev = client.post("/api/evaluate", json={"session_id": sid, "holdout": False}).json()["definitions"]
    assert ev["classes"] == 2 and ev["ok"] == 2 and ev["undecided"] == 1 and not ev["deviating"]


def test_check_and_apply_repair_an_existing_ontology():
    sid, s = project()
    s["ontology"] = base()
    s["iterations"] = 1
    decide(sid, "task", {"choice": "split", "parts": [
        {"name": "Task", "definition": "An activity a user performs."},
        {"name": "TaskGoal", "definition": "What a task is meant to achieve."}]})
    ev = D.check_definitions(s["ontology"], s)
    assert [r["class"] for r in ev["deviating"]] == ["Task"] and [r["class"] for r in ev["missing"]] == ["TaskGoal"]
    assert ev["undecided"] == 1
    d = client.post("/api/definitions/apply", json={"session_id": sid}).json()
    by = {c["name"]: c for c in d["ontology"]["classes"]}
    assert by["Task"]["description"] == "An activity a user performs."
    assert by["TaskGoal"]["module"] == "Tasks" and by["TaskGoal"]["inventory_concepts"] == ["Task"]
    assert d["iteration"] == 2 and s["feedback_log"][-1]["feedback"] == "Apply the team's decided definitions"
    assert "TaskGoal" in d["turtle"]
    ev = D.check_definitions(s["ontology"], s)
    assert ev["ok"] == 2 and not ev["deviating"] and not ev["missing"]
    assert client.post("/api/definitions/apply", json={"session_id": sid}).status_code == 400   # nothing left


def test_an_ontology_from_before_the_decision_is_matched_by_its_inventory_link():
    sid, s = project()
    onto = base()
    onto["classes"].append({"name": "VisualThing", "labels": {"en": "Visual thing"}, "description": "A process.",
                            "parent": None, "module": "Data", "inventory_concepts": ["Visualization"]})
    s["ontology"] = onto
    decide(sid, "visualization", {"choice": "position", "position": 1,
                                  "parts": [{"name": "VisualRepresentation", "definition": "A visual representation."}]})
    ops = D.definition_ops(onto, s)
    assert ops == [{"op": "update_class", "name": "VisualThing", "description": "A visual representation."}]
