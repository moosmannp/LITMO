"""Tests for ontology_edits. Run with `pytest tests/test_ontology_edits.py`."""
import copy

from ontology_edits import (apply_edits, integrity_issues, sanitize_names, focus_modules,
                            ontology_listing)
from helpers import base


def test_a_cycle_through_subclassof_axioms_is_refused():
    new, rep = run([{"op": "add_axiom", "type": "SubClassOf", "classes": ["Task", "LowLevelTask"]}])
    assert not rep["applied"] and "cycle" in rep["rejected"][0]["reason"]
    onto = base()
    onto["axioms"].append({"type": "SubClassOf", "classes": ["Dataset", "LowLevelTask"]})
    new, rep = run([{"op": "update_class", "name": "Task", "parent": "Dataset"}], onto)
    assert not rep["applied"] and "cycle" in rep["rejected"][0]["reason"]


def run(ops, onto=None):
    onto = onto if onto is not None else base()
    before = copy.deepcopy(onto)
    new, report = apply_edits(onto, ops)
    assert onto == before, "the input ontology must not be modified"
    return new, report


def cls(onto, name):
    return next(c for c in onto["classes"] if c["name"] == name)


def test_unmentioned_content_is_untouched():
    new, rep = run([{"op": "update_class", "name": "Dataset", "description": "A table."}])
    assert not rep["rejected"] and len(rep["applied"]) == 1
    assert cls(new, "Dataset")["description"] == "A table."
    assert cls(new, "Task")["sources"] == ["Munzner, 2014: Visualization Analysis"]
    assert cls(new, "Task")["see_also"] == ["https://example.org/o#Task"]
    assert new["properties"] == base()["properties"]


def test_add_class_with_defaults():
    new, rep = run([{"op": "add_class", "name": "Goal", "parent": "Task", "module": "Tasks"}])
    c = cls(new, "Goal")
    assert c["parent"] == "Task" and c["labels"] == {"en": "Goal"} and not rep["rejected"]


def test_order_does_not_matter_for_dependencies():
    # the child is listed before its parent, and the property before its range class
    ops = [{"op": "add_class", "name": "Child", "parent": "NewParent", "module": "Tasks"},
           {"op": "add_property", "name": "refersTo", "type": "ObjectProperty", "domain": "Child", "range": "NewParent"},
           {"op": "add_class", "name": "NewParent", "module": "Tasks"}]
    new, rep = run(ops)
    assert not rep["rejected"], rep["rejected"]
    assert cls(new, "Child")["parent"] == "NewParent" and not rep["new_issues"]


def test_unknown_references_are_rejected_with_reason():
    new, rep = run([{"op": "add_class", "name": "Goal", "parent": "Nothing"},
                    {"op": "update_property", "name": "missing", "description": "x"}])
    assert len(rep["rejected"]) == 2 and not rep["applied"]
    assert "unknown class" in rep["rejected"][0]["reason"]
    assert new == base()


def test_names_are_unique_across_classes_properties_individuals():
    _, rep = run([{"op": "add_class", "name": "usesdata"}, {"op": "add_class", "name": "Task"},
                  {"op": "add_class", "name": "bad name"}])
    assert len(rep["rejected"]) == 3


def test_rename_class_updates_all_references():
    new, rep = run([{"op": "rename_class", "name": "Task", "new_name": "AnalysisTask"}])
    assert not rep["rejected"]
    assert cls(new, "LowLevelTask")["parent"] == "AnalysisTask"
    assert new["properties"][0]["domain"] == "AnalysisTask" and new["properties"][1]["range"] == "AnalysisTask"
    assert new["axioms"][0]["classes"] == ["AnalysisTask", "Dataset"]
    assert cls(new, "AnalysisTask")["sources"]            # annotations survive the rename
    assert integrity_issues(new) == []


def test_rename_via_update_class_new_name():
    new, _ = run([{"op": "update_class", "name": "Dataset", "new_name": "DataTable"}])
    assert new["properties"][0]["range"] == "DataTable"


def test_cycle_is_rejected():
    _, rep = run([{"op": "update_class", "name": "Task", "parent": "LowLevelTask"}])
    assert rep["rejected"] and "cycle" in rep["rejected"][0]["reason"]
    _, rep = run([{"op": "update_class", "name": "Task", "parent": "Task"}])
    assert rep["rejected"]


