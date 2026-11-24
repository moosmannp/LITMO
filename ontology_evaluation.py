"""Automatic evaluation of a generated ontology (stage A of EVALUATION.md).

Deterministic measures only - no model judges here:
- structural metrics (size, hierarchy, OntoQA-style richness, annotation completeness, disjointness of siblings)
- coverage of the literature's concept inventory (central concepts and themes)
- traceability of every class: sources, inventory concepts, competency-question queries, key notions
- competency-question coverage, split into full / partial / none
- logical check with the HermiT reasoner (via owlready2, needs Java), run in a separate process with a timeout

The module has no dependency on the web app; `app.py` supplies the ontology, the inventory and the CQ test results.
"""
import json
import os
import re
import statistics
import subprocess
import sys
import tempfile

REASONER_TIMEOUT = 180   # seconds; HermiT can take long on large ontologies

# The OWL 2 datatype map (OWL 2 Structural Specification, section 4). Other XML Schema types such as xsd:gYear or
# xsd:date are not part of OWL 2 DL, and HermiT rejects them.
XSD = "http://www.w3.org/2001/XMLSchema#"
OWL2_DATATYPES = {XSD + t for t in (
    "decimal integer nonNegativeInteger nonPositiveInteger positiveInteger negativeInteger long int short byte "
    "unsignedLong unsignedInt unsignedShort unsignedByte double float string normalizedString token language Name "
    "NCName NMTOKEN boolean hexBinary base64Binary anyURI dateTime dateTimeStamp").split()} | {
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#" + t for t in ("PlainLiteral", "XMLLiteral", "langString")} | {
    "http://www.w3.org/2000/01/rdf-schema#Literal", "http://www.w3.org/2002/07/owl#real",
    "http://www.w3.org/2002/07/owl#rational"}


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _labels(x) -> dict:
    labels = x.get("labels") if isinstance(x.get("labels"), dict) else {}
    if not labels and x.get("label_de"):
        labels = {"de": x["label_de"]}
    return labels


def _pct(part, whole):
    return round(100.0 * part / whole, 1) if whole else None


# ── structure ──────────────────────────────────────────────────────────────────
def relation_pairs(props) -> list:
    """Object properties with one entry per inverse pair (the one listed first stands for both directions)."""
    obj = [p for p in props if isinstance(p, dict) and p.get("type") == "ObjectProperty" and p.get("name")]
    names = {p["name"] for p in obj}
    seen, out = set(), []
    for p in obj:
        if p["name"] in seen:
            continue
        seen.add(p["name"])
        if p.get("inverse_of") in names:
            seen.add(p["inverse_of"])
        out.append(p)
    return out


def inverse_conflicts(props) -> list:
    """Properties declared as the inverse of a property that already has another inverse, as (property, target,
    the inverse that stays). The target's own declaration wins; without one, the first claim. Two inverses of one
    property make every pair of them equivalent - in wine run 5 an observation linked from a vintage would have
    become a wine."""
    by = {p["name"]: p for p in props if isinstance(p, dict) and p.get("name")}
    claims = {}
    for p in by.values():
        if p.get("inverse_of") in by and p["inverse_of"] != p["name"]:
            claims.setdefault(p["inverse_of"], []).append(p["name"])
    out = []
    for target, names in claims.items():
        own = by[target].get("inverse_of")
        keep = own if own in by and own != target else names[0]
        out += [(n, target, keep) for n in names if n != keep]
    return out


