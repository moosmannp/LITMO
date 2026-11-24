"""Verbesserungsaktionen: Upper Layer, Kernrelationen, Pakete, Entscheidungen, Reasoner-Pruefung."""

import re
from fastapi import HTTPException
from ontology_edits import EditError, Editor, IDENT, humanize, property_issues
from ontology_evaluation import _ancestors, ConceptIndex, hierarchy_coverage, reasoner_check, relation_pairs, taxonomy_state

from project import (apply_conventions, context_block, _cq_text, DECISION_KEYS, decision_store,  # noqa: F401
                     _momo, MOMO_METHOD, _norm, session_prefixes)
from ontology_io import ontology_to_turtle, validate_turtle
from corpus import concept_key, doc_citation, _existing_terms, _inventory_parts
from vocabularies import align_candidates, align_listing, build_align_intro, _clip, turtle_for_reasoning
from editing import edit_ontology
from testing import test_competency_questions, translate_cq_report
from generation import _theme_of
from upper import (clean_upper_layer, DEFAULT_UPPER_LAYER, _disjoint_text, ensure_upper_layer,  # noqa: F401
                   MAX_UPPER_CLASSES, remove_unused_upper, UPPER_MODULE, _upper_disjoint, upper_layer_of,
                   use_upper_layer)
from relations import (clean_property_vocab, CORE_MODULE, CORE_RELATIONS_LIMIT, core_relations_range,  # noqa: F401
                       ensure_core_module, relation_labels, _vocab_lines)

# ── Luecken schliessen (aus der Evaluation) ────────────────────────────────────
# Zwei Aktionen auf der bestehenden Ontologie, per Edit-Operationen statt Neugenerierung: fehlende zentrale Begriffe
# ergaenzen und die Hierarchie aus den Oberbegriffen und Taxonomien der Literatur aufbauen. Die Arbeit wird in
# Pakete geteilt, die der Browser nacheinander schickt (wie die Paper-Extraktion: Fortschritt sichtbar, abbrechbar,
# kein Hintergrundjob, der API-Key bleibt im Browser). Was das Modell bewusst nicht modelliert, wird mit Grund als
# Entscheidung gespeichert und beim naechsten Mal nicht wieder vorgelegt.
GAP_CONCEPTS_PER_BATCH = 12
GAP_RELATIONS_PER_BATCH = 25
GAP_TAXONOMIES_PER_BATCH = 6
GAP_UPPER_PER_BATCH = 25
GAP_KINDS = {"concepts": "Add concepts", "hierarchy": "Build hierarchy", "upper": "Group root classes",
             "properties": "Consolidate properties", "align": "Align with standards",
             "restrictions": "Add class restrictions"}

def upper_candidates(session) -> list:
    """Wurzelklassen, die noch unter die obere Schicht gehoeren: ohne Oberklasse (auch nicht per SubClassOf-Axiom),
    nicht selbst Teil der Schicht und nicht schon bewusst draussen gelassen."""
    onto = session.get("ontology") or {}
    upper = {_norm(x["name"]) for x in upper_layer_of(session)}
    decided = set(session.get("gap_upper_decisions") or [])
    has_super = {a["classes"][0] for a in onto.get("axioms") or []
                 if a.get("type") == "SubClassOf" and len(a.get("classes") or []) == 2}
    return [c for c in onto.get("classes") or [] if isinstance(c, dict) and c.get("name") and not c.get("parent")
            and c.get("layer") != "upper" and _norm(c["name"]) not in upper and c["name"] not in decided
            and c["name"] not in has_super]

def build_upper_intro(layer) -> str:
    disjoint = _upper_disjoint(layer)
    return (
        "The ontology has many root classes. Place each root class listed below under exactly ONE class of the upper "
        "layer (update_class with \"parent\"):\n" +
        "\n".join(f"- {x['name']}" + (f" (below {x['parent']})" if x["parent"] else "") + f": {x['definition']}"
                  for x in layer) + "\n"
        "Rules:\n"
        "- Decide by what the instances of the class ARE, not what they are about: a class of activities belongs with "
        "processes even if it is about data or things; a class of descriptions, plans or records belongs with "
        "information even if it describes an activity; a type, measure or level of something is a characteristic.\n" +
        (f"- {', '.join(disjoint[:-1])} and {disjoint[-1]} are disjoint: never place a class below two of them, and do "
         "not add SubClassOf axioms to another upper class.\n" if len(disjoint) > 1 else
         "- Never add SubClassOf axioms to a second upper class.\n") +
        "- If a class's description mixes two kinds (an activity and its result, say), choose the kind its subclasses "
        "and properties mostly assume and name the class in the summary - it is a candidate for splitting.\n"
        "- If no upper class fits, leave the class as it is and list it under \"skipped\" with a reason.\n"
        "- Change nothing else: no new classes, no renames, no other parents.\n"
        'Answer as {"summary":"...","ops":[...],"skipped":[{"item":"ClassName","reason":"..."}]}\n\nRoot classes:\n')

