"""Tests for the vocabularies: standards, uploads, prefixes, terms in edits and in the generation."""
import copy
import json

from fastapi.testclient import TestClient

import app as A
import editing as E
import llm as L
import ontology_io as O
import project as P
import vocabularies as V
from helpers import base, CFG, FakeLLM, align_session


VOCAB_TTL = """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <https://w3id.org/exvocab#> .
<https://w3id.org/exvocab> a owl:Ontology ; rdfs:label "Example Vocabulary"@en .
ex:Thing2 a owl:Class ; rdfs:label "thing"@en ; rdfs:comment "Anything."@en .
ex:Device a owl:Class ; rdfs:subClassOf ex:Thing2 ; rdfs:label "device"@en, "Geraet"@de .
ex:partOf a owl:ObjectProperty ; rdfs:domain ex:Device ; rdfs:range ex:Thing2 .
<http://other.org/x#Foreign> a owl:Class .
"""


SMALL_TTL = """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix sv: <https://w3id.org/sv#> .
sv:Concept a owl:Class ; rdfs:label "concept" .
sv:broader a owl:ObjectProperty ; rdfs:domain sv:Concept ; rdfs:range sv:Concept .
"""


def test_standards_give_prefixes_only_for_real_namespaces():
    va = [{"name": "VIS4ML", "url": "https://github.com/search?q=VIS4ML&type=repositories"},
          {"name": "VISO (Visualization Ontology)", "url": "https://purl.org/viso/ontology/viso/"},
          {"name": "PROV-O", "url": "https://www.w3.org/TR/prov-o/"},
          {"name": "Vega-Lite", "url": "https://vega.github.io/vega-lite/docs/"},
          {"name": "SKOS", "url": "https://www.w3.org/TR/skos-reference/"},
          {"name": "RDF Data Cube Vocabulary", "url": "https://www.w3.org/TR/vocab-data-cube/"},
          {"name": "DCAT 3", "url": "https://www.w3.org/TR/vocab-dcat-3/"}]
    assert O.standards_to_prefixes(va) == {
        "viso": "https://purl.org/viso/ontology/viso/", "prov": "http://www.w3.org/ns/prov#",
        "skos": "http://www.w3.org/2004/02/skos/core#", "qb": "http://purl.org/linked-data/cube#",
        "dcat": "http://www.w3.org/ns/dcat#"}                       # no dc for DCAT, no docs:, no spec pages
    # short keys no longer match inside words ("as" in "basic", "time" in "runtime", "ex" in "text")
    assert O.standards_to_prefixes([{"name": "Basic runtime text model", "url": "https://example.com/docs/"}]) == {}
    # an explicit prefix and namespace win; a namespace that is a web page is refused
    assert O.standards_to_prefixes([{"name": "My vocab", "prefix": "mv", "namespace": "https://w3id.org/mv#"}]) == \
        {"mv": "https://w3id.org/mv#"}
    assert O.standards_to_prefixes([{"name": "Other", "prefix": "ot", "namespace": "https://www.w3.org/TR/other/"}]) == {}


def test_standards_are_cleaned_and_old_entries_keep_working():
    old = V.clean_standard({"name": "PROV-O", "type": "Standard", "url": "https://www.w3.org/TR/prov-o/", "reuse_hint": "x"})
    assert (old["prefix"], old["namespace"], old["decision"]) == ("prov", "http://www.w3.org/ns/prov#", "align")
    assert old["documentation_url"] == "https://www.w3.org/TR/prov-o/"
    vega = V.clean_standard({"name": "Vega-Lite", "url": "https://vega.github.io/vega-lite/docs/"})
    assert (vega["namespace"], vega["prefix"], vega["decision"]) == ("", "", "reference")
    # a model that puts the specification page into "namespace" does not get a namespace
    bad = V.clean_standard({"name": "Some Spec", "namespace": "https://www.w3.org/TR/some/", "prefix": "sp", "decision": "use_terms"})
    assert bad["namespace"] == "" and bad["prefix"] == ""