def structural_metrics(onto, label_languages=("en",)) -> dict:
    classes = [c for c in onto.get("classes") or [] if isinstance(c, dict) and c.get("name")]
    props = [p for p in onto.get("properties") or [] if isinstance(p, dict) and p.get("name")]
    obj = [p for p in props if p.get("type") == "ObjectProperty"]
    data = [p for p in props if p.get("type") != "ObjectProperty"]
    inds = [i for i in onto.get("individuals") or [] if isinstance(i, dict)]
    axioms = [a for a in onto.get("axioms") or [] if isinstance(a, dict)]
    names = {c["name"] for c in classes}
    parent = {c["name"]: c.get("parent") if c.get("parent") in names else None for c in classes}
    children = {}
    for c, p in parent.items():
        if p:
            children.setdefault(p, []).append(c)

    def depth(name, seen=()):
        p = parent.get(name)
        return 1 if not p or p in seen else 1 + depth(p, seen + (name,))
    depths = [depth(c) for c in names]

    # eine Wurzel hat keine eigene Oberklasse, auch nicht ueber einen Vokabularbegriff: User unter prov:Person mit
    # prov:Person SubClassOf Agent liegt unter Agent (VA 5c zaehlte vier solche Klassen als Wurzeln, DECISIONS 132)
    anc = _ancestors(onto)
    roots = [c for c in names if not parent[c] and not (anc.get(c, set()) & (names - {c}))]
    # nur unter einem Begriff eines Vokabulars, ohne Weg zu einer eigenen Klasse: haengt neben der eigenen Hierarchie
    detached = sorted(c["name"] for c in classes if ":" in str(c.get("parent") or "")
                      and not (anc.get(c["name"], set()) & (names - {c["name"]})))

    referenced = {p.get(k) for p in props for k in ("domain", "range")} | {a for ax in axioms for a in ax.get("classes") or []}
    orphans = sorted(c for c in names if not parent[c] and c not in children and c not in referenced)

    # sibling groups (>= 2 subclasses of one parent) with at least one DisjointClasses axiom among them - OOPS! P10
    disjoint_sets = [set(a.get("classes") or []) for a in axioms if a.get("type") == "DisjointClasses"]
    groups = [set(v) for v in children.values() if len(v) >= 2]
    covered_groups = sum(1 for g in groups if any(len(g & d) >= 2 for d in disjoint_sets))

    langs = [l for l in label_languages if l] or ["en"]
    entities = classes + props + inds
    full_labels = sum(1 for x in entities if all(_labels(x).get(l) for l in langs))
    # a core relation (module CoreRelations, DECISIONS 70/89) may connect anything by design
    no_domain_range = sorted(p["name"] for p in props if (not p.get("domain") or not p.get("range"))
                             and p.get("module") != "CoreRelations")
    subclass_links = sum(1 for p in parent.values() if p)

    modules = {}
    for c in classes:
        modules[c.get("module") or "(no module)"] = modules.get(c.get("module") or "(no module)", 0) + 1
    by_name = {p["name"]: p for p in obj}
    pairs = relation_pairs(obj)
    # a relation is top level if neither direction is below another property
    top = [p for p in pairs if not p.get("sub_property_of")
           and not (by_name.get(p.get("inverse_of")) or {}).get("sub_property_of")]
    # links to reused vocabularies: prefixed superclasses, axiom targets, superproperties, domains and ranges
    module_names = {m.get("name") for m in onto.get("modules") or [] if isinstance(m, dict)}
    def external(ref):   # a module name used like a prefix ("User:Audience") is no link to a vocabulary
        return isinstance(ref, str) and ":" in ref and not ref.startswith(("xsd:", "rdf:", "rdfs:", "owl:", "http")) \
            and ref.split(":", 1)[0] not in module_names
    ext_refs = [c.get("parent") for c in classes] + [x for a in axioms for x in (a.get("classes") or [])[1:]]
    ext_refs += [p.get(k) for p in props for k in ("sub_property_of", "domain", "range")]
    linked_vocabs = sorted({r.split(":", 1)[0] for r in ext_refs if external(r)})
    return {
        "external_links": sum(1 for r in ext_refs if external(r)), "linked_vocabularies": linked_vocabs,
        "relations": len(pairs), "top_level_relations": len(top),
        # relativ zur Groesse, damit der Richtwert fuer jede Ontologie gilt (DECISIONS 130)
        "top_level_relations_per_class": round(len(top) / len(classes), 2) if classes else 0,
        "relations_per_class": round(len(pairs) / len(classes), 2) if classes else 0,
        "properties_with_superproperty": sum(1 for p in props if p.get("sub_property_of")),
        "properties_with_characteristics": sum(1 for p in props if p.get("characteristics")),
        "classes": len(classes), "object_properties": len(obj), "datatype_properties": len(data),
        "individuals": len(inds), "axioms": len(axioms), "modules": len(onto.get("modules") or []),
        # Klassenrestriktionen (Phase 5): wie viele, und wie viele Klassen eine haben
        "restrictions": len([r for r in onto.get("restrictions") or [] if isinstance(r, dict)]),
        "classes_with_restriction": len({r.get("class") for r in onto.get("restrictions") or []
                                         if isinstance(r, dict)} & names),
        "max_depth": max(depths) if depths else 0,
        "avg_depth": round(sum(depths) / len(depths), 2) if depths else 0,
        "root_classes": len(roots),
        "classes_below_vocabulary_only": detached,
        "avg_subclasses": round(subclass_links / len(children), 2) if children else 0,
        # OntoQA (Tartir et al. 2005): relationship richness = non-inheritance relations / all relations
        "relationship_richness": round(len(obj) / (len(obj) + subclass_links), 3) if (obj or subclass_links) else 0,
        "attribute_richness": round(len(data) / len(classes), 3) if classes else 0,
        "classes_with_description_pct": _pct(sum(1 for c in classes if (c.get("description") or "").strip()), len(classes)),
        "entities_labelled_in_all_languages_pct": _pct(full_labels, len(entities)),
        "label_languages": langs,
        "orphan_classes": orphans,
        "sibling_groups": len(groups), "sibling_groups_with_disjointness": covered_groups,
        "properties_without_domain_or_range": no_domain_range,
        "inverse_conflicts": [f"{n} (inverse of {t}, which already has {k})" for n, t, k in inverse_conflicts(props)],
        "classes_per_module": modules,
    }


# ── inventory coverage ─────────────────────────────────────────────────────────
def _class_keys(c, key_fn) -> set:
    keys = {key_fn(c.get("name")), key_fn(re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(c.get("name") or "")))}
    keys |= {key_fn(v) for v in _labels(c).values()}
    keys |= {key_fn(v) for v in c.get("inventory_concepts") or []}
    return {k for k in keys if k}


def _humanize(name) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(name or "")).replace("_", " ").replace("-", " ")


