"""Tests for the project picker: listing and renaming the saved projects. Run with `pytest tests/test_projects.py`."""


import app as A
from fastapi.testclient import TestClient
from helpers import base
client = TestClient(A.app)


def test_a_session_with_a_lone_surrogate_is_saved_and_does_not_block_the_others():
    import json
    import store
    A.sessions.clear()
    broken = new_project("PDF text with a broken character \ud83d here")
    fine = new_project("A second project")
    store.save_dirty_sessions()
    saved = json.loads((store.SESSION_DIR / f"{broken}.json").read_text(encoding="ascii"))
    assert saved["momo"]["use_case"] == A.sessions[broken]["momo"]["use_case"]   # unchanged, as an escape
    assert (store.SESSION_DIR / f"{fine}.json").exists()


def test_text_with_lone_surrogates_does_not_break_the_project_list():
    sid = client.post("/api/session/create").json()["session_id"]
    A.sessions[sid]["title"] = "broken \ud800 text"
    A.sessions[sid]["momo"]["use_case"] = "from a pdf \udc80"
    assert client.get("/api/sessions").status_code == 200
    r = client.get(f"/api/session/{sid}")
    assert r.status_code == 200 and r.json()["project"]["momo"]["use_case"] == "from a pdf \udc80"


def test_the_page_and_its_scripts_are_revalidated():
    for path in ("/app", "/js/main.js"):
        r = client.get(path)
        assert r.status_code == 200 and r.headers["cache-control"] == "no-cache", path


def test_other_web_pages_get_no_cors_permission():
    A.sessions.clear()
    r = client.get("/api/sessions", headers={"Origin": "https://some-other-site.example"})
    assert "access-control-allow-origin" not in r.headers           # the page itself is same-origin


def test_singular_and_plural_get_one_concept_key_and_stored_decisions_are_migrated():
    from corpus import concept_key, migrate_concept_keys
    for one, many in [("metric", "Metrics"), ("topic", "topics"), ("cognitive bias", "Cognitive biases"),
                      ("analysis", "analyses"), ("axis", "axes"), ("status", "statuses"), ("index", "indices")]:
        assert concept_key(one) == concept_key(many), (one, many)
    assert [concept_key(w) for w in ("ideas", "cases", "uses", "VisualEncodings")] == ["idea", "case", "use", "visual encoding"]
    session = {"corpus": {"inventory": {"concepts": [
                   {"id": "c1", "label": "Cognitive biases", "variants": ["cognitive bias"]},
                   {"id": "c2", "label": "Metrics", "variants": []}]}},
               "gap_decisions": {"cognitive bia": "r1", "cognitive biase": "r2", "pitfall": "r3"},
               "context": {"definition_decisions": {"metrics": {"concept": "Metrics", "decision": {"choice": "open"}}}}}
    assert migrate_concept_keys(session) == 3
    assert session["gap_decisions"] == {"cognitive bias": "r1", "pitfall": "r3"}     # both old keys of one concept
    assert list(session["context"]["definition_decisions"]) == ["metric"]
    assert migrate_concept_keys(session) == 0                                     # once per project
    sid = client.post("/api/session/create").json()["session_id"]
    assert migrate_concept_keys(A.sessions[sid]) == 0                              # new projects use the new key


def new_project(use_case="", ontology=None):
    sid = client.post("/api/session/create").json()["session_id"]
    A.sessions[sid]["momo"]["use_case"] = use_case
    A.sessions[sid]["ontology"] = ontology
    return sid


def test_projects_are_listed_with_title_and_size_and_empty_ones_only_when_open():
    A.sessions.clear()
    gen = new_project("Describe wines and dishes", base())
    A.sessions[gen]["iterations"] = 3
    draft = new_project("A wine shop wants to help its customers choose a wine for every dish on the menu of the week")
    empty = new_project()
    client.post("/api/momo/save", json={"session_id": draft, "use_case": A.sessions[draft]["momo"]["use_case"],
                                        "data_sources": "", "competency_questions": [], "key_notions": [],
                                        "patterns": []})            # a modifying request: the middleware saves
    listed = client.get(f"/api/sessions?current={empty}").json()["projects"]
    by = {p["session_id"]: p for p in listed}
    assert set(by) == {gen, draft, empty}
    assert by[gen]["title"] == "Test" and by[gen]["iteration"] == 3 and by[gen]["classes"] == 3 and by[gen]["modules"] == 2
    assert by[draft]["title"] == "A wine shop wants to help its customers choose a wine for …"
    assert by[empty]["current"] and by[empty]["title"] == "Untitled project" and by[empty]["updated"] is None
    assert by[draft]["updated"] is not None
    assert listed[0]["session_id"] == empty                      # not saved yet: first
    assert empty not in {p["session_id"] for p in client.get("/api/sessions").json()["projects"]}


def test_a_project_can_get_its_own_title_and_lose_it_again():
    A.sessions.clear()
    sid = new_project("Describe wines", base())
    assert client.post("/api/session/rename", json={"session_id": sid, "title": "  Wine   run 1 "}).json()["title"] == "Wine run 1"
    p = client.get("/api/sessions").json()["projects"][0]
    assert p["title"] == "Wine run 1" and p["named"] and p["use_case"] == "Describe wines"
    assert client.post("/api/session/rename", json={"session_id": sid, "title": ""}).json()["title"] == "Test"
    assert client.post("/api/session/rename", json={"session_id": "nope", "title": "x"}).status_code == 404
