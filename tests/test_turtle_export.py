"""Tests for the Turtle and SHACL export."""
import ontology_io as O
import project as P
from helpers import base, property_onto


def test_class_definitions_by_intersection_are_read_as_superclasses_and_the_rest_is_reported():
    # DECISIONS 138: the W3C wine ontology defines most classes as intersections; before, 62 of 74 had no superclass
    from rdflib import Graph
    rdf = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:owl="http://www.w3.org/2002/07/owl#"
         xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#" xml:base="https://example.org/wine"
         xmlns="https://example.org/wine#">
  <owl:Ontology rdf:about=""/>
  <owl:Class rdf:ID="Wine"/>
  <owl:Class rdf:ID="Region"/>
  <owl:Class rdf:ID="WineColor"><owl:oneOf rdf:parseType="Collection">
    <WineColor rdf:about="#Red"/><WineColor rdf:about="#White"/></owl:oneOf></owl:Class>
  <owl:ObjectProperty rdf:ID="hasColor"/>
  <owl:ObjectProperty rdf:ID="locatedIn"/>
  <owl:Class rdf:ID="RedWine"><owl:intersectionOf rdf:parseType="Collection">
    <owl:Class rdf:about="#Wine"/>
    <owl:Restriction><owl:onProperty rdf:resource="#hasColor"/><owl:hasValue rdf:resource="#Red"/></owl:Restriction>
  </owl:intersectionOf></owl:Class>
  <owl:Class rdf:ID="RegionalWine"><owl:equivalentClass><owl:Class><owl:intersectionOf rdf:parseType="Collection">
    <owl:Class rdf:about="#Wine"/>
    <owl:Restriction><owl:onProperty rdf:resource="#locatedIn"/><owl:someValuesFrom rdf:resource="#Region"/></owl:Restriction>
  </owl:intersectionOf></owl:Class></owl:equivalentClass></owl:Class>
