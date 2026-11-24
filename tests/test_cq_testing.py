"""Tests for the competency-question tests: sample data, SPARQL queries, their checks and corrections."""
from fastapi.testclient import TestClient

import app as A
import llm as L
import ontology_io as O
import testing as T
from ontology_evaluation import cq_coverage
from helpers import base, CFG, FakeLLM, cq_reply, property_onto


def test_cq_tests_keep_sample_data_and_passing_queries_between_iterations():
    turtle = O.ontology_to_turtle(base())
    q_ok = "PREFIX : <https://example.org/t#> SELECT ?d WHERE { ?t a :Task ; :usesData ?d }"
    q_new = "PREFIX : <https://example.org/t#> SELECT ?t WHERE { ?t a :LowLevelTask }"
    cqs = ["What data does a task use?", "Which low-level tasks are there?"]
    L.call_llm = FakeLLM({"sample_data": ":t1 a :Task ; :usesData :d1 . :d1 a :Dataset .",
                          "tests": [{"cq": 1, "sparql": q_ok}, {"cq": 2, "sparql": None, "missing": "x"}]})
    first = T.test_competency_questions(turtle, cqs, CFG)
    assert first["passed"] == 1 and first["reused"] == 0
    # next iteration: question 1 still passes on the old data without a model call; only question 2 goes to the
    # model, which sees the existing data and adds to it
    llm = FakeLLM({"sample_data": ":l1 a :LowLevelTask .", "tests": [{"cq": 1, "sparql": q_new}]})
    L.call_llm = llm
    second = T.test_competency_questions(turtle, cqs, CFG, previous=first)
    prompt = llm.calls[0][-1]["content"]
    assert "Existing sample data" in prompt and "usesData" in prompt and "What data does a task use?" not in prompt
    assert second["passed"] == 2 and second["reused"] == 1 and second["tests"][0]["reused"]
    assert second["tests"][1]["cq"] == 2 and second["sample_triples"] == first["sample_triples"] + 1
    # everything passes: no model call at all
    L.call_llm = FakeLLM()
    third = T.test_competency_questions(turtle, cqs, CFG, previous=second)
    assert third["passed"] == 2 and third["reused"] == 2 and third["sample_triples"] == second["sample_triples"]


def test_a_query_rdflib_cannot_evaluate_fails_only_its_own_question():
    # VA 5c, second bridge: EXISTS inside a SELECT expression parses, but rdflib fails when the rows are read -
    # that aborted the whole hold-out test, all three runs
    turtle = O.ontology_to_turtle(base())
    q_bad = ("PREFIX : <https://example.org/t#> SELECT ?t (EXISTS { ?t :usesData ?d . ?d a :Dataset } AS ?b) "
             "WHERE { ?t a :Task }")
    q_ok = "PREFIX : <https://example.org/t#> SELECT ?d WHERE { ?t a :Task ; :usesData ?d }"
    L.call_llm = FakeLLM({"sample_data": ":t1 a :Task ; :usesData :d1 . :d1 a :Dataset .",
                          "tests": [{"cq": 1, "sparql": q_bad}, {"cq": 2, "sparql": q_ok}]},
                         {"tests": []}, {"tests": []})            # a correction or check, should one be asked
    r = T.test_competency_questions(turtle, ["Does a task use a dataset?", "What data do tasks use?"], CFG)
    bad, ok = r["tests"]
    assert bad["error"].startswith("Query failed") and "CompValue" in bad["error"] and not bad["result_ok"]
    assert ok["result_ok"] and r["passed"] == 1
    # and the prompts tell the model not to write such queries (DECISIONS 136)
    assert "only inside FILTER - never in the SELECT list" in T.CQ_TEST_SYS and T.EXISTS_RULE in T.CQ_FIX_SYS