def _upper_batches(session) -> list:
    onto = session.get("ontology") or {}
    children = {}
    for c in onto.get("classes") or []:
        if isinstance(c, dict) and c.get("parent"):
            children[c["parent"]] = children.get(c["parent"], 0) + 1
    todo = sorted(upper_candidates(session), key=lambda c: (c.get("module") or "~", c["name"]))
    batches = []
    for i in range(0, len(todo), GAP_UPPER_PER_BATCH):
        part = todo[i:i + GAP_UPPER_PER_BATCH]
        lines = [f"- {c['name']} (module {c.get('module') or '-'}; {children.get(c['name'], 0)} subclasses): "
                 f"{(c.get('description') or '')[:220]}" for c in part]
        text = "\n".join(lines)
        batches.append({"items": [c["name"] for c in part], "request": build_upper_intro(upper_layer_of(session)) + text,
                        "focus": text})
    return batches

GAP_CONCEPT_INTRO = (
    "These concepts are CENTRAL in the literature corpus (defined by two or more sources) but not yet represented in "
    "the ontology. Decide for EACH one:\n"
    "- add it as a class: under the fitting superclass (where the sources name a broader term that is an existing "
    "class, it is given), in the module it belongs to, with labels, a description from the definitions, \"sources\" = "
    "the citations given, \"see_also\" = the existing-ontology URIs given and \"inventory_concepts\" = [the concept's "
    "label exactly as given];\n"
    "- or, if an existing class already represents exactly this concept under another name, link it: update_class "
    "with that class's name and \"inventory_concepts\" = [the label as given] - do not create a duplicate;\n"
    "- or add it as an individual of a fitting class (a single named thing, e.g. one specific framework), or as a "
    "property (a relation or an attribute);\n"
    "- or do not model it: out of scope per the project context, too specific, a variant that an existing class "
    "covers only partly (name it), or not a domain concept.\n"
    "Prefer attaching new classes below existing ones over creating new root classes. Add DisjointClasses for new "
    "sibling classes that cannot share instances. List EVERY concept you do not model under \"skipped\" with a short "
    'reason. Answer as {"summary":"...","ops":[...],"skipped":[{"concept":"the label as given","reason":"..."}]}\n\n'
    "Concepts:\n")

GAP_HIERARCHY_INTRO = (
    "The literature states broader/narrower relations and taxonomies that the class hierarchy does not yet reflect. "
    "Use them to give the ontology a deeper, well-founded hierarchy:\n"
    "- For each relation 'A is a kind of B' between existing classes: make B the superclass of A (update_class "
    "parent) if it holds in this ontology. If A already has a different superclass that also holds, add a SubClassOf "
    "axiom instead of replacing it. Skip relations that are wrong here - the papers sometimes use 'broader' loosely, "
    "for part-of or related-to.\n"
    "- For each taxonomy: arrange its categories as subclasses of the class the taxonomy classifies (create that class "
    "or intermediate classes only if they are real domain concepts), reuse existing classes for categories, add "
    "missing categories as classes only if they are worth modeling, and add DisjointClasses for categories that cannot "
    "overlap. Give every class you add \"sources\" = the citation given with its taxonomy.\n"
    "- Never create cycles. Keep the module structure; a class may have a superclass in another module.\n"
    'List what you deliberately do not apply under "skipped" with a short reason. Answer as {"summary":"...",'
    '"ops":[...],"skipped":[{"item":"the relation or taxonomy as given","reason":"..."}]}\n\n')