</rdf:RDF>"""
    g = Graph().parse(data=rdf, format="xml")
    onto = O.rdf_graph_to_onto(g, "")
    by = {c["name"]: c for c in onto["classes"]}
    assert by["RedWine"]["parent"] == "Wine" and by["RegionalWine"]["parent"] == "Wine"
    assert [(r["class"], r["kind"], r["property"], r["value"]) for r in onto["restrictions"]] == \
        [("RegionalWine", "some", "locatedIn", "Region")]
    assert onto["import_report"] == {"definitions_read_as_superclasses": 2,
                                     "not_read": {"hasValue restrictions": 1, "enumerations (owl:oneOf)": 1}}


def test_class_restrictions_are_written_as_owl_restrictions_and_read_back():
    from rdflib import Graph
    onto = base()
    onto["restrictions"] = [
        {"class": "LowLevelTask", "property": "usesData", "kind": "some", "value": "Dataset", "n": None},
        {"class": "Task", "property": "usesData", "kind": "only", "value": "Dataset", "n": None},
        {"class": "LowLevelTask", "property": "usesData", "kind": "min", "value": "Dataset", "n": 2},
        {"class": "Task", "property": "hasName", "kind": "max", "value": "xsd:string", "n": 1},
        {"class": "Dataset", "property": "schema:about", "kind": "some", "value": "schema:Thing", "n": None}]
    t = O.ontology_to_turtle(onto)
    assert O.validate_turtle(t)[0]
    assert "owl:onProperty :usesData ; owl:someValuesFrom :Dataset ]" in t and "owl:allValuesFrom :Dataset" in t
    assert 'owl:minQualifiedCardinality "2"^^xsd:nonNegativeInteger ; owl:onClass :Dataset' in t
    assert 'owl:maxQualifiedCardinality "1"^^xsd:nonNegativeInteger ; owl:onDataRange xsd:string' in t
    assert "schema:Thing a owl:Class ." in t and "schema:about a owl:ObjectProperty ." in t    # declared (OOPS! P34)
    g = Graph()
    g.parse(data=t, format="turtle")
    back = O.rdf_graph_to_onto(g, t)
    key = lambda r: (r["class"], r["property"], r["kind"], r["value"], r["n"])
    assert sorted(map(key, back["restrictions"])) == sorted(map(key, onto["restrictions"]))
    assert {c["name"]: c["parent"] for c in back["classes"]}["LowLevelTask"] == "Task"   # a restriction is no parent
    assert next(r for r in back["restrictions"] if r["kind"] == "some" and r["class"] == "LowLevelTask") \
        ["natural_language"] == "Every low level task uses data some dataset."
    # an unqualified count reads as one on owl:Thing; a restriction the model does not know is left out
    g.parse(data="""@prefix : <https://example.org/t#> . @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> . @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
        :Dataset rdfs:subClassOf [ a owl:Restriction ; owl:onProperty :usedByTask ; owl:minCardinality "1"^^xsd:nonNegativeInteger ] ,
                                 [ a owl:Restriction ; owl:onProperty :usedByTask ; owl:hasValue :taskExample ] .""",
            format="turtle")
    back = O.rdf_graph_to_onto(g, "")
    assert ("Dataset", "usedByTask", "min", "owl:Thing", 1) in map(key, back["restrictions"])
    assert len(back["restrictions"]) == len(onto["restrictions"]) + 1


def test_shacl_with_several_constraints_per_class_is_valid_turtle():
    constraints = [{"target_class": "Task", "property_name": "usesData", "min_count": "1", "max_count": ""},
                   {"target_class": "Task", "property_name": "hasName", "min_count": "", "max_count": "1",
                    "datatype": "string"}]
    shacl = O.generate_shacl_turtle(base(), constraints)
    assert O.validate_turtle(shacl)[0] and shacl.count(" ] .") == 1 and shacl.count(" ] ;") == 1
    try:
        O.generate_shacl_turtle(base(), [{"target_class": "Task", "property_name": "usesData", "min_count": "1.5"}])
        assert False, "no error"
    except ValueError as ex:
        assert "whole numbers" in str(ex)
    assert P.nth(["a", "b"], 0) is None and P.nth(["a", "b"], "2") == "b" and P.nth(["a"], "x") is None


def test_turtle_header_is_english_and_declares_only_used_prefixes():
    onto = base()
    onto["description_language"] = "en"
    t = O.ontology_to_turtle(onto, custom_prefixes={"skos": "http://www.w3.org/2004/02/skos/core#",
                                                    "schema": "https://schema.org/"})
    assert 'rdfs:label "Test"@en' in t and "@prefix skos:" not in t and "@prefix owl:" in t
    onto["classes"][0]["parent"] = "schema:Thing"
    assert "@prefix schema:" in O.ontology_to_turtle(onto, custom_prefixes={"schema": "https://schema.org/"})
    assert 'rdfs:label "Test"@en' in O.ontology_to_turtle({**base(), "description_language": None})   # default English
    assert P.label_languages({}) == ["en"] and P.DEFAULT_CONVENTIONS["label_languages"] == "en"


def test_property_hierarchy_and_characteristics_survive_turtle_round_trip():
    from rdflib import Graph
    onto = property_onto()
    onto["properties"][0]["characteristics"] = ["functional"]
    onto["properties"][3]["sub_property_of"] = "usesData"
    onto["properties"].append({"name": "partOf", "type": "ObjectProperty", "domain": None, "range": None,
                               "inverse_of": None, "characteristics": ["transitive", "asymmetric"][:1],
                               "labels": {"en": "part of"}, "description": "", "module": "Tasks"})
    turtle = O.ontology_to_turtle(onto)
    assert "rdfs:subPropertyOf :usesData" in turtle and "owl:TransitiveProperty" in turtle
    g = Graph().parse(data=turtle, format="turtle")
    back = {p["name"]: p for p in O.rdf_graph_to_onto(g, turtle)["properties"]}
    assert back["usesSample"]["sub_property_of"] == "usesData" and back["partOf"]["characteristics"] == ["transitive"]
    assert back["usesData"]["characteristics"] == ["functional"]
    assert not [i for i in O.rdf_graph_to_onto(g, turtle)["individuals"] if i["name"] == "partOf"]