def test_vocabulary_upload_reads_terms_of_its_own_namespace():
    client = TestClient(A.app)
    sid = client.post("/api/session/create").json()["session_id"]
    s = A.sessions[sid]
    d = client.post(f"/api/standards/upload?session_id={sid}&index=-1",
                    files={"file": ("ex.ttl", VOCAB_TTL.encode(), "text/turtle")}).json()
    st = d["standards"][0]
    assert st["name"] == "Example Vocabulary" and st["namespace"] == "https://w3id.org/exvocab#" and st["prefix"] == "ex"   # the prefix the file declares (DECISIONS 99)
    assert st["vocabulary"]["classes"] == 2 and st["vocabulary"]["properties"] == 1    # Foreign is not its own term
    entry = s["vocabularies"]["ex"]
    # the term list lives in its own file next to the project, not in the project file (DECISIONS 100)
    assert "classes" not in entry and entry["counts"] == {"classes": 2, "properties": 1}
    assert (V.SESSION_DIR / entry["terms_file"]).is_file()
    voc = V.vocab_terms(entry)
    dev = next(c for c in voc["classes"] if c["name"] == "Device")
    assert dev["label"] == "device" and dev["parents"] == ["ex:Thing2"]             # English label, prefixed reference
    assert voc["properties"][0]["domain"] == "ex:Device"
    # the term lists stay on the server; the project view carries only the summary
    view = client.get(f"/api/session/{sid}").json()["project"]
    assert view["vocabularies"] is None and view["suggested_standards"][0]["vocabulary"]["classes"] == 2
    bad = client.post(f"/api/standards/upload?session_id={sid}&index=-1", files={"file": ("x.ttl", b"not rdf at all {", "text/turtle")})
    assert bad.status_code == 400
    # export and import carry the term file along
    exported = client.get(f"/api/session/{sid}/export").json()
    assert exported["vocabulary_terms"]["ex"]["properties"][0]["name"] == "partOf"
    new = client.post("/api/session/import", files={"file": ("p.json", json.dumps(exported).encode(), "application/json")}).json()
    imported = A.sessions[new["session_id"]]["vocabularies"]["ex"]
    assert imported["terms_file"].startswith(new["session_id"]) and len(V.vocab_terms(imported)["classes"]) == 2
    assert "Device" in V.session_vocab(A.sessions[new["session_id"]])["ex"]


def test_a_vocabulary_keeps_its_prefix_and_the_project_gives_way():
    client = TestClient(A.app)
    sid = client.post("/api/session/create").json()["session_id"]
    s = A.sessions[sid]
    P._context(s)["conventions"]["prefix"] = "ex"                     # the project uses the vocabulary's prefix
    d = client.post(f"/api/standards/upload?session_id={sid}&index=-1",
                    files={"file": ("ex.ttl", VOCAB_TTL.encode(), "text/turtle")}).json()
    assert d["standards"][0]["prefix"] == "ex" and d["prefix_change"] == {"old": "ex", "new": "ex-onto"}
    assert d["conventions"]["prefix"] == "ex-onto" and "prefix_change" not in d["standards"][0]
    # the project cannot take a prefix a vocabulary holds
    r = client.post("/api/context/save", json={"session_id": sid, "conventions": {"prefix": "ex"}})
    assert r.status_code == 400 and "Example Vocabulary" in r.json()["detail"]
    # a second vocabulary with the same prefix for another namespace is refused
    other = VOCAB_TTL.replace("https://w3id.org/exvocab", "https://other.org/voc")
    r = client.post(f"/api/standards/upload?session_id={sid}&index=-1", files={"file": ("o.ttl", other.encode(), "text/turtle")})
    assert r.status_code == 400 and "already used by Example Vocabulary" in r.json()["detail"]
    # an additional prefix that equals the project's moves the project's prefix again
    r = client.post("/api/session/add-prefix", json={"session_id": sid, "prefix": "ex-onto", "uri": "https://x.org/y#"}).json()
    assert r["prefix_change"] == {"old": "ex-onto", "new": "ex-onto-onto"}
    assert client.post("/api/session/add-prefix", json={"session_id": sid, "prefix": "ex",
                                                         "uri": "https://x.org/z#"}).status_code == 400


def test_the_prefix_a_file_declares_survives_a_default_namespace():
    # the W3C wine ontology binds its namespace as the default (xmlns=) and as xmlns:vin=; rdflib keeps only one
    xml = """<?xml version="1.0"?>
<rdf:RDF xmlns="http://example.org/vin#" xmlns:vin="http://example.org/vin#"
  xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:owl="http://www.w3.org/2002/07/owl#">
  <owl:Class rdf:about="http://example.org/vin#Wine"/>
</rdf:RDF>"""
    g = V._parse_rdf(xml, "application/rdf+xml", "w.rdf")
    assert V.declared_prefix(g, "http://example.org/vin#") == "vin"
    s = {"context": {}, "suggested_standards": []}
    st = {"name": "Wine", "decision": "align"}
    V.store_vocabulary(s, st, g, "test")
    assert st["prefix"] == "vin" and st["prefix_change"] == {} and "vin" in s["vocabularies"]