def _gap_concept_text(c, docs, idx) -> str:
    lines = [f'- "{c["label"]}" ({c.get("papers", 0)} sources)' +
             (f" [also: {', '.join(c['variants'][:5])}]" if c.get("variants") else "")]
    if c.get("definition"):
        lines.append(f"  definition: {c['definition']}")
    else:
        for s in [s for s in c["sources"] if s.get("definition")][:2]:
            lines.append(f"  definition ({doc_citation(docs[s['doc']]) if s['doc'] in docs else s['doc']}): {s['definition'][:300]}")
    broader = list(dict.fromkeys(s["broader"] for s in c["sources"] if s.get("broader")))
    if broader:
        lines.append("  broader in the sources: " + "; ".join(
            b + (f" (existing class {idx.class_for_text(b)})" if idx.class_for_text(b) else "") for b in broader[:4]))
    cites = list(dict.fromkeys(doc_citation(docs[s["doc"]]) for s in c["sources"] if s["doc"] in docs))
    if cites:
        lines.append("  citations: " + " | ".join(cites[:4]))
    uris = [s["uri"] for _, s in _existing_terms(c, docs)]
    if uris:
        lines.append("  existing-ontology terms: " + ", ".join(uris[:3]))
    return "\n".join(lines)

def build_gap_batches(session, kind) -> list:
    if kind == "upper":
        return _upper_batches(session)
    if kind == "properties":
        return _property_batches(session)
    if kind == "align":
        return _align_batches(session)
    if kind == "restrictions":
        return _restriction_batches(session)
    onto = session.get("ontology") or {}
    inv, docs, _ = _inventory_parts(session)
    if not inv:
        return []
    idx = ConceptIndex(onto, concept_key)
    batches = []
    if kind == "concepts":
        decided = session.get("gap_decisions") or {}
        todo = [c for c in inv["concepts"] if c.get("papers", 0) > 1 and not idx.class_of(c) and not idx.other_of(c)
                and not any(concept_key(v) in decided for v in [c["label"], *c.get("variants", [])])]
        module_of = {c["name"]: c.get("module") or "" for c in onto.get("classes") or [] if isinstance(c, dict)}
        theme_of = _theme_of(inv)
        def target(c):
            return next((idx.class_for_text(s["broader"]) for s in c["sources"]
                         if s.get("broader") and idx.class_for_text(s["broader"])), None)
        # erst die direkt anhaengbaren (nach Modul ihrer Oberklasse gruppiert), dann der Rest nach Thema
        todo.sort(key=lambda c: (0, module_of.get(target(c), "")) if target(c) else (1, theme_of.get(c["id"], "~")))
        for i in range(0, len(todo), GAP_CONCEPTS_PER_BATCH):
            part = todo[i:i + GAP_CONCEPTS_PER_BATCH]
            texts = [_gap_concept_text(c, docs, idx) for c in part]
            batches.append({"items": [c["label"] for c in part], "request": GAP_CONCEPT_INTRO + "\n".join(texts),
                            "focus": "\n".join(texts)})
    elif kind == "hierarchy":
        decided = set(session.get("gap_hierarchy_decisions") or [])
        h = hierarchy_coverage(onto, inv, concept_key)
        relations = [f"{u['narrower']} is a kind of {u['broader']}" for u in h["unrealized"]]
        relations = [r for r in relations if _norm(r) not in decided]
        for i in range(0, len(relations), GAP_RELATIONS_PER_BATCH):
            part = relations[i:i + GAP_RELATIONS_PER_BATCH]
            text = "Relations stated by the sources:\n" + "\n".join("- " + r for r in part)
            batches.append({"items": part, "request": GAP_HIERARCHY_INTRO + text, "focus": text})
        taxonomies, seen, anc = [], set(), _ancestors(onto)
        for t in inv.get("taxonomies") or []:
            root = idx.class_for_text(t.get("name"))
            cats = t.get("categories") or []
            key = _norm(t.get("name"))
            # nur offene: eine schon angewandte oder entschiedene ("Taxonomy 'X'") Taxonomie nicht noch einmal senden
            if key in seen or not taxonomy_state(t, idx, anc, decided)[1]:
                continue
            seen.add(key)
            src = doc_citation(docs[t["doc"]]) if t.get("doc") in docs else ""
            taxonomies.append((t["name"], f"- Taxonomy '{t['name']}'" + (f" ({src})" if src else "") +
                               (f", classifies the existing class {root}" if root else "") + ": " + "; ".join(cats[:25])))
        for i in range(0, len(taxonomies), GAP_TAXONOMIES_PER_BATCH):
            part = taxonomies[i:i + GAP_TAXONOMIES_PER_BATCH]
            text = "Taxonomies from the literature:\n" + "\n".join(t for _, t in part)
            batches.append({"items": [f"Taxonomy '{n}'" for n, _ in part], "request": GAP_HIERARCHY_INTRO + text,
                            "focus": text})
    return batches

