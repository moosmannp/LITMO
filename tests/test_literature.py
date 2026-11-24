"""Tests for the literature: reading files, grouping the concepts of the paper cards, and linking
classes to them."""
import corpus as C
import generation as G
import llm as L
from helpers import CFG, FakeLLM


def test_literature_files_in_windows_encoding_keep_their_umlauts():
    raw = "Größe;Wert\nÄpfel;1\n".encode("cp1252")
    assert C._decode_text(raw).startswith("Größe") and C._decode_text("\ufeffä".encode("utf-8")) == "ä"
    assert "Größe" in C._profile_csv(raw, "t.csv")


def test_an_abbreviation_is_grouped_under_its_full_form():
    card = lambda term, *syn: {"card": {"concepts": [{"term": term, "synonyms": list(syn), "definition": ""}]}}
    docs = [{"id": "d1", **card("VA", "visual analytics")}, {"id": "d2", **card("visual analytics")},
            {"id": "d3", **card("VA", "visual attention")}, {"id": "d4", **card("visual attention")}]
    groups = {c["label"]: c["papers"] for c in C.group_concepts(docs)}
    assert groups == {"visual analytics": 2, "visual attention": 2}


def test_a_failed_consolidation_leaves_the_name_grouping_unchanged():
    s = {"corpus": {"docs": [{"id": "d1", "status": "done", "card": {"concepts": [
        {"term": "task", "synonyms": [], "definition": "x"}, {"term": "goal", "synonyms": [], "definition": "y"}]}}]}}
    old_apply, old_llm = C.apply_consolidation, L.call_llm
    def broken(concepts, result, doc_ids):
        concepts[0]["sources"] += concepts[1]["sources"]           # half done ...
        raise KeyError("ids")                                       # ... then it fails
    C.apply_consolidation, L.call_llm = broken, FakeLLM({"merges": []})
    try:
        inv = C.build_inventory(s, CFG)
    finally:
        C.apply_consolidation, L.call_llm = old_apply, old_llm
    assert "Consolidation failed" in inv["warning"] and [len(c["sources"]) for c in inv["concepts"]] == [1, 1]


def test_modular_generation_links_classes_to_inventory_concepts():
    inv = {"concepts": [{"id": "c1", "label": "visual encoding", "variants": [], "papers": 2,
                         "sources": [{"doc": "d1", "definition": "maps data", "uri": ""}], "definition": ""}],
           "themes": [], "relations": []}
    session = {"corpus": {"docs": [{"id": "d1", "name": "p.pdf", "card": {"title": "T", "authors": "Doe, J.", "year": "2020"}}],
                          "inventory": inv}, "momo": {"patterns": []}, "context": {}}
    plan = {"modules": [{"name": "Vis", "classes": [{"name": "VisualEncoding", "concepts": ["c1"]},
                                                    {"name": "Forgotten", "concepts": ["c1"]}], "other": []}]}
    results = {"Vis": {"module": {"documentation": "d"}, "classes": [{"name": "VisualEncoding", "sources": ["d1"]}]}}
    onto, _ = G.merge_modules(plan, results, [{"name": "Vis"}], session)
    by = {c["name"]: c for c in onto["classes"]}
    assert by["VisualEncoding"]["inventory_concepts"] == ["visual encoding"]
    assert by["Forgotten"]["inventory_concepts"] == ["visual encoding"]       # fallback class keeps the link too