def test_standard_update_and_load_from_the_web():
    client = TestClient(A.app)
    sid = client.post("/api/session/create").json()["session_id"]
    s = A.sessions[sid]
    s["suggested_standards"] = [{"name": "Example", "namespace": "https://w3id.org/exvocab#", "prefix": "ex"}]
    up = lambda body: client.post("/api/standards/update", json={"session_id": sid, **body})
    assert up({"index": 0, "fields": {"namespace": "https://www.w3.org/TR/exvocab/"}}).status_code == 400
    assert up({"index": 0, "fields": {"decision": "use_terms"}}).json()["standards"][0]["decision"] == "use_terms"

    class Resp:   # what requests.get returns, reduced to what fetch_vocabulary uses
        def __init__(self, status, ctype, body, url):
            self.status_code, self.headers, self.url = status, {"content-type": ctype}, url
            self.raw = type("Raw", (), {"read": lambda _self, n, decode_content=True: body.encode()})()
    tried = []
    def fake_get(url, **kw):
        tried.append(url)
        if url.endswith(".ttl"):
            return Resp(200, "text/plain", VOCAB_TTL, url)       # served as text/plain, still Turtle
        return Resp(200, "text/html", "<html></html>", url)
    real = A.requests.get
    A.requests.get = fake_get
    try:
        d = client.post("/api/standards/load", json={"session_id": sid, "index": 0})
        assert d.status_code == 422 and "web page" in d.json()["detail"]
        up({"index": 0, "fields": {"download_url": "https://example.org/files/exvocab.ttl"}})
        d = client.post("/api/standards/load", json={"session_id": sid, "index": 0}).json()
        assert d["standards"][0]["vocabulary"]["classes"] == 2 and tried[-1].endswith(".ttl")
        assert "ex" in s["vocabularies"]
        # a new namespace invalidates the loaded vocabulary summary
        st = up({"index": 0, "fields": {"namespace": "https://w3id.org/other#"}}).json()["standards"][0]
        assert "vocabulary" not in st
    finally:
        A.requests.get = real
    assert up({"index": 0, "remove": True}).json()["standards"] == []


def test_vocabulary_terms_are_checked_in_edits():
    vocab = {"pl": {"Activity": {"kind": "class", "parents": []}, "Entity": {"kind": "class", "parents": []},
                    "wasGeneratedBy": {"kind": "object", "domain": "pl:Entity", "range": "pl:Activity", "parents": []}}}
    onto = base()
    onto["properties"].append({"name": "isGeneratedBy", "type": "ObjectProperty", "domain": "Dataset", "range": "Task",
                               "inverse_of": None, "labels": {"en": "x"}, "description": "", "module": "Data"})
    new, rep = A.apply_edits(onto, [
        {"op": "add_axiom", "type": "SubClassOf", "classes": ["Dataset", "pl:Nope"]},              # not a term
        {"op": "add_axiom", "type": "SubClassOf", "classes": ["Dataset", "pl:wasGeneratedBy"]},     # a property
        # domain Dataset is not below pl:Entity yet - fits once the link below is applied (retry)
        {"op": "update_property", "name": "isGeneratedBy", "sub_property_of": "pl:wasGeneratedBy"},
        {"op": "add_axiom", "type": "SubClassOf", "classes": ["Dataset", "pl:Entity"]},
        {"op": "add_axiom", "type": "SubClassOf", "classes": ["Task", "pl:Activity"]}], vocab=vocab)
    reasons = [r["reason"] for r in rep["rejected"]]
    assert any("pl:Nope is not a term" in r for r in reasons) and any("is a property of pl:" in r for r in reasons)
    by = {p["name"]: p for p in new["properties"]}
    assert by["isGeneratedBy"]["sub_property_of"] == "pl:wasGeneratedBy" and len(rep["rejected"]) == 2
    # without the class links the subproperty is refused
    new, rep = A.apply_edits(onto, [{"op": "update_property", "name": "isGeneratedBy",
                                     "sub_property_of": "pl:wasGeneratedBy"}], vocab=vocab)
    assert "is not below the domain pl:Entity" in rep["rejected"][0]["reason"]