def _tokens(text) -> list:
    """Word stems for containment tests ('encodes' and 'encode' -> 'encod')."""
    out = []
    for w in re.findall(r"[a-z0-9]+", _humanize(text).lower()):
        w = _stem(w)
        out.append(w[:-1] if len(w) > 4 and w.endswith("e") else w)
    return out


class ConceptIndex:
    """Finds the class, individual or property that represents an inventory concept or a term from the literature.
    Classes match through the link stored at generation (`inventory_concepts`) or by name/label; individuals by
    name/label; properties only if the concept's words occur in the property name ("Encode" in `encodesAttribute`)."""

    def __init__(self, onto, key_fn):
        self.key = key_fn
        self.classes = [c for c in onto.get("classes") or [] if isinstance(c, dict) and c.get("name")]
        self.by_key = {}
        for c in self.classes:
            for k in _class_keys(c, key_fn):
                self.by_key.setdefault(k, c["name"])
        self.individuals = {}
        for i in onto.get("individuals") or []:
            if isinstance(i, dict) and i.get("name"):
                for v in [i["name"], _humanize(i["name"]), *_labels(i).values(), *(i.get("inventory_concepts") or [])]:
                    if key_fn(v):
                        self.individuals.setdefault(key_fn(v), i["name"])
        self.properties = [(_tokens(p["name"]), p["name"]) for p in onto.get("properties") or []
                           if isinstance(p, dict) and p.get("name")]
        # die Begriffe, fuer die ein Modul eine Property angelegt hat (DECISIONS 136): hasTaskStability fuer
        # "stability of the task", was die Woerter allein nicht finden
        self.property_concepts = {}
        for p in onto.get("properties") or []:
            if isinstance(p, dict) and p.get("name"):
                for v in p.get("inventory_concepts") or []:
                    if key_fn(v):
                        self.property_concepts.setdefault(key_fn(v), p["name"])

    def class_for_text(self, text):
        k = self.key(text)
        return self.by_key.get(k) if k else None

    def class_of(self, concept):
        for v in [concept["label"], *concept.get("variants", [])]:
            hit = self.class_for_text(v)
            if hit:
                return hit
        return None

    def other_of(self, concept):
        """('individual' | 'property', name) if the concept is represented other than as a class."""
        variants = [concept["label"], *concept.get("variants", [])]
        for v in variants:
            if self.key(v) in self.individuals:
                return "individual", self.individuals[self.key(v)]
            if self.key(v) in self.property_concepts:
                return "property", self.property_concepts[self.key(v)]
        for v in variants:
            toks = _tokens(v)
            if not toks or len("".join(toks)) < 4:
                continue
            n = len(toks)
            for ptoks, name in self.properties:
                if any(ptoks[i:i + n] == toks for i in range(len(ptoks) - n + 1)):
                    return "property", name
        return None


def concept_coverage(onto, inventory, key_fn, decisions=None) -> dict:
    """How the inventory concepts are represented: as a class, otherwise (individual, or inside a property name),
    deliberately not modeled (a decision recorded when gaps were filled), or missing."""
    if not inventory or not inventory.get("concepts"):
        return {"available": False}
    idx = ConceptIndex(onto, key_fn)
    decisions = decisions or {}
    concepts = inventory["concepts"]
    status = {}
    for c in concepts:
        cls = idx.class_of(c)
        if cls:
            status[c["id"]] = ("class", cls)
            continue
        other = idx.other_of(c)
        if other:
            status[c["id"]] = other
        elif any(key_fn(v) in decisions for v in [c["label"], *c.get("variants", [])]):
            reason = next(decisions[key_fn(v)] for v in [c["label"], *c.get("variants", [])] if key_fn(v) in decisions)
            status[c["id"]] = ("decided", reason)
        else:
            status[c["id"]] = ("missing", None)
    central = [c for c in concepts if c.get("papers", 0) > 1]
    as_class = lambda cs: sum(1 for c in cs if status[c["id"]][0] == "class")
    themes = []
    by_id = {c["id"]: c for c in concepts}
    for t in inventory.get("themes") or []:
        members = [by_id[cid] for cid in t.get("concepts") or [] if cid in by_id]
        themes.append({"name": t["name"], "concepts": len(members), "covered": as_class(members),
                       "covered_pct": _pct(as_class(members), len(members))})
    pick = lambda kind: [{"label": c["label"], "sources": c.get("papers", 0), "as": status[c["id"]][1]}
                         for c in central if status[c["id"]][0] == kind]
    missing, other = pick("missing"), pick("individual") + pick("property")
    for o in other:
        o["kind"] = next(status[c["id"]][0] for c in central if c["label"] == o["label"])
    return {
        "available": True,
        "concepts": len(concepts), "covered": as_class(concepts), "covered_pct": _pct(as_class(concepts), len(concepts)),
        "central_concepts": len(central), "central_covered": as_class(central),
        "central_covered_pct": _pct(as_class(central), len(central)),
        "central_other": len(other), "central_decided": len(pick("decided")), "central_missing": len(missing),
        "central_represented_pct": _pct(len(central) - len(missing), len(central)),
        "themes": themes,
        "missing_central": sorted(missing, key=lambda m: -m["sources"])[:80],
        "other_central": sorted(other, key=lambda m: -m["sources"])[:80],
        "decided_central": pick("decided")[:80],
    }