def link_new_classes(before, onto, labels, inventory) -> list:
    """Fallback, falls das Modell den Link vergisst: eine im Paket NEU angelegte Klasse ohne inventory_concepts wird
    mit dem Begriff des Pakets verknuepft, dessen Name (oder Variante) Wort fuer Wort am Anfang oder Ende ihres Namens
    oder Labels steht ("Incomplete Knowledge" -> IncompleteKnowledgeEvent) - nur wenn genau ein Begriff passt."""
    by_label = {c["label"]: c for c in (inventory or {}).get("concepts") or []}
    concepts = [(lab, [concept_key(v).split() for v in [lab, *by_label[lab].get("variants", [])] if concept_key(v)])
                for lab in labels if lab in by_label]
    old = {c.get("name") for c in before.get("classes") or []}
    linked = []
    for c in onto.get("classes") or []:
        if c.get("name") in old or c.get("inventory_concepts"):
            continue
        names = [concept_key(c.get("name")).split()] + [concept_key(l).split() for l in (c.get("labels") or {}).values()]
        def fits(words):   # a single short word ("map", "area") would match too much
            if len(words) < 2 and len(words[0]) < 6:
                return False
            return any(n[:len(words)] == words or n[-len(words):] == words for n in names if len(n) >= len(words))
        hits = [lab for lab, variants in concepts if any(fits(w) for w in variants)]
        if len(hits) == 1:
            c["inventory_concepts"] = hits
            linked.append(f"{c['name']} -> {hits[0]}")
    return linked

# ── Properties konsolidieren (DECISIONS 70) ────────────────────────────────────
# Generierte Ontologien haben oft eine Property je Klassenpaar. Das Modell schlaegt ein Kernvokabular allgemeiner
# Relationen vor, das Team gibt es frei, dann wird jede bestehende Property in Paketen zugeordnet: in eine Kernrelation
# ueberfuehrt (merge), darunter gehaengt (Subproperty) oder mit Begruendung behalten. Alles domaenenunabhaengig: das
# Vokabular entsteht aus den Properties dieser Ontologie, nicht aus einer festen Liste.
GAP_PROPERTIES_PER_BATCH = 40

PROPERTY_VOCAB_SYS = (
    MOMO_METHOD + "\nYou design the CORE RELATION VOCABULARY of an existing OWL ontology. Its object properties are "
    "often narrow - one property per pair of classes - which makes them hard to reuse and query and lets the "
    "reasoner draw wrong conclusions from narrow domains and ranges. Propose a small set of general relations "
    "({size}, fewer if fewer are needed) that together cover what "
    "the existing properties express.\n"
    "Rules:\n"
    "1. Name a relation by its general meaning (lowerCamelCase verb phrase), never by the classes it connects. Typical "
    "general relations are part-whole, temporal order, participation, input and output, use, creation, description or "
    "representation, location, causation, membership - include only those this ontology actually needs, and add "
    "domain-specific ones where the existing properties share a meaning none of these captures.\n"
    "2. Domain and range: the most specific class that still covers the domains and ranges of the existing "
    "properties the relation will absorb - prefer upper-layer or module root classes; leave empty when it can relate "
    "anything. Use only class names from the listing.\n"
    "3. Give an inverse only when both directions are needed, with its own name and description.\n"
    "4. Characteristics: transitive only if A r B and B r C always imply A r C (part-whole, temporal order); "
    "functional only if a subject can never have two different values; symmetric only if A r B always implies B r A; "
    "asymmetric if A r B excludes B r A. Never combine transitive with functional or asymmetric.\n"
    "5. Under \"covers\" list existing property names the relation would absorb or generalize (a representative "
    "sample; every relation should cover at least two).\n"
    "6. Give each relation and inverse \"labels\" in every language listed under \"Label languages\" in the project "
    "conventions (lowercase verb phrases, e.g. \"has part\").\n"
    'Answer ONLY as JSON: {"summary":"how the vocabulary is organized","relations":[{"name":"...",'
    '"labels":{"<language code>":"label"},"description":"...","domain":"Class or empty","range":"Class or empty",'
    '"inverse":{"name":"...","labels":{"<language code>":"label"},"description":"..."} or null,'
    '"characteristics":[],"covers":["existingProperty", "..."]}]}')

