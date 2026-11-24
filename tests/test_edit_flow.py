"""Flow tests for feedback, OOPS! fix and syntax fix with a simulated LLM. Run with `pytest tests/test_edit_flow.py`."""


import app as A
import editing as E
import llm as L
import ontology_io as O
from fastapi.testclient import TestClient
from helpers import base, CFG, FakeLLM
client = TestClient(A.app)
REAL_CHECK_OOPS = E.check_oops        # the tests below replace it; the reachability test needs the real one


def test_an_unreachable_oops_service_fails_fast_and_is_not_tried_again_for_a_while():
    import requests
    turtle = O.ontology_to_turtle(base())
    calls, real_post = [], E.requests.post
    def no_connection(url, data=None, headers=None, timeout=None):
        calls.append(timeout)
        raise requests.ConnectTimeout("Connection to oops.linkeddata.es timed out")
    E.requests.post, E._oops_down_until = no_connection, 0.0
    try:
        first = REAL_CHECK_OOPS(turtle)
        assert calls == [(E.OOPS_CONNECT_TIMEOUT, E.OOPS_READ_TIMEOUT)] and E.OOPS_CONNECT_TIMEOUT <= 10
        assert first[0]["code"] == "UNREACHABLE" and "cannot be reached" in first[0]["description"]
        second = REAL_CHECK_OOPS(turtle)                        # within the next minutes: no new attempt
        assert len(calls) == 1 and second[0]["code"] == "UNREACHABLE" and "next attempt after" in second[0]["description"]
        # a service that accepts the connection but answers too slowly is reported as such, and tried again next time
        E._oops_down_until = 0.0
        def slow(url, data=None, headers=None, timeout=None):
            calls.append(timeout)
            raise requests.ReadTimeout("read timed out")
        E.requests.post = slow
        assert REAL_CHECK_OOPS(turtle)[0]["code"] == "TIMEOUT" and REAL_CHECK_OOPS(turtle)[0]["code"] == "TIMEOUT"
        assert len(calls) == 3 and E._oops_down_until == 0.0
        # the OOPS! fix does not treat the unreachable service as a pitfall
        E.check_oops = lambda t: [E._unreachable("test")]
        L.call_llm = FakeLLM()
        _, _, report = E.run_oops_and_fix(turtle, base(), {}, CFG)
        assert report["total"] == 0 and not report["fix_applied"]
    finally:
        E.requests.post, E._oops_down_until, E.check_oops = real_post, 0.0, REAL_CHECK_OOPS


def test_saving_in_the_turtle_editor_keeps_the_ontology():
    onto = base()
    onto["namespace"] = "https://w3id.org/test/"                        # a slash namespace stays one
    onto["classes"][0].update(parent="schema:Thing", inventory_concepts=["task"], layer=None)
    onto["classes"][2]["parent"] = "Task"
    onto["axioms"].append({"type": "SubClassOf", "classes": ["Dataset", "schema:CreativeWork"], "module": "Data",
                           "scoped": False, "natural_language": "Every dataset is a creative work."})
    onto["axioms"].append({"type": "EquivalentClasses", "classes": ["LowLevelTask", "schema:Action"], "module": "Tasks"})
    onto["properties"][2]["sub_property_of"] = "schema:name"            # hasName: range xsd:string
    onto["restrictions"] = [{"class": "LowLevelTask", "property": "usesData", "kind": "some", "value": "Dataset", "n": None,
                          "module": "Tasks", "natural_language": "Each low-level task works on a dataset."},
                         {"class": "Task", "property": "hasName", "kind": "exactly", "value": "xsd:string", "n": 1,
                          "module": "Tasks", "natural_language": "A task has exactly one name."}]
    sid = new_session(onto)
    before = A.sessions[sid]["ontology"]
    turtle = client.post("/api/export", json={"session_id": sid}).json()["turtle"]
    r = client.post("/api/update-turtle", json={"session_id": sid, "turtle": turtle})
    assert r.status_code == 200, r.text
    after = A.sessions[sid]["ontology"]
    assert [m["name"] for m in after["modules"]] == [m["name"] for m in before["modules"]]
    assert after["modules"][0]["key_notion"] == "Task" and after["namespace"] == "https://w3id.org/test/"
    by = lambda o, k: {x["name"]: x for x in o[k]}
    for name, c in by(before, "classes").items():
        a_ = by(after, "classes")[name]
        assert (a_["parent"], a_.get("module"), a_.get("sources") or [], a_.get("see_also") or []) == \
            (c["parent"], c["module"], c.get("sources") or [], c.get("see_also") or []), name
    assert by(after, "classes")["Task"]["inventory_concepts"] == ["task"]
    for name, p_ in by(before, "properties").items():
        a_ = by(after, "properties")[name]
        assert (a_["domain"], a_["range"], a_.get("inverse_of"), a_.get("sub_property_of"), a_["module"]) == \
            (p_["domain"], p_["range"], p_.get("inverse_of"), p_.get("sub_property_of"), p_["module"]), name
    key = lambda a: (a["type"], tuple(a["classes"]) if a["type"] == "SubClassOf" else tuple(sorted(a["classes"])))
    assert sorted(map(key, after["axioms"])) == sorted(map(key, before["axioms"]))
    assert next(a for a in after["axioms"] if a["type"] == "SubClassOf")["natural_language"] == \
        "Every dataset is a creative work."
    assert [(i["name"], i["class"]) for i in after["individuals"]] == [("taskExample", "LowLevelTask")]
    assert sorted(after["restrictions"], key=str) == sorted(before["restrictions"], key=str)     # with their readings
    assert ":Task a owl:Class" in r.json()["turtle"]                          # the server's own export ... and "schema:Thing" in r.json()["turtle"]
    # ... and saving that again changes nothing
    client.post("/api/update-turtle", json={"session_id": sid, "turtle": r.json()["turtle"]})
    assert A.sessions[sid]["ontology"]["classes"] == after["classes"] and A.sessions[sid]["ontology"]["axioms"] == after["axioms"]