def _ancestors(onto) -> dict:
    """class -> set of all superclasses (parent chain plus SubClassOf axioms)."""
    direct = {}
    for c in onto.get("classes") or []:
        if isinstance(c, dict) and c.get("name") and c.get("parent"):
            direct.setdefault(c["name"], set()).add(c["parent"])
    for a in onto.get("axioms") or []:
        if isinstance(a, dict) and a.get("type") == "SubClassOf" and len(a.get("classes") or []) == 2:
            direct.setdefault(a["classes"][0], set()).add(a["classes"][1])
    result = {}
    for start in direct:
        seen, todo = set(), list(direct[start])
        while todo:
            x = todo.pop()
            if x not in seen:
                seen.add(x)
                todo += list(direct.get(x, ()))
        result[start] = seen
    return result


def taxonomy_state(t, idx, anc, decided=()) -> tuple:
    """(relevant, open) einer Taxonomie der Literatur: relevant, wenn sie Klassen der Ontologie betrifft; offen, solange
    sie nicht entschieden ist und ihre Kategorien nicht unter ihrer Wurzel stehen (ohne Wurzel: bis zur Entscheidung)."""
    root = idx.class_for_text(t.get("name"))
    names = t.get("categories") or []
    cats = [idx.class_for_text(x.split(":")[-1]) for x in names]
    relevant = sum(1 for x in cats if x) >= 2 or bool(root and len(names) >= 3)
    done = {_norm(t.get("name")), _norm(f"Taxonomy '{t.get('name')}'")} & set(decided)
    pending = not root or not any(cats) or any(c and c != root and root not in anc.get(c, ()) for c in cats)
    return relevant, relevant and not done and pending

def hierarchy_coverage(onto, inventory, key_fn, decisions=None, declined=None) -> dict:
    """Taxonomic recall against the literature itself: of the broader/narrower relations the sources state between
    terms that are both classes of the ontology, how many does the class hierarchy realize (directly or transitively)?
    Relations come from the 'broader' statements of the paper cards and from their taxonomies (category -> taxonomy
    name). Also lists missing central concepts whose broader term already is a class (they can be attached directly).
    declined(narrower, broader) -> True for relations the team or the generation declined with a reason: they are
    reported apart, like decided central concepts (DECISIONS 111). declined.keys, if present, are the keys of all
    hierarchy decisions: a decided taxonomy is no longer open."""
    if not inventory or not inventory.get("concepts"):
        return {"available": False}
    idx = ConceptIndex(onto, key_fn)
    anc = _ancestors(onto)
    pairs = {}

    def add(narrow, broad, origin):
        if narrow and broad and narrow != broad:
            e = pairs.setdefault((narrow, broad), {"support": 0, "origins": set()})
            e["support"] += 1
            e["origins"].add(origin)

    attachable, decisions = [], decisions or {}
    for c in inventory["concepts"]:
        narrow = idx.class_of(c)
        broader = [s.get("broader") for s in c.get("sources") or [] if s.get("broader")]
        for b in broader:
            add(narrow, idx.class_for_text(b), "broader term")
        if not narrow and c.get("papers", 0) > 1 and not idx.other_of(c) and \
                not any(key_fn(v) in decisions for v in [c["label"], *c.get("variants", [])]):
            target = next((idx.class_for_text(b) for b in broader if idx.class_for_text(b)), None)
            if target:
                attachable.append({"label": c["label"], "broader": target, "sources": c.get("papers", 0)})
    relevant_taxonomies = open_taxonomies = 0
    for t in inventory.get("taxonomies") or []:
        root = idx.class_for_text(t.get("name"))
        cats = [idx.class_for_text(x.split(":")[-1]) for x in t.get("categories") or []]
        if root:
            for cat in cats:
                add(cat, root, "taxonomy")
        relevant, open_tax = taxonomy_state(t, idx, anc, getattr(declined, "keys", ()))
        relevant_taxonomies += relevant
        open_taxonomies += open_tax
    realized = [(n, b) for (n, b) in pairs if b in anc.get(n, ())]
    open_ = sorted(({"narrower": n, "broader": b, "support": e["support"], "origins": sorted(e["origins"])}
                    for (n, b), e in pairs.items() if b not in anc.get(n, ()) and n not in anc.get(b, ())),
                   key=lambda x: -x["support"])
    is_declined = declined or (lambda n, b: False)
    unrealized = [u for u in open_ if not is_declined(u["narrower"], u["broader"])]
    declined_rel = [u for u in open_ if is_declined(u["narrower"], u["broader"])]
    return {
        "available": True, "relations": len(pairs), "realized": len(realized),
        "realized_pct": _pct(len(realized), len(pairs)),
        "declined": declined_rel[:200], "declined_count": len(declined_rel),
        "realized_or_declined_pct": _pct(len(realized) + len(declined_rel), len(pairs)),
        "unrealized": unrealized[:200], "unrealized_count": len(unrealized),
        "attachable": sorted(attachable, key=lambda a: -a["sources"])[:120], "attachable_count": len(attachable),
        "relevant_taxonomies": relevant_taxonomies, "open_taxonomies": open_taxonomies,
    }