def test_remove_class_reparents_and_redirects():
    new, rep = run([{"op": "remove_class", "name": "LowLevelTask"}])
    assert not rep["rejected"], rep["rejected"]
    assert new["individuals"][0]["class"] == "Task"        # redirected to the parent
    assert all(c["name"] != "LowLevelTask" for c in new["classes"])
    assert integrity_issues(new) == []


def test_remove_class_still_in_use_needs_replacement():
    _, rep = run([{"op": "remove_class", "name": "Dataset"}])        # no parent, used as range/domain
    assert rep["rejected"] and "replace_with" in rep["rejected"][0]["reason"]
    new, rep = run([{"op": "remove_class", "name": "Dataset", "replace_with": "Task"}])
    assert not rep["rejected"] and new["properties"][0]["range"] == "Task"
    assert new["axioms"] == []   # DisjointClasses(Task, Dataset) lost a member and is dropped


def test_property_rules():
    new, rep = run([{"op": "add_property", "name": "hasSize", "type": "DatatypeProperty", "domain": "Dataset", "range": "integer"}])
    assert next(p for p in new["properties"] if p["name"] == "hasSize")["range"] == "xsd:integer"
    _, rep = run([{"op": "add_property", "name": "hasX", "type": "DatatypeProperty", "domain": "Dataset", "range": "Dataset"}])
    assert rep["rejected"]                                           # class as datatype range
    _, rep = run([{"op": "add_property", "name": "p", "type": "Whatever"}])
    assert rep["rejected"]


def test_inverse_is_linked_both_ways_and_cleaned_up():
    new, rep = run([{"op": "add_property", "name": "supports", "type": "ObjectProperty", "domain": "Dataset", "range": "Task"},
                    {"op": "add_property", "name": "supportedBy", "type": "ObjectProperty", "domain": "Task",
                     "range": "Dataset", "inverse_of": "supports"}])
    assert not rep["rejected"]
    props = {p["name"]: p for p in new["properties"]}
    assert props["supports"]["inverse_of"] == "supportedBy" and props["supportedBy"]["inverse_of"] == "supports"
    new, _ = run([{"op": "remove_property", "name": "usesData"}])
    assert next(p for p in new["properties"] if p["name"] == "usedByTask")["inverse_of"] is None
    _, rep = run([{"op": "update_property", "name": "hasName", "inverse_of": "usesData"}])
    assert rep["rejected"]                                           # datatype property cannot have an inverse


def test_rename_property_updates_inverse():
    new, _ = run([{"op": "rename_property", "name": "usesData", "new_name": "operatesOn"}])
    assert next(p for p in new["properties"] if p["name"] == "usedByTask")["inverse_of"] == "operatesOn"


def test_axioms():
    new, rep = run([{"op": "add_axiom", "type": "DisjointClasses", "classes": ["Dataset", "Task"]}])
    assert rep["rejected"] and "already exists" in rep["rejected"][0]["reason"]   # same set, other order
    new, rep = run([{"op": "add_axiom", "type": "SubClassOf", "classes": ["LowLevelTask", "Task"]},
                    {"op": "remove_axiom", "type": "DisjointClasses", "classes": ["Task", "Dataset"]}])
    assert not rep["rejected"] and len(new["axioms"]) == 1
    _, rep = run([{"op": "add_axiom", "type": "EquivalentClasses", "classes": ["Task", "Dataset", "LowLevelTask"]}])
    assert rep["rejected"]


def test_modules():
    new, rep = run([{"op": "add_module", "name": "Users", "documentation": "people"},
                    {"op": "add_class", "name": "User", "module": "Users"},
                    {"op": "update_module", "name": "Tasks", "new_name": "Activities"}])
    assert not rep["rejected"], rep["rejected"]
    assert cls(new, "Task")["module"] == "Activities" and cls(new, "User")["module"] == "Users"
    _, rep = run([{"op": "remove_module", "name": "Data"}])
    assert rep["rejected"] and "move_to" in rep["rejected"][0]["reason"]
    new, rep = run([{"op": "remove_module", "name": "Data", "move_to": "Tasks"}])
    assert not rep["rejected"] and cls(new, "Dataset")["module"] == "Tasks"


def test_bad_values_reject_the_operation_not_the_run():
    ops = [{"op": "update_class", "name": "Task", "labels": ["x"]},
           {"op": "update_class", "name": "Task", "see_also": ["not a uri"]},
           {"op": "update_class", "name": "Task", "sources": "text"},
           {"op": "does_not_exist"}, {"op": 5}, "text", None,
           {"op": "update_class", "name": "Dataset", "description": "ok"}]
    new, rep = run(ops)
    assert len(rep["applied"]) == 1 and len(rep["rejected"]) == 5
    assert cls(new, "Dataset")["description"] == "ok" and cls(new, "Task") == base()["classes"][0]