def test_a_loaded_ontology_keeps_external_terms_and_unknown_prefixes():
    sid = new_session({})
    A.sessions[sid]["cq_test_report"] = {"iteration": 0, "result": {}}      # of the previous ontology (T12)
    ttl = """@prefix : <https://example.org/p#> .
@prefix ex2: <https://example.org/other#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
<https://example.org/p> a owl:Ontology .
:Bob a owl:NamedIndividual , :Person .
:Person a owl:Class ; rdfs:subClassOf ex2:Agent .
:age a owl:DatatypeProperty ; rdfs:domain :Person ; rdfs:range xsd:integer .
ex2:Agent owl:disjointWith :Place .
:Place a owl:Class ."""
    r = client.post(f"/api/load-ontology?session_id={sid}", files={"file": ("p.ttl", ttl.encode(), "text/turtle")})
    assert r.status_code == 200, r.text
    o = A.sessions[sid]["ontology"]
    assert {c["name"]: c["parent"] for c in o["classes"]} == {"Person": "ex2:Agent", "Place": None}
    assert o["properties"][0]["range"] == "xsd:integer" and o["individuals"] == [
        {"name": "Bob", "class": "Person", "labels": {"en": "Bob"}}]
    assert o["axioms"] == [{"type": "DisjointClasses", "classes": ["Place", "ex2:Agent"]}]
    assert A.sessions[sid]["custom_prefixes"]["ex2"] == "https://example.org/other#"
    assert "@prefix ex2: <https://example.org/other#>" in r.json()["turtle"]
    assert "cq_test_report" not in A.sessions[sid]


def new_session(onto=None):
    sid = client.post("/api/session/create").json()["session_id"]
    A.sessions[sid]["ontology"] = onto if onto is not None else base()
    return sid


def feedback(sid, text, llm):
    L.call_llm = llm
    E.check_oops = lambda turtle: []
    return client.post("/api/feedback", json={"session_id": sid, "feedback": text, "llm_config": CFG})


def cls(onto, name):
    return next(c for c in onto["classes"] if c["name"] == name)


def test_feedback_applies_operations_and_keeps_everything_else():
    sid = new_session()
    llm = FakeLLM({"summary": "Dataset gets a better description.",
                   "ops": [{"op": "update_class", "name": "Dataset", "description": "A table of records."}]})
    r = feedback(sid, "Describe the dataset better", llm)
    assert r.status_code == 200, r.text
    d = r.json()
    assert cls(d["ontology"], "Dataset")["description"] == "A table of records."
    assert cls(d["ontology"], "Task")["sources"] and d["edit_report"]["summary"].startswith("Dataset")
    assert len(llm.calls) == 1
    prompt = llm.calls[0][1]["content"]
    assert "## Tasks" in prompt and "**Request:**\nDescribe the dataset better" in prompt
    assert '"classes"' not in prompt                       # a listing, not the ontology JSON
    assert d["usage"]["calls"][0]["step"] == "Refinement"
    assert A.sessions[sid]["feedback_log"][0]["feedback"] == "Describe the dataset better"
    assert "history" not in A.sessions[sid]