def test_sample_data_may_describe_the_ontologys_individuals_but_not_change_its_schema():
    turtle = O.ontology_to_turtle(base())                       # base has the individual taskExample
    q = "PREFIX : <https://example.org/t#> SELECT ?d WHERE { :taskExample :usesData ?d }"
    L.call_llm = FakeLLM({"sample_data": ":taskExample :usesData :d1 ; :hasName \"example\" . :d1 a :Dataset .\n"
                                         ":taskExample a owl:Class . :Task :usesData :d1 . :usesData rdfs:range :Task .",
                          "tests": [{"cq": 1, "sparql": q}]})
    r = T.test_competency_questions(turtle, ["What data does the example task use?"], CFG)
    assert r["passed"] == 1 and r["sample_triples"] == 3, r
    assert sorted(r["sample_issues"]) == [":Task: changes an ontology term instead of describing an individual",
                                          ":taskExample: changes an ontology term instead of describing an individual",
                                          ":usesData: changes an ontology term instead of describing an individual"]


def test_sample_data_of_the_wrong_class_for_a_domain_or_range_is_dropped():
    turtle = O.ontology_to_turtle(base())             # usesData: Task -> Dataset; taskExample is a LowLevelTask
    q = "PREFIX : <https://example.org/t#> SELECT ?t WHERE { ?t :usesData ?d }"
    L.call_llm = FakeLLM({"sample_data": ":d1 a :Dataset . :d2 a :Dataset . :d1 :usesData :d2 .\n"   # a dataset as user
                                         ":taskExample :usesData :d2 .\n"                              # subclass of Task: fine
                                         ":x :usesData :t9 . :t9 a :Task .",                            # untyped x, wrong range
                          "tests": [{"cq": 1, "sparql": q}]})
    r = T.test_competency_questions(turtle, ["Which tasks use data?"], CFG)
    assert r["passed"] == 1 and r["tests"][0]["rows"] == [{"t": ":taskExample"}], r
    assert sorted(r["sample_issues"]) == [":d1 is not a :Task, the domain of :usesData - triple dropped",
                                          ":t9 is not a :Dataset, the range of :usesData - triple dropped"]


def test_a_query_that_answers_only_part_of_the_question_is_partial():
    turtle = O.ontology_to_turtle(base())
    q = "PREFIX : <https://example.org/t#> SELECT ?d WHERE { ?t :usesData ?d }"
    L.call_llm = FakeLLM({"sample_data": ":t1 a :Task ; :usesData :d1 . :d1 a :Dataset .",
                          "tests": [{"cq": 1, "sparql": q, "leaves_out": "the ranking: nothing says which dataset is best"},
                                    {"cq": 2, "sparql": q, "leaves_out": "null"}]},
                         {"checks": [{"item": 1, "verdict": "missing", "reason": "the question asks which is best"}]})
    r = T.test_competency_questions(turtle, ["Which dataset is best for a task?", "What data do tasks use?"], CFG)
    first, second = r["tests"]
    assert first["status"] == "partial" and first["rows"] and "the ranking" in first["error"]
    assert first["gap_check"] == {"verdict": "missing", "reason": "the question asks which is best"}
    assert len(L.call_llm.calls) == 2 and r["sample_issues"] == []
    assert second["status"] == "passed" and second["leaves_out"] == ""
    assert r["passed"] == 1
    c = cq_coverage(r)
    assert (c["full"], c["partial"]) == (1, 1) and c["questions"][0]["level"] == "partial"
    # a partial query is not kept as a passing one: the next test asks for it again
    L.call_llm = FakeLLM({"sample_data": "", "tests": [{"cq": 1, "sparql": q, "leaves_out": "the ranking"}]},
                         {"checks": [{"item": 1, "verdict": "missing", "reason": "r"}]})
    again = T.test_competency_questions(turtle, ["Which dataset is best for a task?", "What data do tasks use?"], CFG,
                                        previous=r)
    assert again["reused"] == 1 and again["tests"][0]["status"] == "partial"