# ── traceability ───────────────────────────────────────────────────────────────
def traceability(onto, cq_reports, inventory, key_fn) -> dict:
    """Why does each class exist? A class is traceable if it has sources, is linked to an inventory concept,
    is used by a competency-question query that runs successfully, is a module's key notion or belongs to the
    upper layer. Classes with none
    of these are candidates for superfluous elements (the measure of Lippolis et al. 2025) - to be reviewed,
    not deleted automatically: a helper class can be legitimate.
    basis: "literature" when there are sources or an inventory; without them only the competency questions can
    trace a class ("competency questions"); without tested questions either nothing can ("none", no percentage)."""
    classes = [c for c in onto.get("classes") or [] if isinstance(c, dict) and c.get("name")]
    props = [p for p in onto.get("properties") or [] if isinstance(p, dict) and p.get("name")]
    used_full, used_any = set(), set()
    for rep in cq_reports:
        for t in (rep or {}).get("tests") or []:
            terms = set(t.get("terms") or [])
            used_any |= terms
            if t.get("status") == "passed":
                used_full |= terms
    # Eine bestandene Abfrage braucht auch die Klassen, die sie ueber ihre Properties erreicht (z.B. hasColor ->
    # WineColor), selbst wenn sie diese nicht beim Namen nennt (Wein-Lauf 2)
    used_full |= {p.get(k) for p in props if p["name"] in used_full for k in ("domain", "range") if p.get(k)}
    inv_keys = set()
    for c in (inventory or {}).get("concepts") or []:
        inv_keys |= {key_fn(v) for v in [c["label"], *c.get("variants", [])]}
    notions = {_norm(m.get("key_notion") or m.get("name")) for m in onto.get("modules") or [] if isinstance(m, dict)}

    rows, untraceable = [], []
    for c in classes:
        reasons = []
        if c.get("sources"):
            reasons.append("sources")
        if c.get("inventory_concepts") or (inv_keys & _class_keys(c, key_fn)):
            reasons.append("inventory")
        if c["name"] in used_full:
            reasons.append("cq")
        if _norm(c["name"]) in notions:
            reasons.append("key_notion")
        if c.get("layer") == "upper":   # part of the upper layer by design, not derived from the literature
            reasons.append("upper_layer")
        rows.append(reasons)
        if not reasons:
            untraceable.append(c["name"])
    n = len(classes)
    count = lambda r: sum(1 for x in rows if r in x)
    tested = any((rep or {}).get("tests") for rep in cq_reports)
    basis = ("literature" if inventory or count("sources") else "competency questions" if tested else "none")
    if basis == "none":
        untraceable = []
    return {
        "classes": n, "basis": basis,
        "with_sources_pct": _pct(count("sources"), n),
        "linked_to_inventory_pct": _pct(count("inventory"), n),
        "used_by_passing_cq_pct": _pct(count("cq"), n),
        "untraceable": untraceable, "untraceable_pct": None if basis == "none" else _pct(len(untraceable), n),
        "properties": len(props),
        "properties_used_by_cq_pct": _pct(sum(1 for p in props if p["name"] in used_any), len(props)),
        "properties_unused_by_cq": sorted(p["name"] for p in props if p["name"] not in used_any),
    }


# ── competency questions ───────────────────────────────────────────────────────
def cq_level(test) -> str:
    """full: the query runs and returns data. partial: a query could be written and uses ontology terms, but some
    term is missing, there is no answer on the sample data, or it answers only part of the question. none: no query could be written (or it does not parse)."""
    if test.get("status") == "passed":
        return "full"
    if test.get("status") == "partial":       # runs, but answers only part of the question (its author says so)
        return "partial"
    if test.get("status") == "failed" and test.get("parses") and test.get("terms"):
        return "partial"
    return "none"


def cq_coverage(report) -> dict:
    tests = (report or {}).get("tests") or []
    levels = [cq_level(t) for t in tests]
    return {"total": len(tests), "full": levels.count("full"), "partial": levels.count("partial"),
            "none": levels.count("none"), "full_pct": _pct(levels.count("full"), len(tests)),
            "at_least_partial_pct": _pct(len(tests) - levels.count("none"), len(tests)),
            "questions": [{"question": t.get("question"), "level": lvl, "error": t.get("error") or ""}
                          for t, lvl in zip(tests, levels)]}