def test_rejected_operations_are_sent_back_once():
    sid = new_session()
    llm = FakeLLM({"summary": "s", "ops": [{"op": "add_class", "name": "Goal", "parent": "Taks", "module": "Tasks"},
                                           {"op": "update_class", "name": "Dataset", "description": "x"}]},
                  {"summary": "fixed", "ops": [{"op": "add_class", "name": "Goal", "parent": "Task", "module": "Tasks"}]})
    d = feedback(sid, "Add a Goal class", llm).json()
    assert len(llm.calls) == 2
    assert "could not apply" in llm.calls[1][-1]["content"] and "reason: unknown class: Taks" in llm.calls[1][-1]["content"]
    assert cls(d["ontology"], "Goal")["parent"] == "Task"
    assert len(d["edit_report"]["applied"]) == 2 and not d["edit_report"]["rejected"]
    assert [c["step"] for c in d["usage"]["calls"]] == ["Refinement", "Refinement (corrections)"]


def test_all_rejected_leaves_the_ontology_unchanged():
    sid = new_session()
    bad = {"summary": "s", "ops": [{"op": "remove_class", "name": "Ghost"}]}
    r = feedback(sid, "Remove the ghost", FakeLLM(bad, {"summary": "no", "ops": [{"op": "remove_class", "name": "Ghost"}]}))
    assert r.status_code == 422 and "unchanged" in r.json()["detail"]
    assert A.sessions[sid]["ontology"] == base()
    assert not A.sessions[sid].get("feedback_log")


def test_empty_operations_mean_no_change():
    sid = new_session()
    r = feedback(sid, "Is everything fine?", FakeLLM({"summary": "Nothing to change.", "ops": []}))
    assert r.status_code == 200 and r.json()["ontology"]["classes"] == base()["classes"]
    assert r.json()["edit_report"]["operations"] == 0


def test_answer_without_ops_list_is_an_error():
    sid = new_session()
    r = feedback(sid, "x", FakeLLM({"classes": []}))
    assert r.status_code == 500 and "no list of operations" in r.json()["detail"]


def test_earlier_requests_and_attachments_reach_the_next_prompt():
    sid = new_session()
    feedback(sid, "Prefer the term Goal over Aim", FakeLLM({"summary": "ok", "ops": [
        {"op": "add_class", "name": "Goal", "parent": "Task", "module": "Tasks"}]}))
    A.sessions[sid]["data_files"] = [{"name": "notes.txt", "kind": "text", "summary": "short",
                                      "full_text": "FULL TEXT OF THE NOTES", "suffix": " (feedback attachment)"}]
    llm = FakeLLM({"summary": "ok", "ops": []})
    feedback(sid, "Use the attached notes", llm)
    prompt = llm.calls[0][1]["content"]
    assert "Prefer the term Goal over Aim" in prompt and "FULL TEXT OF THE NOTES" in prompt
    llm2 = FakeLLM({"summary": "ok", "ops": []})
    feedback(sid, "Again", llm2)
    assert "FULL TEXT OF THE NOTES" not in llm2.calls[0][1]["content"]       # attachments are used once


def test_questions_without_change_are_not_logged_as_change_requests():
    sid = new_session()
    feedback(sid, "Is the hierarchy fine?", FakeLLM({"summary": "Yes.", "ops": []}))
    assert not A.sessions[sid].get("feedback_log")


def test_attachments_are_kept_when_the_round_fails():
    sid = new_session()
    A.sessions[sid]["data_files"] = [{"name": "notes.txt", "kind": "text", "full_text": "NOTES",
                                      "suffix": " (feedback attachment)"}]
    r = feedback(sid, "x", FakeLLM("not json at all"))
    assert r.status_code == 500 and not A.sessions[sid]["data_files"][0].get("used")
    llm = FakeLLM({"summary": "ok", "ops": [{"op": "update_class", "name": "Task", "description": "y"}]})
    feedback(sid, "use the notes", llm)
    assert "NOTES" in llm.calls[0][1]["content"] and A.sessions[sid]["data_files"][0]["used"]


def test_invented_provenance_is_dropped_but_requested_one_kept():
    sid = new_session()
    llm = FakeLLM({"summary": "s", "ops": [
        {"op": "add_class", "name": "Goal", "module": "Tasks", "sources": ["Invented, 2020: A Paper That Does Not Exist"],
         "see_also": ["https://invented.org/Goal"]},
        {"op": "update_class", "name": "Task", "sources": ["Munzner, 2014: Visualization Analysis", "Shneiderman, 1996: The Eyes Have It"]}]})
    d = feedback(sid, "Task is also defined by Shneiderman, 1996: The Eyes Have It", llm).json()
    assert cls(d["ontology"], "Goal").get("sources") == [] and cls(d["ontology"], "Goal").get("see_also") == []
    assert cls(d["ontology"], "Task")["sources"] == ["Munzner, 2014: Visualization Analysis", "Shneiderman, 1996: The Eyes Have It"]
    assert len(d["edit_report"]["dropped_provenance"]) == 2