PROPERTY_MAP_INTRO = (
    "The team approved these CORE RELATIONS for the ontology (they exist now; never change them):\n{core}\n\n"
    "Decide for EACH property listed below:\n"
    "- merge_property into a core relation when the property says nothing beyond that relation restricted to "
    "particular classes (only its domain and range differ);\n"
    "- update_property with \"sub_property_of\" = a core relation when the property has a meaning of its own that a "
    "query would need and the core relation does not express (a more specific way of relating);\n"
    "- keep it as it is when no core relation fits - list it under \"skipped\" with the reason.\n"
    "Decide only for the listed property; its inverse follows automatically. A core relation's domain and range must "
    "contain the property's domain and range, otherwise the server rejects the operation - then choose another core "
    "relation or keep the property. Change nothing else.\n"
    'Answer as {{"summary":"...","ops":[...],"skipped":[{{"item":"propertyName","reason":"..."}}]}}\n\nProperties:\n')

def _relation_line(p, with_module=True):
    return (f"- {p['name']}" + (f" (module {p.get('module')})" if with_module and p.get("module") else "") +
            f": {p.get('domain') or '(any)'} -> {p.get('range') or '(any)'}" +
            (f", inverse {p['inverse_of']}" if p.get("inverse_of") else "") +
            (f", below {p['sub_property_of']}" if p.get("sub_property_of") else "") +
            (f": {_clip(p.get('description'))}" if p.get("description") else ""))

def build_property_vocab_prompt(session) -> list:
    onto = session.get("ontology") or {}
    classes = [c for c in onto.get("classes") or [] if isinstance(c, dict) and c.get("name")]
    names = {c["name"] for c in classes}
    tops = [c for c in classes if not c.get("parent") or c.get("parent") not in names
            or next((x for x in classes if x["name"] == c["parent"]), {}).get("layer") == "upper"]
    pairs = relation_pairs(onto.get("properties") or [])
    lines = ["Upper-level and root classes (candidates for domain and range):"]
    lines += [f"- {c['name']}" + (f" (below {c['parent']})" if c.get("parent") else "") + f": {_clip(c.get('description'), 90)}"
              for c in tops]
    lines += ["", "All classes: " + ", ".join(sorted(names)), "",
              f"Existing object properties ({len(pairs)} relations, one direction of each inverse pair shown):"]
    lines += [_relation_line(p) for p in pairs]
    # der Umfang folgt der Groesse der Ontologie (DECISIONS 130); PROPERTY_VOCAB_SYS enthaelt JSON-Klammern, daher replace
    lo, hi = core_relations_range(len(classes))
    return [{"role": "system", "content": PROPERTY_VOCAB_SYS.replace("{size}", f"about {lo} to {hi}")},
            {"role": "user", "content": context_block(session) + "\n\n" + "\n".join(lines)}]

def core_relation_ops(vocab, onto, langs=("en",)) -> list:
    """Edit-Operationen, die das freigegebene Vokabular anlegen. Eine bestehende Property gleichen Namens wird zur
    Kernrelation (Domain, Range, Eigenschaften werden angeglichen). Ihre alte Inverse wird dabei geloest: sie gehoerte
    zur engen Property, und an der erweiterten Kernrelation wuerde sie falsche Typen folgern (DECISIONS 71)."""
    existing = {_norm(p.get("name")) for p in onto.get("properties") or [] if isinstance(p, dict)}
    # schon Kernrelationen (ein frueherer Lauf): Inverse und Oberproperty bleiben - z.B. eine Anbindung an prov:
    core = {_norm(p.get("name")) for p in onto.get("properties") or [] if isinstance(p, dict) and p.get("module") == CORE_MODULE}
    ops, later = [], []
    for r in vocab:
        base = {"name": r["name"], "type": "ObjectProperty", "description": r["description"], "module": CORE_MODULE,
                "labels": relation_labels(r, list(langs)),
                "domain": r["domain"] or None, "range": r["range"] or None, "characteristics": r["characteristics"]}
        if _norm(r["name"]) in existing and _norm(r["name"]) not in core:
            # inverse_of null zuerst: die Inverse des Vokabulars verknuepft sich danach in beide Richtungen neu
            base.update(inverse_of=None, sub_property_of=None)
        ops.append({**base, "op": "update_property" if _norm(r["name"]) in existing else "add_property"})
        if r["inverse"]:
            inv = {"name": r["inverse"]["name"], "type": "ObjectProperty", "description": r["inverse"]["description"],
                   "labels": relation_labels(r["inverse"], list(langs)),
                   "module": CORE_MODULE,
                   "domain": r["range"] or None, "range": r["domain"] or None, "inverse_of": r["name"],
                   # the inverse of a transitive/symmetric relation has the same characteristic
                   "characteristics": [c for c in r["characteristics"] if c in ("transitive", "symmetric")]}
            if _norm(inv["name"]) in existing and _norm(inv["name"]) not in core:
                inv["sub_property_of"] = None
            later.append({**inv, "op": "update_property" if _norm(inv["name"]) in existing else "add_property"})
    return ops + later