def test_generation_offers_matching_terms_and_checks_them():
    client = TestClient(A.app)
    sid, s = align_session(client)          # pl (align) loaded
    client.post(f"/api/standards/upload?session_id={sid}&index=-1", files={"file": ("sv.ttl", SMALL_TTL.encode(), "text/turtle")})
    i = next(i for i, x in enumerate(s["suggested_standards"]) if x["prefix"] == "sv")
    client.post("/api/standards/update", json={"session_id": sid, "index": i, "fields": {"decision": "use_terms"}})
    terms = V.relevant_vocab_terms(s, ["ProvenanceActivity", "generated data entity", "ThemeConcept"])
    refs = [t["ref"] for t in terms]
    assert set(refs[:3]) == {"pl:Activity", "pl:Entity", "sv:Concept"}
    assert "sv:broader" not in refs and "pl:Plan" not in refs                  # only what matches, no whole vocabularies
    block = V.reuse_block(terms)
    assert "pl:Activity (class, team decision: align)" in block and "sv:Concept (class, team decision: use_terms)" in block
    # after generation: invented or wrong-kind terms are removed, fitting links stay
    onto = copy.deepcopy(s["ontology"])
    onto["classes"][0]["parent"] = "pl:Activity"                               # Task below pl:Activity
    onto["classes"].append({"name": "Odd", "labels": {"en": "odd"}, "parent": "pl:Nope", "module": "Data"})
    onto["axioms"].append({"type": "SubClassOf", "classes": ["Dataset", "pl:wasGeneratedBy"]})   # a property
    onto["axioms"].append({"type": "SubClassOf", "classes": ["Dataset", "pl:Entity"]})
    by = {p["name"]: p for p in onto["properties"]}
    by["isGeneratedBy"]["sub_property_of"] = "pl:wasGeneratedBy"              # fits: Dataset ⊑ Entity, Task ⊑ Activity
    by["usesData"]["sub_property_of"] = "pl:wasGeneratedBy"                   # Task is not below pl:Entity
    checked, dropped = V.check_external_refs(s, onto)
    cl = {c["name"]: c for c in checked["classes"]}
    props = {p["name"]: p for p in checked["properties"]}
    assert cl["Task"]["parent"] == "pl:Activity" and cl["Odd"]["parent"] is None
    assert ["Dataset", "pl:Entity"] in [a["classes"] for a in checked["axioms"]]
    assert ["Dataset", "pl:wasGeneratedBy"] not in [a["classes"] for a in checked["axioms"]]
    assert props["isGeneratedBy"]["sub_property_of"] == "pl:wasGeneratedBy" and "sub_property_of" not in props["usesData"]
    assert len(dropped) == 3


def test_generation_without_literature_reuses_loaded_terms():
    client = TestClient(A.app)
    sid, s = align_session(client)
    s["ontology"] = None
    s["momo"] = {"use_case": "", "key_notions": [{"name": "Tasks", "description": "analysis work"}], "patterns": [],
                 "competency_questions": [{"question": "Which data does a task generate?"}]}
    E.check_oops = lambda turtle: []
    module = {"module": {"name": "Tasks", "documentation": "d"}, "classes": [
        {"name": "Task", "labels": {"en": "Task"}, "description": "x", "parent": "pl:Activity"},
        {"name": "Dataset", "labels": {"en": "Dataset"}, "description": "x", "parent": "pl:Invented"}],
        "properties": [], "individuals": [], "axioms": []}
    L.call_llm = FakeLLM({"ontology_name": "Tasks", "modules": [{"name": "Tasks", "classes": [
        {"name": "Task", "note": "an analysis activity that generates data entities"},
        {"name": "Dataset", "note": "data"}]}]}, module)
    d = client.post("/api/generate", json={"session_id": sid, "domain_description": "Analysis tasks are activities that generate data entities",
                                           "llm_config": CFG}).json()
    prompt = L.call_llm.calls[1][-1]["content"]                      # the module call
    assert "**Reusable vocabulary terms**" in prompt and "pl:Activity" in prompt
    assert d["reuse_report"]["links"] == 1 and "pl:Invented is not a term" in d["reuse_report"]["dropped"][0]
    assert "@prefix pl: <https://w3id.org/pl#>" in d["turtle"] and "rdfs:subClassOf pl:Activity" in d["turtle"]


def test_built_in_prefixes_cannot_be_taken_and_derived_prefixes_start_with_a_letter():
    client = TestClient(A.app)
    sid = client.post("/api/session/create").json()["session_id"]
    r = client.post("/api/session/add-prefix", json={"session_id": sid, "prefix": "owl", "uri": "https://x.org/owl#"})
    assert r.status_code == 400 and "built-in" in r.json()["detail"]
    assert client.post("/api/session/add-prefix", json={"session_id": sid, "prefix": "owl",
                                                         "uri": "http://www.w3.org/2002/07/owl#"}).status_code == 200
    r = client.post("/api/context/save", json={"session_id": sid, "conventions": {"prefix": "rdfs"}})
    assert r.status_code == 400 and "built-in" in r.json()["detail"]
    assert V._derived_prefix("http://example.org/onto/1.0/") == "onto"
    assert V._derived_prefix("http://example.org/ont/2023#") == "ont"
    assert V._derived_prefix("urn:2023") == "urn" and V._derived_prefix("http://1.2/3/") == "v3"
