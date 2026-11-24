"""Helpers the test files share: the example ontology, a simulated model and its configuration."""
import json

import app as A
import llm as L

CFG = {"provider": "anthropic", "api_key": "x", "model": "claude-opus-5-5"}


def base():
    return {
        "ontology_name": "Test", "namespace": "https://example.org/t#", "license": "https://creativecommons.org/licenses/by/4.0/",
        "modules": [{"name": "Tasks", "key_notion": "Task", "pattern": None, "documentation": "d"},
                    {"name": "Data", "key_notion": "Data", "pattern": None, "documentation": "d"}],
        "classes": [
            {"name": "Task", "labels": {"en": "Task"}, "description": "A goal.", "parent": None, "module": "Tasks",
             "sources": ["Munzner, 2014: Visualization Analysis"], "see_also": ["https://example.org/o#Task"]},
            {"name": "LowLevelTask", "labels": {"en": "Low level task"}, "description": "x", "parent": "Task", "module": "Tasks"},
            {"name": "Dataset", "labels": {"en": "Dataset"}, "description": "x", "parent": None, "module": "Data"},
        ],
        "properties": [
            {"name": "usesData", "type": "ObjectProperty", "domain": "Task", "range": "Dataset", "inverse_of": "usedByTask",
             "labels": {"en": "uses data"}, "description": "", "module": "Tasks"},
            {"name": "usedByTask", "type": "ObjectProperty", "domain": "Dataset", "range": "Task", "inverse_of": "usesData",
             "labels": {"en": "used by"}, "description": "", "module": "Data"},
            {"name": "hasName", "type": "DatatypeProperty", "domain": "Task", "range": "xsd:string", "inverse_of": None,
             "labels": {"en": "has name"}, "description": "", "module": "Tasks"},
        ],
        "individuals": [{"name": "taskExample", "class": "LowLevelTask", "labels": {"en": "example"}}],
        "axioms": [{"type": "DisjointClasses", "classes": ["Task", "Dataset"], "module": "Tasks", "scoped": False,
                    "natural_language": "x"}],
    }


class FakeLLM:
    """Answers successive calls from a list of JSON-able replies and records the prompts."""
    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, cfg, messages, effort="high"):
        self.calls.append(messages)
        L._record_usage(100, 10)
        if not self.replies:
            raise AssertionError("unexpected LLM call")
        r = self.replies.pop(0)
        return r if isinstance(r, str) else json.dumps(r)


def cq_reply(n, ok_query, sample=":t1 a :Task ; :usesData :d1 . :d1 a :Dataset ."):
    tests = [{"cq": 1, "sparql": ok_query}]
    tests += [{"cq": i, "sparql": None, "missing": "nothing models this"} for i in range(2, n + 1)]
    return {"sample_data": sample, "tests": tests}


def gap_inventory():
    return {"concepts": [
        {"id": "c1", "label": "Task", "variants": [], "papers": 4, "definition": "", "sources": []},
        {"id": "c2", "label": "Low-level task", "variants": [], "papers": 3, "definition": "",
         "sources": [{"doc": "d1", "definition": "a primitive task", "broader": "task", "uri": ""}]},
        {"id": "c3", "label": "Glyph", "variants": [], "papers": 2, "definition": "A composite mark.",
         "sources": [{"doc": "d1", "definition": "a mark", "broader": "Dataset", "uri": ""}]},       # attachable
        {"id": "c4", "label": "Encode", "variants": [], "papers": 2, "definition": "", "sources": []},  # in a property
        {"id": "c5", "label": "Brushing", "variants": [], "papers": 2, "definition": "linked selection",
         "sources": [{"doc": "d2", "definition": "x", "broader": "", "uri": ""}]},
        {"id": "c6", "label": "Overview", "variants": [], "papers": 1, "definition": "", "sources": []},
    ], "themes": [], "competency_questions": [],
       "taxonomies": [{"name": "Tasks", "categories": ["low-level task", "high level task", "goal"], "doc": "d1"}]}


def property_onto():
    onto = base()
    onto["properties"] += [
        {"name": "usesSample", "type": "ObjectProperty", "domain": "LowLevelTask", "range": "Dataset",
         "inverse_of": "sampleUsedBy", "labels": {"en": "uses sample"}, "description": "", "module": "Tasks"},
        {"name": "sampleUsedBy", "type": "ObjectProperty", "domain": "Dataset", "range": "LowLevelTask",
         "inverse_of": "usesSample", "labels": {"en": "sample used by"}, "description": "", "module": "Data"},
        {"name": "describesTask", "type": "ObjectProperty", "domain": "Dataset", "range": "Task", "inverse_of": None,
         "labels": {"en": "describes task"}, "description": "", "module": "Data"}]
    return onto


PROVLIKE_TTL = """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix pl: <https://w3id.org/pl#> .
pl:Activity a owl:Class ; rdfs:label "activity" ; rdfs:comment "Something that occurs over time." ; owl:disjointWith pl:Entity .
pl:Entity a owl:Class ; rdfs:label "entity" ; rdfs:comment "A thing with fixed aspects." .
pl:Plan a owl:Class ; rdfs:subClassOf pl:Entity .
pl:wasGeneratedBy a owl:ObjectProperty ; rdfs:domain pl:Entity ; rdfs:range pl:Activity .
"""


def align_session(client):
    sid = client.post("/api/session/create").json()["session_id"]
    s = A.sessions[sid]
    onto = base()
    onto["properties"].append({"name": "isGeneratedBy", "type": "ObjectProperty", "domain": "Dataset", "range": "Task",
                               "inverse_of": None, "labels": {"en": "is generated by"}, "description": "", "module": "Data"})
    onto["classes"].append({"name": "AnalysisActivity", "labels": {"en": "analysis activity"}, "description": "x",
                            "parent": "Task", "module": "Tasks"})
    s["ontology"], s["iterations"] = onto, 1
    client.post(f"/api/standards/upload?session_id={sid}&index=-1", files={"file": ("pl.ttl", PROVLIKE_TTL.encode(), "text/turtle")})
    return sid, s