def test_a_separate_check_decides_whether_a_stated_gap_is_asked_for():
    turtle = O.ontology_to_turtle(base())
    q = "PREFIX : <https://example.org/t#> SELECT ?t ?d WHERE { ?t :usesData ?d }"
    questions = ["Which tasks use which data?", "Which dataset is best for a task?", "What data do tasks use?",
                 "Which tasks use data?"]
    L.call_llm = FakeLLM(
        {"sample_data": ":t1 a :Task ; :usesData :d1 . :d1 a :Dataset .", "tests": [
            {"cq": 1, "sparql": q, "leaves_out": "whether the data is good enough for the task"},   # a judgement
            {"cq": 2, "sparql": q, "leaves_out": "which dataset is best"},
            {"cq": 3, "sparql": q, "leaves_out": "how the data was collected"},                     # not checked below
            {"cq": 4, "sparql": q}]},
        {"checks": [{"item": 1, "verdict": "beyond", "reason": "the question asks which, not how good"},
                    {"item": 2, "verdict": "missing", "reason": "the question asks for the best one"},
                    {"item": 9, "verdict": "beyond"}, {"item": 3, "verdict": "unsure"}]})
    r = T.test_competency_questions(turtle, questions, CFG)
    assert [t["status"] for t in r["tests"]] == ["passed", "partial", "partial", "passed"] and r["passed"] == 2
    first = r["tests"][0]
    assert first["error"] == "" and first["leaves_out"] == "whether the data is good enough for the task"
    assert first["gap_check"]["reason"] == "the question asks which, not how good"
    check = L.call_llm.calls[1]
    assert "When in doubt, \"missing\"" in check[0]["content"]
    text = check[1]["content"]
    assert "Item 1. Question: Which tasks use which data?" in text and "Rows (1 in total): " in text
    assert "Stated gap: how the data was collected" in text and "Which tasks use data?" not in text   # only partials
    # the check is an addition: if it fails, the answers stay partial and the report says so
    L.call_llm = FakeLLM({"sample_data": ":t1 a :Task ; :usesData :d1 . :d1 a :Dataset .",
                          "tests": [{"cq": 1, "sparql": q, "leaves_out": "whether it is good"}]})
    r = T.test_competency_questions(turtle, questions[:1], CFG)
    assert r["tests"][0]["status"] == "partial" and "The check of partial answers failed" in r["sample_issues"][-1]


def test_a_count_of_zero_is_no_result_and_declared_prefixes_keep_their_names():
    turtle = O.ontology_to_turtle(base())
    P_ = "PREFIX : <https://example.org/t#> "
    L.call_llm = FakeLLM({"sample_data": ":t1 a :Task .", "tests": [
        {"cq": 1, "sparql": P_ + "SELECT (COUNT(?d) AS ?n) WHERE { ?t :usesData ?d }"}]})
    r = T.test_competency_questions(turtle, ["How many data sets are used?"], CFG)
    assert r["tests"][0]["status"] == "failed" and r["tests"][0]["error"] == "No result on the sample data."
    # a prefix rdflib binds itself (geo) keeps the ontology's own namespace
    geo = """@prefix : <https://example.org/g#> .
@prefix geo: <http://www.w3.org/2003/01/geo/wgs84_pos#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
:Place a owl:Class ; rdfs:subClassOf geo:SpatialThing .
geo:SpatialThing a owl:Class ."""
    L.call_llm = FakeLLM({"sample_data": ":p1 a :Place .", "tests": [{"cq": 1, "sparql":
        "PREFIX : <https://example.org/g#> PREFIX geo: <http://www.w3.org/2003/01/geo/wgs84_pos#> "
        "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> SELECT ?x WHERE { ?x a :Place . :Place rdfs:subClassOf geo:SpatialThing }"}]})
    r = T.test_competency_questions(geo, ["Which places are spatial things?"], CFG)
    assert r["tests"][0]["status"] == "passed", r["tests"][0]["error"]