def evaluation_summary(rep) -> dict:
    """Die Kennzahlen einer Evaluation, die eine spaetere mit ihr vergleicht (DECISIONS 136): vorher - Reparatur -
    nachher. Bei Evaluate 3x das Mittel der Laeufe, sonst der eine Test."""
    m, cov, hi = rep.get("metrics") or {}, rep.get("coverage") or {}, rep.get("hierarchy") or {}
    cq, ho = rep.get("cq") or {}, rep.get("holdout") or {}
    cr, hr = rep.get("cq_repeats") or {}, rep.get("holdout_repeats") or {}
    rs = (rep.get("reasoner") or {}).get("ontology") or {}
    return {"iteration": rep.get("iteration"), "evaluated_at": rep.get("evaluated_at"), "figures": {
        "classes": m.get("classes"), "object_properties": m.get("object_properties"),
        "restrictions": m.get("restrictions"), "root_classes": m.get("root_classes"),
        "top_level_relations_per_class": m.get("top_level_relations_per_class"),
        "central_as_class_pct": cov.get("central_covered_pct"),
        "central_represented_pct": cov.get("central_represented_pct"),
        "hierarchy_decided_pct": hi.get("realized_or_declined_pct"),
        "cq_full": (cr.get("full") or {}).get("mean", cq.get("full")),
        "holdout_full": (hr.get("full") or {}).get("mean", ho.get("full")),
        "reasoner_consistent": None if rs.get("error") else rs.get("consistent")}}


def cq_repeats(reports) -> dict:
    """Several independent tests of the same questions on the same ontology ("Evaluate 3x", PLAN.md phase 6): per run
    the number of questions answered in full, partially and not at all, their mean and spread, and per question in
    how many runs it was answered in full. A single run varied by up to 2 of 10 questions, so one run cannot show
    whether a change of 1 or 2 is an effect of the ontology."""
    covs = [cq_coverage(r) for r in reports]

    def stats(k):
        xs = [c[k] for c in covs]
        return {"runs": xs, "mean": round(statistics.mean(xs), 1),
                "sd": round(statistics.stdev(xs), 1) if len(xs) > 1 else 0.0}
    levels, errors = {}, {}
    for c in covs:
        for q in c["questions"]:
            levels.setdefault(q["question"], []).append(q["level"])
            errors.setdefault(q["question"], []).append((q.get("error") or "")[:300] if q["level"] != "full" else "")
    return {"runs": len(covs), "total": covs[0]["total"] if covs else 0,
            "full": stats("full"), "partial": stats("partial"), "none": stats("none"),
            "questions": [{"question": q, "levels": lv, "full": lv.count("full"), "errors": errors[q]}
                          for q, lv in levels.items()],
            "varying": sum(1 for lv in levels.values() if len(set(lv)) > 1)}


_STOP = set("""a an the of and or to in on for by with as is are be been being was were do does did can could
which what who whom whose where when how why that this these those it its from at into there their them they
has have had any all each some""".split())


def _stem(w) -> str:
    """Crude stemming, enough to see that 'supported' and 'supports' are about 'support' (and 'entities' about
    'entity')."""
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    for suffix in ("ing", "ed", "es", "s"):
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            return w[:-len(suffix)]
    return w


# Woerter einer Frage, die im Inventar als Begriff stehen koennen, aber nichts ueber den Inhalt sagen
_QUESTION_WORDS = {"what", "which", "how", "who", "when", "where", "why", "mean", "means", "given", "kind", "type"}


# Fragen danach, was sein kann, muss oder am besten ist, oder nach allen Moeglichkeiten: eine Ontologie mit
# Beispieldaten zeigt, was erfasst ist, und beantwortet sie nur zum Teil (VA 5c, Bruecke: 6 von 10, DECISIONS 134)
_MODAL = re.compile(r"\b(can|could|cannot|must|should|may|might|ought|need|needs|require|requires|required|help|helps|"
                    r"allow|allows|enable|enables|let|lets|every|possible|possibly|potentially|best|better|suitable|"
                    r"appropriate|effective)\b", re.I)
HOLDOUT_SELECTION_VERSION = 2      # 2: modale Fragen nach hinten (DECISIONS 134)


def modal_words(question) -> list:
    return list(dict.fromkeys(m.lower() for m in _MODAL.findall(str(question or ""))))


def _simple_key(term) -> str:
    words = re.findall(r"[a-z0-9]+", str(term or "").lower())
    return " ".join(words[:-1] + [_stem(words[-1])]) if words else ""


def _concept_index(inventory, key) -> dict:
    """Begriffsschluessel -> (Zahl der Quellen, Bezeichnung, Thema) fuer alle Begriffe des Inventars."""
    theme = {cid: t.get("name") for t in inventory.get("themes") or [] for cid in t.get("concepts") or []}
    index = {}
    for c in inventory.get("concepts") or []:
        if not isinstance(c, dict) or not c.get("label"):
            continue
        for v in [c["label"], *c.get("variants", [])]:
            k = key(v)
            if len(k) > 2 and k not in _STOP and k not in _QUESTION_WORDS and \
                    c.get("papers", 0) > index.get(k, (0,))[0]:
                index[k] = (c.get("papers", 0), c["label"], theme.get(c.get("id")))
    return index


def question_concepts(question, index, key) -> list:
    """Die Begriffe des Inventars, die eine Frage nennt: laengste Wortfolge zuerst (bis vier Woerter), jedes Wort
    nur einmal. Liefert (Zahl der Quellen, Bezeichnung, Thema, die Woerter der Frage)."""
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9-]*", str(question or ""))
    found, used = {}, set()
    for n in (4, 3, 2, 1):
        for i in range(len(words) - n + 1):
            if used & set(range(i, i + n)) or (n > 1 and words[i].lower() in ("a", "an", "the")):
                continue
            k = key(" ".join(words[i:i + n]))
            if k in index:
                found[k] = (*index[k], " ".join(words[i:i + n]))
                used |= set(range(i, i + n))
    return sorted(found.values(), key=lambda x: (-x[0], x[1]))