def test_failed_operation_leaves_no_partial_change():
    # the description would be changed first, then the parent fails: nothing may stick
    new, rep = run([{"op": "update_class", "name": "Task", "description": "changed", "parent": "Nope"}])
    assert rep["rejected"] and cls(new, "Task")["description"] == "A goal."


def test_case_insensitive_names_resolve():
    new, rep = run([{"op": "update_class", "name": "lowleveltask", "description": "y"}])
    assert not rep["rejected"] and cls(new, "LowLevelTask")["description"] == "y"


def test_sanitize_names_fixes_invalid_identifiers():
    onto = base()
    onto["classes"].append({"name": "Visual Encoding", "labels": {"en": "x"}, "parent": "Task", "module": "Tasks"})
    onto["classes"].append({"name": "Größe (neu)", "labels": {"en": "x"}, "parent": "Visual Encoding", "module": "Tasks"})
    onto["properties"].append({"name": "has visual encoding", "type": "ObjectProperty", "domain": "Visual Encoding",
                               "range": "Dataset", "inverse_of": None, "module": "Tasks"})
    onto["individuals"].append({"name": "my ind", "class": "Größe (neu)"})
    new, renames = sanitize_names(onto)
    names = {r["old"]: r["new"] for r in renames}
    assert names["Visual Encoding"] == "VisualEncoding" and names["has visual encoding"] == "hasVisualEncoding"
    assert names["Größe (neu)"] == "GroeSseNeu" or names["Größe (neu)"].isidentifier()
    assert cls(new, names["Größe (neu)"])["parent"] == "VisualEncoding"
    assert new["properties"][-1]["domain"] == "VisualEncoding"
    assert new["individuals"][-1]["class"] == names["Größe (neu)"]
    assert integrity_issues(new) == []
    assert sanitize_names(new)[1] == []                                # idempotent


def test_sanitize_does_not_merge_names_that_differ_only_in_punctuation():
    # regression: two broken names with the same normalized form crashed sanitize_names (EditError) and their
    # references were merged
    onto = {"classes": [{"name": "Visual Encoding", "parent": None}, {"name": "Visual-Encoding!", "parent": None},
                        {"name": "Glyph", "parent": "Visual-Encoding!"}], "properties": []}
    new, renames = sanitize_names(onto)
    names = {r["old"]: r["new"] for r in renames}
    assert names == {"Visual Encoding": "VisualEncoding", "Visual-Encoding!": "VisualEncoding2"}
    assert cls(new, "Glyph")["parent"] == "VisualEncoding2"


def test_listing_shows_classes_and_properties_outside_known_modules():
    # regression: classes with module "" and properties of a module without classes were invisible to the model
    onto = {"modules": [{"name": "Tasks"}], "classes": [{"name": "Task", "module": "Tasks"}, {"name": "Orphan", "module": ""}],
            "properties": [{"name": "hasThing", "type": "ObjectProperty", "domain": "Task", "range": "Task", "module": "Gone"}]}
    text = ontology_listing(onto)
    assert "Orphan" in text and "hasThing" in text and "## Gone" in text


def test_prefixes_and_datatypes_are_checked():
    known = {"owl", "xsd", "rdf", "rdfs", "schema"}
    _, rep = apply_edits(base(), [{"op": "update_class", "name": "Task", "parent": "foo:Bar"}], known_prefixes=known)
    assert rep["rejected"] and "unknown prefix" in rep["rejected"][0]["reason"]
    new, rep = apply_edits(base(), [{"op": "update_class", "name": "Task", "parent": "schema:Action"}], known_prefixes=known)
    assert not rep["rejected"] and cls(new, "Task")["parent"] == "schema:Action"
    _, rep = run([{"op": "add_property", "name": "p", "type": "ObjectProperty", "domain": "Task", "range": "xsd:string"}])
    assert rep["rejected"] and "DatatypeProperty" in rep["rejected"][0]["reason"]
    _, rep = run([{"op": "add_property", "name": "p", "type": "ObjectProperty", "domain": "Task", "range": "string"}])
    assert rep["rejected"]
    _, rep = run([{"op": "update_class", "name": "Task", "parent": "xsd:string"}])
    assert rep["rejected"] and "not a class" in rep["rejected"][0]["reason"]
    # a class that happens to be called like a datatype stays usable
    new, rep = run([{"op": "add_class", "name": "Date", "module": "Data"},
                    {"op": "add_property", "name": "happensOn", "type": "ObjectProperty", "domain": "Task", "range": "Date"}])
    assert not rep["rejected"], rep["rejected"]