def test_a_query_without_result_on_its_own_sample_data_gets_one_correction_round():
    turtle = O.ontology_to_turtle(base())
    P = "PREFIX : <https://example.org/t#> "
    chain = P + "SELECT ?t ?n WHERE { ?t :usesData ?d ; :hasName ?n }"            # no task has a name in the data
    other = P + "SELECT ?d WHERE { ?t :usesData ?d }"
    asked = P + "SELECT ?t WHERE { ?t a :LowLevelTask ; :usesData ?d }"            # no low-level task uses data
    questions = ["Which named tasks use data?", "Which data are used?", "Which low-level tasks use data?"]
    L.call_llm = FakeLLM(
        {"sample_data": ":t1 a :Task ; :usesData :d1 . :d1 a :Dataset .",
         "tests": [{"cq": 1, "sparql": chain}, {"cq": 2, "sparql": other}, {"cq": 3, "sparql": asked}]},
        {"fixes": [{"item": 1, "sample_data": ':t1 :hasName "Find outliers" .'},
                   {"item": 2, "sparql": P + "SELECT ?t WHERE { ?t a :Task ; :usesData ?d }",
                    "leaves_out": "which of the tasks are low-level tasks",
                    "sample_data": ":t2 a :Task ; this is not Turtle"}]})          # does not spoil item 1's triples
    r = T.test_competency_questions(turtle, questions, CFG)
    named, data, inverse = r["tests"]
    assert named["status"] == "passed" and named["first_error"] == "No result on the sample data." \
        and not named.get("corrected")
    assert data["status"] == "passed" and "first_error" not in data                # had a result from the start
    assert inverse["status"] == "partial" and inverse["corrected"] and "low-level tasks" in inverse["error"]
    fix = L.call_llm.calls[1]
    assert "Never answer an easier question silently" in fix[0]["content"]
    text = fix[1]["content"]
    assert "Item 1. Question: Which named tasks use data?" in text and "- :hasName: owl:DatatypeProperty, :Task -> " in text
    assert "- :LowLevelTask: owl:Class, below :Task" in text and ":d1 a :Dataset" in text
    assert "@prefix" not in text and '"Find outliers"' in r["sample_data"]
    assert any(i.startswith("Sample data of correction 2 is not valid Turtle") for i in r["sample_issues"])
    # the partial answer then goes to the check (third call): it has no reply here, so it stays partial
    assert len(L.call_llm.calls) == 3 and "The check of partial answers failed" in r["sample_issues"][-1]
    # if the correction call fails, the tests stay failed and the report says so
    L.call_llm = FakeLLM({"sample_data": ":t1 a :Task ; :usesData :d1 . :d1 a :Dataset .",
                          "tests": [{"cq": 1, "sparql": chain}]})
    r = T.test_competency_questions(turtle, questions[:1], CFG)
    assert r["tests"][0]["status"] == "failed" and "The correction of queries without result failed" in r["sample_issues"][-1]


def test_a_class_counts_as_an_answer_when_it_comes_from_the_data():
    turtle = O.ontology_to_turtle(base())             # taskExample is an individual of the ontology (LowLevelTask)
    P = "PREFIX : <https://example.org/t#> PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> "
    L.call_llm = FakeLLM({"sample_data": ":t1 a :LowLevelTask .", "tests": [
        {"cq": 1, "sparql": P + "SELECT ?c WHERE { ?c rdfs:subClassOf :Task }"},                       # schema only
        {"cq": 2, "sparql": P + "SELECT ?type WHERE { :t1 a ?type . VALUES ?type { :LowLevelTask :Task } }"},  # wine run 6
        {"cq": 3, "sparql": P + "SELECT ?type WHERE { :taskExample a ?type . VALUES ?type { :LowLevelTask } }"}]})
    r = T.test_competency_questions(turtle, ["Which kinds of task are there?", "What kind of task is t1?",
                                             "What kind of task is the example?"], CFG)
    levels = [t["status"] for t in r["tests"]]
    assert levels == ["failed", "passed", "passed"], r["tests"]
    assert "answers from the schema" in r["tests"][0]["error"]


def test_an_untyped_individual_of_the_sample_data_is_not_an_undeclared_term():
    turtle = O.ontology_to_turtle(base())
    P = "PREFIX : <https://example.org/t#> "
    L.call_llm = FakeLLM({"sample_data": ":t1 a :Task ; :usesData :d9 .", "tests": [      # :d9 has no type (wine run 7)
        {"cq": 1, "sparql": P + "SELECT ?t WHERE { ?t :usesData :d9 }"},
        {"cq": 2, "sparql": P + "SELECT ?t WHERE { ?t a :InventedClass }"}]})
    r = T.test_competency_questions(turtle, ["Which tasks use d9?", "Which invented things are there?"], CFG)
    assert r["tests"][0]["status"] == "passed", r["tests"][0]
    assert r["tests"][1]["unknown_terms"] == [":InventedClass"]