def holdout_details(inventory, questions, key=None) -> list:
    """Je Hold-out-Frage die zentralen Begriffe (zwei oder mehr Quellen), die sie nennt, und ihr Thema - fuer die
    Durchsicht durch das Team. Gezeigt wird das Wort der Frage, nicht die Bezeichnung des Inventars: dessen
    Zusammenfassung legt mitunter Fernes zusammen (VA: "patterns" unter "form")."""
    key = key or _simple_key
    index = _concept_index(inventory or {}, key)
    out = []
    for q in questions:
        cs = question_concepts(q, index, key)
        central = [c for c in cs if c[0] >= 2]
        out.append({"question": q, "central": [c[3] for c in central],
                    "single_source": [c[3] for c in cs if c[0] < 2],
                    "theme": next((c[2] for c in central if c[2]), None), "modal": modal_words(q)})
    return out


def select_holdout_cqs(inventory, team_cqs, limit=10, exclude=(), keep=(), key=None) -> list:
    """Questions extracted from the papers that were NOT given to the generator: they test whether the ontology
    answers what the literature asks, not only the questions it was built for. Near-duplicates of the team's
    questions are skipped (token overlap), and so are the questions in `exclude`: those a model has already seen
    while suggesting the team's questions (they would leak into the ontology and flatter the hold-out score), and
    those the team removed. `keep`: an earlier selection, kept as far as it is still eligible.

    Which questions (DECISIONS 133): almost every question comes from one paper, so the number of sources says
    nothing. A question counts by the concepts it names - preferably two or more central ones (two or more sources)
    and few that only one paper uses ("What components define a Vega-Lite unit specification?" names none). The set
    is spread over the themes of the inventory and the papers, so one area or one paper does not fill it.
    Questions about what can, must or should be, or about every possibility, come after the others (DECISIONS 134):
    an ontology with sample data answers them only in part, whatever it models."""
    inventory = inventory or {}
    key = key or _simple_key
    tok = lambda s: {_stem(w) for w in re.findall(r"[a-z0-9]+", str(s).lower()) if w not in _STOP and len(w) > 1}
    team = [tok(q) for q in team_cqs]
    seen = {" ".join(str(q).lower().split()) for q in exclude}
    def similar(a, b):
        return bool(a and b) and len(a & b) / len(a | b) >= 0.5
    index = _concept_index(inventory, key)
    rated = []
    for n, q in enumerate(sorted(inventory.get("competency_questions") or [], key=lambda x: -len(x.get("docs") or []))):
        text = q.get("question") if isinstance(q, dict) else None
        t = tok(text)
        if not t or " ".join(text.lower().split()) in seen or any(similar(t, x) for x in team):
            continue
        cs = question_concepts(text, index, key)
        central = [c for c in cs if c[0] >= 2]
        rare = len(cs) - len(central)
        tier = 0 if len(central) >= 2 and len(central) >= 2 * rare else 1 if central else 3
        if tier < 3 and modal_words(text):
            tier = 2
        theme = next((c[2] for c in central if c[2]), None)
        rated.append((tier, -len(central), -sum(c[0] for c in central), n, text, theme, q.get("docs") or []))
    rated.sort(key=lambda r: r[:4])
    by_text = {r[4]: r for r in rated}
    picked, per_theme, per_paper = [], {}, {}
    def take(r):
        picked.append(r[4])
        per_theme[r[5]] = per_theme.get(r[5], 0) + 1
        for d in r[6]:
            per_paper[d] = per_paper.get(d, 0) + 1
    for q in keep:
        if q in by_text and q not in picked and len(picked) < limit:
            take(by_text[q])
    # in Stufen: erst je Thema eine Frage der besten Gruppe, dann zwei, dann die naechste Gruppe; zuletzt ohne
    # Grenzen. Hoechstens zwei Fragen, deren Paper schon zweimal vertreten sind (ein Taxonomie-Paper mit vielen
    # Fragen soll den Satz nicht fuellen), ausser in der letzten Stufe
    stages = [((0,), 1, 2), ((0,), 2, 2), ((1,), 1, 2), ((1,), 2, 2), ((2,), 1, 2), ((2,), 2, 2),
              ((0, 1, 2, 3), None, 2), ((0, 1, 2, 3), None, None)]
    for tiers, theme_max, paper_max in stages:
        for r in rated:
            if len(picked) >= limit:
                return picked
            if r[0] not in tiers or r[4] in picked or any(similar(tok(r[4]), tok(p)) for p in picked):
                continue
            if theme_max and per_theme.get(r[5], 0) >= theme_max:
                continue
            if paper_max and r[6] and all(per_paper.get(d, 0) >= paper_max for d in r[6]):
                continue
            take(r)
    return picked