def test_old_name_still_resolves_after_rename_in_the_same_batch():
    new, rep = run([{"op": "rename_class", "name": "Task", "new_name": "Activity"},
                    {"op": "update_class", "name": "Task", "description": "renamed"},
                    {"op": "update_module", "name": "Tasks", "new_name": "Activities"},
                    {"op": "add_class", "name": "Step", "parent": "Task", "module": "Tasks"}])
    assert not rep["rejected"], rep["rejected"]
    assert cls(new, "Activity")["description"] == "renamed"
    assert cls(new, "Step")["parent"] == "Activity" and cls(new, "Step")["module"] == "Activities"


def test_rejected_operation_leaves_no_rename_alias():
    from ontology_edits import Editor, EditError
    ed = Editor(base())
    try:
        ed.apply({"op": "update_class", "name": "Task", "new_name": "Goal", "parent": "Nope"})
    except EditError:
        pass
    assert ed.renamed == {} and cls(ed.o, "Task")


def test_property_type_change():
    _, rep = run([{"op": "update_property", "name": "hasName", "type": "ObjectProperty"}])   # range xsd:string
    assert rep["rejected"]
    new, rep = run([{"op": "update_property", "name": "hasName", "type": "ObjectProperty", "range": "Dataset"}])
    assert not rep["rejected"] and next(p for p in new["properties"] if p["name"] == "hasName")["range"] == "Dataset"
    new, rep = run([{"op": "update_property", "name": "usesData", "type": "DatatypeProperty", "range": "xsd:string"}])
    assert not rep["rejected"], rep["rejected"]
    props = {p["name"]: p for p in new["properties"]}
    assert props["usesData"]["inverse_of"] is None and props["usedByTask"]["inverse_of"] is None


def test_axioms_match_regardless_of_case():
    onto = base()
    onto["axioms"][0]["classes"] = ["task", "dataset"]          # spelled differently by an earlier model answer
    new, rep = run([{"op": "remove_axiom", "type": "DisjointClasses", "classes": ["Task", "Dataset"]}], onto)
    assert not rep["rejected"] and new["axioms"] == []


def test_integrity_detects_problems():
    onto = base()
    onto["classes"][1]["parent"] = "Ghost"
    onto["classes"][0]["parent"] = "LowLevelTask"                        # cycle Task <-> LowLevelTask
    onto["properties"][0]["range"] = "Ghost"
    issues = integrity_issues(onto)
    assert any("unknown parent Ghost" in i for i in issues) and any("unknown range" in i for i in issues)


def test_listing_and_focus():
    onto = base()
    full = ontology_listing(onto)
    assert "## Tasks" in full and "- LowLevelTask [parent: Task]" in full and "A goal." in full
    assert focus_modules(onto, "please rename the dataset class") == {"Data"}
    assert focus_modules(onto, "make it nicer") is None
    compact = ontology_listing(onto, focus={"Data"})
    assert "A goal." not in compact and "Classes: Task, LowLevelTask<Task" in compact
    assert "A goal." not in compact and "Dataset" in compact


def prop(onto, name):
    return next((p for p in onto["properties"] if p["name"] == name), None)


def relations():
    """base() plus a broad relation `involves` (Task -> owl:Thing-like: no range) with inverse `involvedIn`."""
    return [{"op": "add_property", "name": "involves", "type": "ObjectProperty", "domain": "Task",
             "characteristics": ["transitive"]},
            {"op": "add_property", "name": "involvedIn", "type": "ObjectProperty", "range": "Task", "inverse_of": "involves"}]