def _property_batches(session) -> list:
    onto = session.get("ontology") or {}
    vocab = (session.get("property_vocab") or {}).get("relations") or []
    core = {_norm(r["name"]) for r in vocab} | {_norm(r["inverse"]["name"]) for r in vocab if r.get("inverse")}
    decided = {_norm(n) for n in session.get("gap_property_decisions") or []}
    by = {p["name"]: p for p in onto.get("properties") or [] if isinstance(p, dict) and p.get("name")}
    todo = []
    for p in relation_pairs(onto.get("properties") or []):
        names = {_norm(p["name"]), _norm(p.get("inverse_of"))} - {""}
        inv = by.get(p.get("inverse_of")) or {}
        # already mapped: below another property (either direction), part of the vocabulary, or kept on purpose
        if names & core or names & decided or p.get("sub_property_of") or inv.get("sub_property_of"):
            continue
        todo.append(p)
    order = {m.get("name"): i for i, m in enumerate(onto.get("modules") or [])}
    todo.sort(key=lambda p: (order.get(p.get("module"), 999), p["name"]))
    intro = PROPERTY_MAP_INTRO.format(core=_vocab_lines(vocab))
    batches = []
    for i in range(0, len(todo), GAP_PROPERTIES_PER_BATCH):
        part = todo[i:i + GAP_PROPERTIES_PER_BATCH]
        text = "\n".join(_relation_line(p) for p in part)
        batches.append({"items": [p["name"] for p in part], "request": intro + text, "focus": text})
    return batches

# ── An Standards ausrichten (DECISIONS 75) ─────────────────────────────────────
# Eigene Klassen und Properties an Terme der geladenen Vokabulare anbinden (SubClassOf, EquivalentClasses,
# subPropertyOf). Kandidaten findet der Server ohne Modell ueber Namen und Labels; das Modell entscheidet nach Bedeutung;
# der Server prueft, dass der Term existiert, Domain/Range passen und der Reasoner mit den Vokabular-Axiomen zustimmt.
GAP_ALIGN_PER_BATCH = 25

def _align_batches(session) -> list:
    cands = align_candidates(session)
    order = {m.get("name"): i for i, m in enumerate((session.get("ontology") or {}).get("modules") or [])}
    cands.sort(key=lambda c: (c["kind"] != "class", order.get(c.get("module"), 999), c["name"]))
    intro = build_align_intro(session)
    batches = []
    for i in range(0, len(cands), GAP_ALIGN_PER_BATCH):
        part = cands[i:i + GAP_ALIGN_PER_BATCH]
        text = align_listing(part)
        batches.append({"items": [c["name"] for c in part], "request": intro + text, "focus": text})
    return batches


# ── Klassenrestriktionen (PLAN.md Phase 5, DECISIONS 125) ──────────────────────
# Klassenpaare, die die Ontologie nur lose verbindet, mit ihren Belegen: eine spezifische Property, die eine
# Konsolidierung in eine allgemeine zusammengefuehrt hat (ihr Domain-Range-Paar ging dabei verloren), eine Relation, die
# mehrere Quellen nennen, oder eine Property, die eine bestandene Kompetenzfrage nutzt. Das Modell entscheidet je Paar,
# ob eine Restriktion fuer JEDE Instanz gilt; der Editor prueft Domain und Range, der Reasoner-Waechter die Folgen.
GAP_RESTRICTIONS_PER_BATCH = 30
RESTRICTION_MIN_PAPERS = 2

GAP_RESTRICTION_INTRO = (
    "These pairs of classes are connected only loosely in the ontology - each comes with its evidence: a specific "
    "property that was merged into a broader one, a relation the literature states, or a property a passing "
    "competency question uses. Decide for EACH pair whether a class restriction holds, and write it with "
    "add_restriction:\n"
    "- some: EVERY instance of the first class has at least one such relation to an instance of the second (\"every "
    "A p some B\"); only: all its values of that property are of the second class; min, max, exactly n: a number "
    "the domain requires.\n"
    "- Use the most specific existing property whose domain covers the first class and whose range covers the "
    "second - usually the one named in the evidence or the broader one it was merged into. Do not create "
    "properties or classes.\n"
    "- Write no restriction where the relation holds only for some instances, is typical rather than necessary, "
    "or the evidence is wrong; list that pair under \"skipped\" with the reason.\n"
    'Answer as {"summary":"...","ops":[...],"skipped":[{"item":"the pair as given (A -> B)","reason":"..."}]}\n\n'
    "Pairs:\n")

