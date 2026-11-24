"""Tests for the documentation export: one chapter per module with diagram, classes, definitions and sources
(DECISIONS 114). Run with `pytest tests/test_documentation.py`."""


import app as A
import documentation as D
from corpus import concept_key
from fastapi.testclient import TestClient
from helpers import base
client = TestClient(A.app)


def project():
    onto = base()
    onto["summary"] = "Tasks and the data they use."
    onto["modules"].append({"name": "UpperLayer", "key_notion": "UpperLayer", "documentation": "upper"})
    onto["classes"][0]["parent"] = "Process"
    onto["classes"][0]["inventory_concepts"] = ["task"]
    onto["classes"][0]["sources"] *= 2                               # a source cited twice is listed once
    onto["classes"][2]["description"] = "A collection of <records>."   # escaped in HTML
    onto["classes"].append({"name": "Process", "labels": {"en": "process"}, "description": "Something that happens.",
                            "parent": None, "module": "UpperLayer", "layer": "upper"})
    onto["axioms"].append({"type": "SubClassOf", "classes": ["LowLevelTask", "prov:Activity"], "module": "Tasks"})
    sid = client.post("/api/session/create").json()["session_id"]
    s = A.sessions[sid]
    s["ontology"] = onto
    s["momo"]["competency_questions"] = [{"question": "Which tasks use which data?"}]
    s["corpus"] = {"docs": [{"id": "d1", "name": "a.pdf", "card": {"title": "Visualization Analysis",
                                                                    "authors": "Munzner, T.", "year": "2014"}}],
                   "inventory": {"themes": [], "relations": [], "taxonomies": [], "concepts": [
                       {"id": "c1", "label": "task", "variants": ["Task"], "papers": 2, "sources": [
                           {"doc": "d1", "term": "task", "definition": "What a user wants to do.", "page": 7,
                            "quote": "a task is what users want to do", "quote_ok": True},
                           {"doc": "d1", "term": "goal", "definition": "An aim.", "quote": "unverified", "quote_ok": False}]},
                       {"id": "c2", "label": "pitfall", "variants": [], "papers": 2, "sources": []}]}}
    s["gap_decisions"] = {concept_key("pitfall"): "generic research vocabulary"}
    s["gap_hierarchy_decisions"] = {"datasetisakindoftask": {"item": "Dataset is a kind of Task",
                                                             "reason": "data are used by tasks"}}
    s["evaluation"] = {"evaluated_at": "2026-10-28T10:00:00+00:00", "iteration": 2,
                       "cq": {"total": 1, "full": 1, "partial": 0, "none": 0,
                              "questions": [{"question": "Which tasks use which data?", "level": "full"}]}}
    return sid, s


def test_the_documentation_has_a_chapter_per_module_with_classes_definitions_and_sources():
    sid, s = project()
    doc = D.build_documentation(s)
    assert [m["name"] for m in doc["modules"]] == ["Tasks", "Data"]               # the upper layer is its own section
    assert [c["name"] for c in doc["upper"]] == ["Process"]
    task = next(c for c in doc["modules"][0]["classes"] if c["name"] == "Task")
    assert task["sources"] == ["Munzner, 2014: Visualization Analysis"]
    assert [x["term"] for x in task["literature"]] == ["task", "goal"]           # verified quote first
    md = D.to_markdown(doc)
    assert md.startswith("# Test\n\n*Documentation generated on ")
    assert "## 1. Module Tasks" in md and "## 2. Module Data" in md and "Module UpperLayer" not in md
    assert '> **task**: What a user wants to do. - "a task is what users want to do" (Munzner, 2014: Visualization ' \
           'Analysis, p. 7)' in md
    assert "unverified" not in md                                                 # unverified quotes are left out
    assert "- Superclass: `Process`" in md and "- Superclass: `Task`, `prov:Activity`" in md
    assert "```mermaid\nclassDiagram\n  direction LR" in md and "  Task <|-- LowLevelTask" in md
    assert '  class prov_Activity["prov:Activity"]' in md and "  Task --> Dataset : usesData" in md
    assert "- `LowLevelTask`" in md and "- `Task` (below `Process`)" in md     # the tree
    assert "| `usesData` | object | Task -> Dataset |" in md
    assert "Which tasks use which data? - *answered*" in md and "Competency questions: 1 answered in full" in md
    assert "| pitfall | 2 | generic research vocabulary |" in md
    assert "| Dataset is a kind of Task | data are used by tasks |" in md
    assert "## References\n\n- Munzner, 2014: Visualization Analysis" in md
    page = D.to_html(doc)
    assert page.startswith("<!doctype html>") and "A collection of &lt;records&gt;." in page
    assert '<a href="#c-Task"><code>Task</code></a>' in page and 'id="m-Tasks"' in page
    assert D.MERMAID_SRC in page and "useMaxWidth: false" in page


def test_classes_without_a_listed_module_and_decisions_on_variants_are_documented():
    sid, s = project()
    s["ontology"]["classes"] += [{"name": "Loose", "labels": {"en": "loose"}, "description": "", "parent": None},
                                 {"name": "Loaded", "labels": {"en": "loaded"}, "description": "", "parent": None,
                                  "module": "Imported"}]
    inv = s["corpus"]["inventory"]["concepts"]
    inv += [{"id": "c3", "label": "bias", "variants": ["cognitive bias"], "papers": 3, "sources": []},
            {"id": "c4", "label": "dataset", "variants": [], "papers": 2, "sources": []}]
    s["gap_decisions"].update({concept_key("cognitive bias"): "out of scope", concept_key("dataset"): "later"})
    doc = D.build_documentation(s)
    assert [m["name"] for m in doc["modules"]] == ["Tasks", "Data", "Imported", "Without a module"]
    assert doc["counts"]["modules"] == 2 and [c["name"] for c in doc["modules"][3]["classes"]] == ["Loose"]
    # a decision on a variant counts; a concept that is a class by now is no longer listed as not modelled
    assert [x[0] for x in doc["excluded"]] == ["bias", "pitfall"]
    md = D.to_markdown(doc)
    assert "## 3. Module Imported" in md and "## 4. Classes and properties without a module" in md


def test_class_restrictions_are_documented_and_drawn():
    sid, s = project()
    s["ontology"]["restrictions"] = [{"class": "LowLevelTask", "property": "usesData", "kind": "min", "value": "Dataset",
                                      "n": 1, "module": "Tasks", "natural_language": "Every low level task uses data."}]
    doc = D.build_documentation(s)
    md = D.to_markdown(doc)
    assert "- Restrictions: Every low level task uses data. (`usesData min 1 Dataset`)" in md
    assert "  LowLevelTask ..> Dataset : usesData min 1" in md and "1 class restrictions" in md
    assert "<code>usesData min 1 Dataset</code>" in D.to_html(doc)


def test_the_documentation_is_downloaded_as_html_or_markdown():
    sid, _ = project()
    r = client.get(f"/api/session/{sid}/documentation?format=md")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/markdown")
    assert r.headers["content-disposition"] == 'attachment; filename="Test-documentation.md"'
    r = client.get(f"/api/session/{sid}/documentation")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    empty = client.post("/api/session/create").json()["session_id"]
    assert client.get(f"/api/session/{empty}/documentation").status_code == 400