def test_subproperty_needs_compatible_domain_and_range():
    new, rep = run(relations() + [{"op": "update_property", "name": "usesData", "sub_property_of": "involves"}])
    assert not rep["rejected"] and prop(new, "usesData")["sub_property_of"] == "involves"
    assert prop(new, "involves")["characteristics"] == ["transitive"]
    # usedByTask has domain Dataset, involves has domain Task: Dataset is not below Task
    new, rep = run(relations() + [{"op": "update_property", "name": "usedByTask", "sub_property_of": "involves"}])
    assert "domain Dataset is not below the domain Task" in rep["rejected"][0]["reason"]
    # no cycles, no mixing of object and datatype properties
    new, rep = run(relations() + [{"op": "update_property", "name": "usesData", "sub_property_of": "involves"},
                                  {"op": "update_property", "name": "involves", "sub_property_of": "usesData"}])
    assert "cycle" in rep["rejected"][0]["reason"]
    new, rep = run([{"op": "update_property", "name": "hasName", "sub_property_of": "usesData"}])
    assert rep["rejected"]
    # a narrower domain on the superproperty must not exclude an existing subproperty
    new, rep = run(relations() + [{"op": "update_property", "name": "usesData", "sub_property_of": "involves"},
                                  {"op": "update_property", "name": "involves", "domain": "LowLevelTask"}])
    assert "is not below the domain LowLevelTask" in rep["rejected"][0]["reason"]


def test_characteristics_follow_owl2_dl():
    new, rep = run([{"op": "update_property", "name": "hasName", "characteristics": ["functional"]}])
    assert not rep["rejected"] and prop(new, "hasName")["characteristics"] == ["functional"]
    new, rep = run([{"op": "update_property", "name": "hasName", "characteristics": ["transitive"]}])
    assert "can only be functional" in rep["rejected"][0]["reason"]
    new, rep = run([{"op": "update_property", "name": "usesData", "characteristics": ["inverseFunctional"]}])
    assert prop(new, "usesData")["characteristics"] == ["inverse_functional"]
    new, rep = run([{"op": "update_property", "name": "usesData", "characteristics": ["transitive", "functional"]}])
    assert "not allowed in OWL 2 DL" in rep["rejected"][0]["reason"]
    # a superproperty of a transitive property is not simple either
    new, rep = run(relations()[:1] + [{"op": "update_property", "name": "usesData", "characteristics": ["transitive"]},
                                      {"op": "update_property", "name": "usesData", "sub_property_of": "involves"},
                                      {"op": "update_property", "name": "involves", "characteristics": ["functional"]}])
    assert "not allowed in OWL 2 DL" in rep["rejected"][0]["reason"]
    new, rep = run([{"op": "update_property", "name": "usesData", "characteristics": ["symmetric"]}])
    assert "its own inverse" in rep["rejected"][0]["reason"]
    new, rep = run([{"op": "update_property", "name": "usesData", "characteristics": ["reflexive"]}])
    assert "unknown characteristic" in rep["rejected"][0]["reason"]


def test_merge_property_moves_references_and_the_inverse():
    ops = relations() + [{"op": "add_property", "name": "usesSample", "type": "ObjectProperty", "domain": "LowLevelTask",
                          "range": "Dataset", "inverse_of": "sampleUsedBy"},
                         {"op": "add_property", "name": "sampleUsedBy", "type": "ObjectProperty", "domain": "Dataset",
                          "range": "LowLevelTask"},
                         {"op": "add_property", "name": "usesFirstSample", "type": "ObjectProperty",
                          "domain": "LowLevelTask", "range": "Dataset", "sub_property_of": "usesSample"},
                         {"op": "merge_property", "name": "usesSample", "into": "usesData"},
                         # the old name still works later in the same batch
                         {"op": "update_property", "name": "usesSample", "description": "uses data"}]
    new, rep = run(ops)
    assert not rep["rejected"], rep["rejected"]
    assert prop(new, "usesSample") is None and prop(new, "sampleUsedBy") is None      # inverse merged into usedByTask
    assert prop(new, "usesFirstSample")["sub_property_of"] == "usesData"
    assert prop(new, "usesData")["description"] == "uses data"
    assert "sampleUsedBy -> usedByTask" in rep["applied"][-2]["summary"]
    # merging into a narrower relation would retype subjects: rejected
    new, rep = run([{"op": "add_property", "name": "usesAnything", "type": "ObjectProperty"},
                    {"op": "merge_property", "name": "usesAnything", "into": "usesData"}])
    assert "is not below" in rep["rejected"][0]["reason"]
    # without an inverse on the target, the merged property's inverse is removed
    new, rep = run(relations() + [{"op": "merge_property", "name": "usesData", "into": "involves"}])
    assert not rep["rejected"] and prop(new, "usedByTask") is None
    assert prop(new, "involvedIn") is not None