def restriction_candidates(session) -> list:
    """Klassenpaare (A -> B) mit Belegen, die noch keine Restriktion haben und nicht entschieden sind."""
    onto = session.get("ontology") or {}
    classes = {c["name"]: c for c in onto.get("classes") or [] if isinstance(c, dict) and c.get("name")}
    props = {p["name"]: p for p in onto.get("properties") or [] if isinstance(p, dict) and p.get("name")}
    own = lambda n: n in classes and classes[n].get("layer") != "upper"
    have = {(r.get("class"), r.get("value")) for r in onto.get("restrictions") or [] if isinstance(r, dict)}
    decided = decision_store(session, "restrictions")
    pairs = {}

    def add(a, b, evidence, prop=None):
        if not (own(a) and own(b)) or (a, b) in have or f"{a} -> {b}" in decided:
            return
        e = pairs.setdefault(f"{a} -> {b}", {"item": f"{a} -> {b}", "class": a, "value": b,
                                             "module": classes[a].get("module"), "evidence": [], "properties": []})
        if evidence not in e["evidence"]:
            e["evidence"].append(evidence)
        if prop in props and prop not in e["properties"]:
            e["properties"].append(prop)
    for m in session.get("merge_records") or []:
        # nur, wenn die Zusammenfuehrung noch gilt (ein zurueckgenommenes Paket hat die Property wieder)
        if isinstance(m, dict) and m.get("property") not in props and m.get("type") != "DatatypeProperty":
            add(m.get("domain"), m.get("range"), f"merged property {m.get('property')} (into {m['into']})"
                if m.get("into") else f"property {m.get('property')}, removed by a consolidation", m.get("into"))
    inv, _, _ = _inventory_parts(session)
    if inv:
        idx = ConceptIndex(onto, concept_key)
        by_id = {c["id"]: c for c in inv.get("concepts") or []}
        for rel in inv.get("relations") or []:
            if len(rel.get("docs") or []) < RESTRICTION_MIN_PAPERS:
                continue
            ends = [idx.class_of(by_id[rel[k + "_id"]]) if rel.get(k + "_id") in by_id else idx.class_for_text(rel.get(k))
                    for k in ("subject", "object")]
            if all(ends):
                add(ends[0], ends[1], f"literature: '{rel.get('subject')} {rel.get('relation')} {rel.get('object')}' "
                                      f"({len(rel['docs'])} papers)")
    result = ((session.get("cq_test_report") or {}).get("result") or {})
    used = {t for x in result.get("tests") or [] if x.get("status") == "passed" for t in x.get("terms") or []}
    for name in sorted(used):
        p = props.get(name)
        if p and p.get("type") == "ObjectProperty" and p.get("module") != CORE_MODULE:
            add(p.get("domain"), p.get("range"), f"property {name} used by a passing competency question", name)
    order = {m.get("name"): i for i, m in enumerate(onto.get("modules") or [])}
    return sorted(pairs.values(), key=lambda e: (order.get(e["module"], 999), e["item"]))

def _restriction_batches(session) -> list:
    cands = restriction_candidates(session)
    batches = []
    for i in range(0, len(cands), GAP_RESTRICTIONS_PER_BATCH):
        part = cands[i:i + GAP_RESTRICTIONS_PER_BATCH]
        text = "\n".join(f"- {c['item']}: " + "; ".join(c["evidence"][:4]) +
                         (f" [properties named: {', '.join(c['properties'])}]" if c["properties"] else "") for c in part)
        batches.append({"items": [c["item"] for c in part], "request": GAP_RESTRICTION_INTRO + text, "focus": text})
    return batches


def decisions_report(session) -> dict:
    return {kind: [{"key": k, "item": (v or {}).get("item") or k, "reason": (v or {}).get("reason") or ""}
                   for k, v in decision_store(session, kind).items()] for kind in DECISION_KEYS}