def test_unknown_prefix_is_rejected_in_feedback():
    sid = new_session()
    llm = FakeLLM({"summary": "s", "ops": [{"op": "update_class", "name": "Task", "parent": "foo:Bar"}]},
                  {"summary": "s", "ops": [{"op": "update_class", "name": "Task", "parent": "prov:Activity"}]})
    d = feedback(sid, "Task is a kind of activity", llm).json()
    assert "unknown prefix" in llm.calls[1][-1]["content"]
    assert cls(d["ontology"], "Task")["parent"] == "prov:Activity"
    assert "prov:Activity a owl:Class" in d["turtle"] and O.validate_turtle(d["turtle"])[0]


def test_oops_fix_uses_operations_and_rechecks():
    sid = new_session()
    session = A.sessions[sid]
    pitfall = {"code": "P10", "name": "Missing disjointness", "description": "d", "importance": "important",
               "count": 2, "affected": ["https://example.org/t#LowLevelTask"]}
    calls = {"n": 0}
    def oops(turtle):
        calls["n"] += 1
        return [pitfall] if calls["n"] == 1 else []
    E.check_oops = oops
    llm = FakeLLM({"summary": "disjoint", "ops": [{"op": "add_axiom", "type": "DisjointClasses",
                                                     "classes": ["LowLevelTask", "Dataset"], "scoped": True}]})
    L.call_llm = llm
    onto = session["ontology"]
    turtle = O.ontology_to_turtle(onto)
    fixed, turtle2, report = E.run_oops_and_fix(turtle, onto, session, A.LLMConfig(**CFG))
    assert report["fix_applied"] and report["fixed"][0]["code"] == "P10" and report["still_unfixed"] == 0
    assert report["fix_changes"] == ["added axiom DisjointClasses(LowLevelTask, Dataset)"]
    assert len(fixed["axioms"]) == 2 and "AllDisjointClasses" in turtle2
    assert "Missing disjointness" in llm.calls[0][1]["content"] and "LowLevelTask" in llm.calls[0][1]["content"]


def test_oops_fix_with_nothing_applicable_is_reported():
    sid = new_session()
    E.check_oops = lambda turtle: [{"code": "P11", "name": "n", "description": "", "importance": "critical",
                                    "count": 1, "affected": []}]
    L.call_llm = FakeLLM({"summary": "s", "ops": [{"op": "update_class", "name": "Ghost", "description": "x"}]},
                         {"summary": "s", "ops": []})
    session = A.sessions[sid]
    fixed, _, report = E.run_oops_and_fix(O.ontology_to_turtle(session["ontology"]), session["ontology"], session,
                                          A.LLMConfig(**CFG))
    assert fixed is None and "no applicable change" in report["fix_error"] and not report["fix_applied"]


def test_invalid_names_are_fixed_without_the_model():
    onto = base()
    onto["classes"].append({"name": "Visual Encoding", "labels": {"en": "Visual encoding"}, "parent": "Task", "module": "Tasks"})
    sid = new_session(onto)
    session = A.sessions[sid]
    turtle = O.ontology_to_turtle(onto)
    assert not O.validate_turtle(turtle)[0]
    llm = FakeLLM()
    L.call_llm = llm
    fixed, turtle2, report = E.validate_and_fix_turtle(turtle, onto, session, A.LLMConfig(**CFG))
    assert report["valid"] and report["fixed"] and report["renamed"] == [{"old": "Visual Encoding", "new": "VisualEncoding"}]
    assert not llm.calls and O.validate_turtle(turtle2)[0] and cls(fixed, "VisualEncoding")["parent"] == "Task"


def test_syntax_error_the_renaming_cannot_fix_goes_to_the_model_as_operations():
    onto = base()
    onto["properties"][0]["domain"] = "Task Broken Domain"       # an invalid reference, not a name
    sid = new_session(onto)
    session = A.sessions[sid]
    turtle = O.ontology_to_turtle(onto)
    assert not O.validate_turtle(turtle)[0]
    llm = FakeLLM({"summary": "domain", "ops": [{"op": "update_property", "name": "usesData", "domain": "Task"}]})
    L.call_llm = llm
    fixed, turtle2, report = E.validate_and_fix_turtle(turtle, onto, session, A.LLMConfig(**CFG))
    assert report["valid"] and report["fixed"] and fixed["properties"][0]["domain"] == "Task"
    assert "syntax error" in llm.calls[0][1]["content"]