def test_remove_property_keeps_subproperties_attached():
    new, rep = run(relations() + [{"op": "update_property", "name": "usesData", "sub_property_of": "involves"},
                                  {"op": "remove_property", "name": "involves"}])
    assert not rep["rejected"] and "sub_property_of" not in prop(new, "usesData")
    listing = ontology_listing(run(relations() + [{"op": "update_property", "name": "usesData",
                                                     "sub_property_of": "involves"}])[0])
    assert "below: involves" in listing and "[transitive]" in listing


def test_class_restrictions_are_checked_and_follow_renames_removals_and_merges():
    some = {"op": "add_restriction", "class": "LowLevelTask", "property": "usesData", "kind": "some", "value": "Dataset"}
    new, rep = run([some, {"op": "add_restriction", "class": "Task", "property": "hasName", "kind": "max", "n": 1,
                           "value": "string"}])
    assert not rep["rejected"], rep["rejected"]
    r = new["restrictions"]
    assert r[0] == {"class": "LowLevelTask", "property": "usesData", "kind": "some", "value": "Dataset", "n": None,
                    "module": "Tasks", "natural_language": "Every low level task uses data some dataset."}
    assert (r[1]["value"], r[1]["n"]) == ("xsd:string", 1) and "at most 1" in r[1]["natural_language"]
    assert "LowLevelTask SubClassOf usesData some Dataset" in ontology_listing(new)
    # outside the domain or range, without a count, a fractional count, twice: rejected
    _, rep = run([some, some,
                  {"op": "add_restriction", "class": "Dataset", "property": "usesData", "kind": "some", "value": "Dataset"},
                  {"op": "add_restriction", "class": "Task", "property": "usesData", "kind": "some", "value": "Task"},
                  {"op": "add_restriction", "class": "Task", "property": "usesData", "kind": "min", "value": "Dataset"},
                  {"op": "add_restriction", "class": "Task", "property": "usesData", "kind": "min", "n": "1.5",
                   "value": "Dataset"}])
    reasons = " | ".join(x["reason"] for x in rep["rejected"])
    assert len(rep["rejected"]) == 5 and reasons.count("whole number") == 2
    assert "already exists" in reasons and "not below the domain" in reasons and "not below the range" in reasons
    # renames follow; a removed value class is replaced, a removed restricted class takes its restriction along
    new, _ = run([some, {"op": "rename_class", "name": "Dataset", "new_name": "DataCollection"},
                  {"op": "rename_property", "name": "usesData", "new_name": "consumes"}])
    assert (new["restrictions"][0]["value"], new["restrictions"][0]["property"]) == ("DataCollection", "consumes")
    new, _ = run([some, {"op": "remove_class", "name": "LowLevelTask"}])
    assert not new.get("restrictions")
    # a merge keeps the class pair: the restriction moves to the broader property, and the merge is recorded
    new, rep = run(relations() + [some, {"op": "merge_property", "name": "usesData", "into": "involves"}])
    assert not rep["rejected"] and new["restrictions"][0]["property"] == "involves"
    assert rep["merge_records"] == [{"property": "usesData", "into": "involves", "type": "ObjectProperty",
                                     "domain": "Task", "range": "Dataset"}]
    new, rep = run([some, {"op": "remove_restriction", "class": "LowLevelTask", "property": "usesData"}])
    assert not new.get("restrictions") and "removed restriction LowLevelTask SubClassOf usesData some Dataset" in rep["applied"][1]["summary"]
    # an ontology without restrictions does not get an empty list
    assert "restrictions" not in run([{"op": "update_class", "name": "Task", "description": "x"}])[0]


def test_no_number_on_a_transitive_property():
    # OWL 2 DL: a cardinality restriction needs a simple property - HermiT refuses the whole ontology otherwise
    count = {"op": "add_restriction", "class": "Task", "property": "involves", "kind": "min", "n": 2, "value": "Task"}
    new, rep = run(relations() + [count, {"op": "add_restriction", "class": "Task", "property": "involves",
                                          "kind": "some", "value": "Task"}])
    assert "not allowed in OWL 2 DL on involves" in rep["rejected"][0]["reason"] and len(new["restrictions"]) == 1
    # ... nor may a property with a number become transitive afterwards
    new, rep = run([{"op": "add_restriction", "class": "Task", "property": "usesData", "kind": "max", "n": 3,
                     "value": "Dataset"},
                    {"op": "update_property", "name": "usesData", "characteristics": ["transitive"]}])
    assert len(rep["applied"]) == 1 and "not allowed in OWL 2 DL on usesData" in rep["rejected"][0]["reason"]