def _unsatisfiable(turtle, session=None):
    """Unerfuellbare Klassen laut HermiT, oder None, wenn der Reasoner nicht laeuft (kein Java, Timeout ...).
    Mit Session: zusammen mit den Axiomen der verwendeten Vokabular-Terme."""
    r = reasoner_check(turtle_for_reasoning(session, turtle) if session else turtle)
    o = r.get("ontology") or {}
    if not r.get("available") or o.get("error"):
        return None
    if o.get("consistent") is False:
        return {"(the ontology is inconsistent)"}
    return set(o.get("unsatisfiable") or [])

def _reasoner_guard(session, llm_config, run, before, onto, turtle, label, standards):
    baseline = run.get("unsat_baseline")
    if baseline is None:
        return onto, turtle, {"checked": False}
    found = _unsatisfiable(turtle, session)
    if found is None:              # Java fehlt, Zeitueberschreitung ...: nicht "geprueft, nichts Neues"
        return onto, turtle, {"checked": False, "reason": "the reasoner could not run"}
    new = found - set(baseline)
    if not new:
        return onto, turtle, {"checked": True, "new_unsatisfiable": []}
    classes = sorted(n for n in new if not n.startswith("("))
    problem = ("made the ontology INCONSISTENT - an individual now belongs to classes that are disjoint"
               if len(classes) < len(new) else "")
    if classes:
        problem += (" and " if problem else "made ") + ("these classes UNSATISFIABLE - they can have no instances, "
                    "usually because a new superclass is disjoint with another of their superclasses: " + ", ".join(classes))
    request = ("Your last changes " + problem + ". Resolve this with the smallest change: revert or change the "
               "superclass, or remove a disjointness axiom only if it is wrong in the domain.")
    try:
        fixed, _ = edit_ontology(session, llm_config, onto, request, label + " (reasoner fix)")
        apply_conventions(fixed, session)
        fixed_turtle = ontology_to_turtle(fixed, standards, session_prefixes(session, fixed))
        still = _unsatisfiable(fixed_turtle, session)
        if still is not None and not (still - set(baseline)) and validate_turtle(fixed_turtle)[0]:
            return fixed, fixed_turtle, {"checked": True, "new_unsatisfiable": sorted(new), "corrected": True}
    except Exception:
        pass
    old_turtle = ontology_to_turtle(before, standards, session_prefixes(session, before))
    return before, old_turtle, {"checked": True, "new_unsatisfiable": sorted(new), "reverted": True}

def _property_regression(session, llm_config, turtle, run=None):
    """Nach der Konsolidierung die CQs des Teams erneut testen. Abfragen, die eine ueberfuehrte Property nutzten,
    bestehen auf den alten Daten nicht mehr und werden neu geschrieben; faellt eine vorher bestandene Frage durch,
    ist das ein Hinweis auf verlorene Bedeutung."""
    cqs = [_cq_text(c) for c in _momo(session).get("competency_questions", []) if _cq_text(c)]
    prev = (session.get("cq_test_report") or {}).get("result")
    if not cqs or not llm_config:
        return {"tested": False, "reason": "no competency questions" if not cqs else "no LLM configured"}
    # alte Daten und Abfragen durch die Zusammenfuehrungen uebersetzen; sonst reissen die Datenketten und jede
    # Abfrage mit einer ueberfuehrten Property gilt als 'durchgefallen' (DECISIONS 71)
    merged = (run or {}).get("merged") or {}
    namespace = (session.get("ontology") or {}).get("namespace") or ""
    translated, n_translated = translate_cq_report(prev, merged, namespace)
    hold, _ = translate_cq_report(session.get("holdout_test_report"), merged, namespace)
    if hold:
        session["holdout_test_report"] = hold        # die Evaluation testet den Hold-out danach auf denselben Daten
    try:
        result = test_competency_questions(turtle, cqs, llm_config, context_block(session), previous=translated)
    except Exception as ex:
        return {"tested": False, "reason": str(getattr(ex, "detail", ex))}
    session["cq_test_report"] = {"iteration": session.get("iterations"), "result": result}
    before = {_norm(t["question"]) for t in (prev or {}).get("tests") or [] if t.get("status") == "passed"}
    now = {_norm(t["question"]) for t in result["tests"] if t.get("status") == "passed"}
    return {"tested": True, "result": result, "passed_before": len(before) if prev else None,
            "passed_after": result["passed"], "total": result["total"], "translated": n_translated,
            "merged": len(merged),
            "regressions": [t["question"] for t in result["tests"] if _norm(t["question"]) in before - now]}