# ── reasoner ───────────────────────────────────────────────────────────────────
def java_available() -> bool:
    from shutil import which
    return bool(which("java") or os.environ.get("JAVA_HOME"))


def reasoner_check(turtle, sample_turtle="", timeout=REASONER_TIMEOUT) -> dict:
    """Consistency and unsatisfiable classes with HermiT - for the ontology alone and together with the CQ sample
    data (without individuals a consistent ontology proves little). Runs in a separate process: HermiT has no
    timeout of its own, and owlready2 keeps global state."""
    try:
        import owlready2  # noqa: F401
    except ImportError:
        return {"available": False, "reason": "owlready2 is not installed (pip install -r requirements.txt)"}
    if not java_available():
        return {"available": False, "reason": "Java is not installed; the HermiT reasoner needs it"}
    from rdflib import Graph
    tmp = tempfile.mkdtemp(prefix="odt-reasoner-")
    try:
        paths = {}
        g = Graph().parse(data=turtle, format="turtle")
        paths["ontology"] = os.path.join(tmp, "ontology.nt")
        g.serialize(paths["ontology"], format="nt", encoding="utf-8")
        if sample_turtle.strip():
            try:
                g.parse(data=sample_turtle, format="turtle")
                paths["with_sample_data"] = os.path.join(tmp, "with_data.nt")
                g.serialize(paths["with_sample_data"], format="nt", encoding="utf-8")
            except Exception:
                pass
        out = {"available": True}
        outside = _replace_non_owl2_datatypes(paths)
        if outside:
            out["datatypes_outside_owl2"] = outside
        for label, path in paths.items():
            try:
                proc = subprocess.run([sys.executable, os.path.abspath(__file__), "--reason", path],
                                      capture_output=True, text=True, timeout=timeout)
                out[label] = json.loads(proc.stdout.strip().splitlines()[-1]) if proc.stdout.strip() else \
                    {"error": (proc.stderr or "no output")[-300:]}
            except subprocess.TimeoutExpired:
                out[label] = {"error": f"the reasoner took longer than {timeout} s and was stopped"}
            except Exception as ex:
                out[label] = {"error": f"{type(ex).__name__}: {str(ex)[:200]}"}
        return out
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def _replace_non_owl2_datatypes(paths) -> dict:
    """The reasoner only knows the OWL 2 datatypes: a range outside them becomes rdfs:Literal, a literal of such a
    type a plain one, so the rest of the ontology is still checked. Returns {datatype: [properties]} to report."""
    from rdflib import Graph, Literal, RDFS, URIRef
    outside = {}
    for path in paths.values():
        g = Graph().parse(path, format="nt")
        changed = False
        for s, o in list(g.subject_objects(RDFS.range)):
            if isinstance(o, URIRef) and str(o).startswith(XSD) and str(o) not in OWL2_DATATYPES:
                outside.setdefault("xsd:" + str(o)[len(XSD):], set()).add(str(s).split("#")[-1].split("/")[-1])
                g.remove((s, RDFS.range, o)); g.add((s, RDFS.range, RDFS.Literal))
                changed = True
        for s, p, o in list(g):
            if isinstance(o, Literal) and o.datatype and str(o.datatype) not in OWL2_DATATYPES:
                outside.setdefault("xsd:" + str(o.datatype)[len(XSD):] if str(o.datatype).startswith(XSD)
                                   else str(o.datatype), set())
                g.remove((s, p, o)); g.add((s, p, Literal(str(o))))
                changed = True
        if changed:
            g.serialize(path, format="nt", encoding="utf-8")
    return {dt: sorted(props) for dt, props in sorted(outside.items())}


def _reason_file(path) -> dict:
    """Runs inside the child process."""
    import owlready2
    from shutil import which
    if not which("java") and os.environ.get("JAVA_HOME"):
        owlready2.JAVA_EXE = os.path.join(os.environ["JAVA_HOME"], "bin", "java")
    # owlready2 startet Java mit subprocess.check_output; mit einer Frist beendet check_output Java selbst - der Abbruch
    # dieses Kindprozesses von aussen liess Java weiterlaufen (Code-Review T13: bis 2 GB je Zeitueberschreitung)
    import functools, subprocess
    import owlready2.reasoning as reasoning
    reasoning.subprocess.check_output = functools.partial(subprocess.check_output, timeout=REASONER_TIMEOUT - 20)
    world = owlready2.World()
    world.get_ontology("file://" + path.replace("\\", "/")).load(format="ntriples")
    try:
        owlready2.sync_reasoner_hermit(world, infer_property_values=False, debug=0)
    except owlready2.OwlReadyInconsistentOntologyError:
        return {"consistent": False, "unsatisfiable": []}
    unsat = sorted({c.name for c in world.inconsistent_classes()} - {"Nothing"})
    return {"consistent": True, "unsatisfiable": unsat}


if __name__ == "__main__" and len(sys.argv) == 3 and sys.argv[1] == "--reason":
    try:
        result = _reason_file(sys.argv[2])
    except Exception as ex:  # noqa: BLE001 - reported to the parent as data
        result = {"error": f"{type(ex).__name__}: {str(ex)[:300]}"}
    print(json.dumps(result))