def test_cq_tests_follow_merges_and_entailments():
    ns = "https://example.org/t#"
    onto = property_onto()
    onto["properties"][3]["sub_property_of"] = "usesData"          # usesSample below usesData
    turtle = O.ontology_to_turtle(onto)
    # entailment: data stated with a subproperty, an inverse or a subclass is found by a query on the general term
    L.call_llm = FakeLLM({"sample_data": ":l1 a :LowLevelTask ; :usesSample :d1 . :d1 a :Dataset .", "tests": [
        {"cq": 1, "sparql": "SELECT ?t ?d WHERE { ?t a :Task ; :usesData ?d }"},
        {"cq": 2, "sparql": "SELECT ?d ?t WHERE { ?d :usedByTask ?t }"}]})
    r = T.test_competency_questions(turtle, ["What data does a task use?", "Which task uses this data?"], CFG)
    assert r["passed"] == 2, [t["error"] for t in r["tests"]]
    assert "usedByTask" not in r["sample_data"]                       # entailed triples are not stored as data
    # translation: usesSample merged into usesData, describesTask (no inverse) turned around into usesData
    old = {"tests": [{"question": "q1", "status": "passed", "sparql": "SELECT ?t WHERE { ?t :usesSample ?d }"},
                     {"question": "q2", "status": "passed", "sparql": f"SELECT ?d WHERE {{ ?d <{ns}describesTask> ?t }}"}],
           "sample_data": f"@prefix : <{ns}> .\n:t1 a :LowLevelTask ; :usesSample :d1 . :d2 :describesTask :t1 . :d1 a :Dataset ."}
    new, n = T.translate_cq_report(old, {"usesSample": "usesData", "describesTask": "^usesData"}, ns)
    assert n == 4 and old["tests"][0]["sparql"].endswith(":usesSample ?d }")      # the input stays as it was
    assert new["tests"][0]["sparql"] == "SELECT ?t WHERE { ?t :usesData ?d }"
    assert new["tests"][1]["sparql"] == f"SELECT ?d WHERE {{ ?d ^<{ns}usesData> ?t }}"
    assert "usesSample" not in new["sample_data"] and "describesTask" not in new["sample_data"]
    L.call_llm = FakeLLM()                                             # nothing may need the model
    onto2 = property_onto()
    onto2["properties"] = [p for p in onto2["properties"] if p["name"] not in ("usesSample", "sampleUsedBy", "describesTask")]
    r = T.test_competency_questions(O.ontology_to_turtle(onto2), ["q1", "q2"], CFG, previous=new)
    assert r["passed"] == 2 and r["reused"] == 2


def test_fresh_cq_test_ignores_the_stored_data():
    client = TestClient(A.app)
    sid = client.post("/api/session/create").json()["session_id"]
    s = A.sessions[sid]
    s["ontology"], s["iterations"] = base(), 1
    s["momo"]["competency_questions"] = [{"question": "What data does a task use?"}]
    q = "PREFIX : <https://example.org/t#> SELECT ?d WHERE { ?t a :Task ; :usesData ?d }"
    L.call_llm = FakeLLM(cq_reply(1, q))
    client.post("/api/momo/test-cqs", json={"session_id": sid, "llm_config": CFG})
    L.call_llm = FakeLLM()
    assert client.post("/api/momo/test-cqs", json={"session_id": sid, "llm_config": CFG}).json()["reused"] == 1
    L.call_llm = FakeLLM(cq_reply(1, q, sample=":t9 a :Task ; :usesData :d9 . :d9 a :Dataset ."))
    d = client.post("/api/momo/test-cqs", json={"session_id": sid, "llm_config": CFG, "fresh": True}).json()
    assert d["reused"] == 0 and ":t1" not in d["sample_data"] and len(L.call_llm.calls) == 1
    L.call_llm = FakeLLM(cq_reply(1, q), cq_reply(2, q))
    e = client.post("/api/evaluate", json={"session_id": sid, "llm_config": CFG, "fresh": True}).json()
    assert len(L.call_llm.calls) >= 1 and e["cq"]["full"] == 1
