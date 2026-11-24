"""Kernrelationen: ein kleines Vokabular allgemeiner Relationen, das das Team freigibt (DECISIONS 70, 89).

Zwei Wege fuehren zum Vokabular: vor der Generierung aus den Kompetenzfragen, den Key Notions und den Relationen der
Literatur (Schritt 7, Basis "plan"), oder als Reparatur aus den Properties einer fertigen Ontologie (Basis
"ontology", improvements.py). Die Generierung legt ein freigegebenes Vokabular als eigenes Modul an, die Module
verwenden es und haengen eigene Properties nur darunter. Hier liegt, was Generierung und Reparatur teilen.
"""

from fastapi import HTTPException
from ontology_edits import EditError, Editor, humanize, IDENT, property_issues
from ontology_evaluation import relation_pairs

from project import _class_name, context_block, _cq_text, MOMO_METHOD, named_notions, _norm
from corpus import _inventory_parts, _plain
from vocabularies import _clip
from definitions import decided_classes
from upper import upper_layer_of, use_upper_layer

# Kernrelationen und Relationsstruktur relativ zur Groesse der Ontologie statt fester Zahlen (DECISIONS 130):
# der Vorschlag im Reparaturwerkzeug 0.15-0.25 Kernrelationen je Klasse (VA mit 264 Klassen: 40-66, wie zuvor 40-70),
# der Richtwert der Evaluation hoechstens 0.3 Relationen oben je Klasse; unter 10 ist nichts zu konsolidieren
CORE_PER_CLASS = (0.15, 0.25)
TOP_LEVEL_PER_CLASS_MAX = 0.3
TOP_LEVEL_MIN = 10
CORE_RELATIONS_LIMIT = 120          # harte Grenze beim Speichern
CORE_MODULE = "CoreRelations"       # Modul der freigegebenen Kernrelationen (opla:isNativeTo)
PLAN_LITERATURE_RELATIONS = 250     # Relationen der Literatur im Vorschlags-Prompt, die mit den meisten Quellen zuerst

def core_relations_range(n_classes) -> tuple:
    """Umfang eines Kernvokabulars fuer eine Ontologie dieser Groesse, mindestens 3 bis 5."""
    lo = max(3, round(CORE_PER_CLASS[0] * n_classes))
    return lo, max(lo + 2, round(CORE_PER_CLASS[1] * n_classes))

def ensure_core_module(onto):
    if not any(m.get("name") == CORE_MODULE for m in onto.get("modules") or []):
        onto.setdefault("modules", []).append({
            "name": CORE_MODULE, "key_notion": None, "pattern": None,
            "documentation": "The general relations approved by the team. Specific properties of the other modules "
                             "are placed below them (rdfs:subPropertyOf) or were merged into them."})

def _labels_of(r, name) -> dict:
    """Die Labels des Vorschlags gelten nur, solange die Relation ihren Namen behaelt ("label_name"): nach einer
    Umbenennung in der Tabelle passen sie nicht mehr, dann entstehen sie beim Anlegen aus dem Namen."""
    labels = r.get("labels") if isinstance(r.get("labels"), dict) else {}
    labels = {str(k).strip().lower(): _plain(v, 80) for k, v in labels.items()
              if isinstance(v, str) and v.strip() and str(k).strip()}
    if not labels or r.get("label_name", name) != name:
        return {}
    return {"labels": labels, "label_name": name}

def relation_labels(r, langs) -> dict:
    """Labels einer Kernrelation (oder ihrer Inversen) fuer jede Label-Sprache, die das Vokabular nennt; die erste
    Sprache wenigstens aus dem Namen, klein wie die Labels der Module ("has part")."""
    labels = {l: v for l, v in (r.get("labels") or {}).items() if l in langs}
    return {langs[0]: humanize(r["name"]).lower(), **labels}

def clean_property_vocab(relations, onto, classes=None) -> list:
    """Prueft das (vorgeschlagene oder vom Team bearbeitete) Kernvokabular. Fehler -> HTTP 400 mit Grund.
    classes: die erlaubten Klassen fuer Domain und Range vor der Generierung (Basis "plan"); "covers" nennt dann
    Kompetenzfragen und Relationen der Literatur statt bestehender Properties."""
    if not isinstance(relations, list) or not relations:
        raise HTTPException(status_code=400, detail="The core vocabulary needs at least one relation")
    if len(relations) > CORE_RELATIONS_LIMIT:
        raise HTTPException(status_code=400, detail=f"At most {CORE_RELATIONS_LIMIT} core relations")
    planned = classes is not None
    if not planned:
        classes = {c.get("name") for c in onto.get("classes") or [] if isinstance(c, dict)}
    existing = {p.get("name") for p in onto.get("properties") or [] if isinstance(p, dict)}
    out, seen = [], set()
    def check_name(n, what):
        n = str(n or "").strip()
        if not IDENT.match(n):
            raise HTTPException(status_code=400, detail=f"Invalid {what} name {n!r}")
        if _norm(n) in seen:
            raise HTTPException(status_code=400, detail=f"The relation name {n} appears twice")
        if _norm(n) in {_norm(c) for c in classes}:
            raise HTTPException(status_code=400, detail=f"{n} is already the name of a class")
        seen.add(_norm(n))
        return n
    for r in relations:
        r = r if isinstance(r, dict) else {}
        name = check_name(r.get("name"), "relation")
        dom, rng = (str(r.get(k) or "").strip() for k in ("domain", "range"))
        for side, v in (("domain", dom), ("range", rng)):
            if v and v not in classes:
                raise HTTPException(status_code=400, detail=f"{name}: the {side} {v} is not a class of the ontology"
                                    if not planned else f"{name}: the {side} {v} is not a key notion or decided class")
        try:
            chars = Editor._characteristics("ObjectProperty", r.get("characteristics") or [])
        except EditError as ex:
            raise HTTPException(status_code=400, detail=f"{name}: {ex}")
        inv = r.get("inverse") if isinstance(r.get("inverse"), dict) and str(r["inverse"].get("name") or "").strip() else None
        if inv:
            if "symmetric" in chars:
                raise HTTPException(status_code=400, detail=f"{name}: a symmetric relation is its own inverse")
            iname = check_name(inv["name"], "inverse")
            inv = {"name": iname, "description": str(inv.get("description") or "").strip(),
                   **_labels_of(inv, iname)}
        covers = r.get("covers") or []
        covers = ([_plain(c, 120) for c in covers if isinstance(c, str) and c.strip()] if planned
                  else [c for c in covers if c in existing])
        out.append({"name": name, "description": str(r.get("description") or "").strip()[:500], "domain": dom,
                    "range": rng, "inverse": inv, "characteristics": chars, "covers": covers[:30],
                    **_labels_of(r, name)})
    issues = property_issues([{"name": r["name"], "type": "ObjectProperty", "characteristics": r["characteristics"],
                               "inverse_of": (r["inverse"] or {}).get("name")} for r in out] +
                             [{"name": r["inverse"]["name"], "type": "ObjectProperty", "inverse_of": r["name"],
                               "characteristics": [c for c in r["characteristics"] if c in ("transitive", "symmetric")]}
                              for r in out if r["inverse"]])
    if issues:
        raise HTTPException(status_code=400, detail=issues[0])
    return out

def _vocab_lines(vocab) -> str:
    return "\n".join(
        f"- {r['name']}: {r['domain'] or '(any)'} -> {r['range'] or '(any)'}" +
        (f", inverse {r['inverse']['name']}" if r.get("inverse") else "") +
        (f" [{', '.join(r['characteristics'])}]" if r.get("characteristics") else "") +
        (f": {_clip(r['description'], 140)}" if r.get("description") else "") for r in vocab)

# ── Vor der Generierung (Phase 3a) ─────────────────────────────────────────────
# Das Vokabular entsteht aus dem, was die Ontologie leisten soll (Fragen, Key Notions, Relationen der Literatur),
# nicht aus fertigen engen Properties. Domain und Range duerfen nur Klassen sein, die es nach der Planung sicher gibt:
# die Key Notions (jede wird eine Klasse ihres Moduls), die entschiedenen Klassen aus Schritt 4 und - wenn die
# Generierung sie verwendet - die Klassen der oberen Schicht (DECISIONS 97; vorher blieb dafuer nur "beliebig").
def relation_classes(session) -> list:
    momo = session.get("momo") or {}
    names = [_class_name(n["name"]) for n in named_notions(momo.get("key_notions"))] + list(decided_classes(session))
    if use_upper_layer(session):
        names += [x["name"] for x in upper_layer_of(session)]
    return list(dict.fromkeys(n for n in names if n))

PLAN_RELATIONS_SYS = (
    MOMO_METHOD + "\nYou design the CORE RELATION VOCABULARY of a modular ontology BEFORE it is generated: a small set "
    "of general relations that every module uses, instead of each module inventing one narrow property per pair of "
    "classes (which makes an ontology hard to query and reuse). Propose {size}.\n"
    "Rules:\n"
    "1. Derive the relations from what the competency questions ask for and from how the key notions are related"
    "{literature}. Name a relation by its general meaning (lowerCamelCase verb phrase), never by the classes it "
    "connects. Typical general relations are part-whole, temporal order, participation, input and output, use, "
    "creation, description or representation, location, causation, membership - include only those this ontology "
    "needs, and add domain-specific ones where the questions share a meaning none of these captures.\n"
    "2. Each relation names ONE kind of connection that a query can rely on. Never propose a catch-all such as "
    "hasDescription, hasProperty, hasAttribute, hasDetail, hasFeature or isRelatedTo: what it would collect (a "
    "colour, an origin, a variety, a date) are different connections - propose them separately, or leave them to the "
    "modules.\n"
    "3. Domain and range: one of the classes listed under 'Classes for domain and range', or empty when the relation "
    "really connects many kinds of things (as part-whole or temporal order do). Modules use a core relation between "
    "any classes within its domain and range.\n"
    "4. Give an inverse only when both directions are needed, with its own name and description.\n"
    "5. Characteristics: transitive only if A r B and B r C always imply A r C (part-whole, temporal order); "
    "functional only if a subject can never have two different values; symmetric only if A r B always implies B r A; "
    "asymmetric if A r B excludes B r A. Never combine transitive with functional or asymmetric.\n"
    "6. Under \"covers\" list what the relation serves: competency questions as \"CQ<number>\"{covers}.\n"
    "7. Give each relation and inverse \"labels\" in every language listed under \"Label languages\" in the project "
    "conventions (lowercase verb phrases, e.g. \"has part\"); English only if none are listed.\n"
    "8. A core relation is general enough that relations of several modules can go below it. A relation between two "
    "specific classes that only one module uses belongs to that module, not here.{upper}\n"
    "Attributes with literal values (names, numbers, dates) are not relations: leave them to the modules.\n"
    'Answer ONLY as JSON: {{"summary":"how the vocabulary is organized","relations":[{{"name":"...",'
    '"labels":{{"<language code>":"label"}},"description":"...","domain":"Class or empty","range":"Class or empty",'
    '"inverse":{{"name":"...","labels":{{"<language code>":"label"}},"description":"..."}} or null,'
    '"characteristics":[],"covers":["CQ1", "..."]}}]}}')

def _upper_rule(session) -> str:
    """Regel 9 des Vorschlags, wenn die obere Schicht verwendet wird (DECISIONS 119): VA 4a-4c - 25 Relationen ohne
    Kernrelation zeigten auf Qualitaeten (Umfang, Klarheit, Granularitaet), keine Kernrelation hatte diesen Bereich."""
    if not use_upper_layer(session):
        return ""
    names = [x["name"] for x in upper_layer_of(session) if x.get("name")]
    quality = ("In particular, propose \"has quality\" with range Quality, for the characteristics, levels, degrees "
               "and scopes of things. " if "Quality" in names else "")
    return ("\n9. The upper layer (" + ", ".join(names) + ") groups all classes. Where relations of several modules "
            "will point to instances of one upper class, propose one general relation with that class as range. " +
            quality + "Such a relation is not a catch-all (rule 2): its range says what it collects, and the module "
            "relations below it keep their specific meaning.")

def build_core_vocab_prompt(session) -> list:
    momo = session.get("momo") or {}
    inv, _, _ = _inventory_parts(session)
    lit = (inv or {}).get("relations") or []
    cqs = [_cq_text(c) for c in momo.get("competency_questions") or [] if _cq_text(c)]
    notions = named_notions(momo.get("key_notions"))
    classes = relation_classes(session)
    # nach der Zahl der Key Notions, nicht fest (DECISIONS 138): "20 bis 50" mit Literatur gab dem Wein-Durchlauf
    # (5 Key Notions, 68 Klassen) 21 Kernrelationen und 0.5 Relationen oben je Klasse; VA (10) bleibt bei 20-40
    n = len(notions)
    if n:
        lo, hi = max(3, 2 * n), max(5, 4 * n)
        size = (f"about {lo} to {hi} relations (two to four per key notion), fewer if the questions" +
                (" and the literature" if lit else "") + " need fewer")
    else:
        size = ("about 20 to 50 relations, fewer if the questions and the literature need fewer" if lit else
                "about 5 to 15 relations, fewer if the domain is small")
    system = PLAN_RELATIONS_SYS.format(
        size=size, literature=", and from the relations the literature states between concepts" if lit else "",
        covers=" and relations of the literature as \"subject - relation - object\"" if lit else "",
        upper=_upper_rule(session))
    lines = ["**Use case:**\n" + (momo.get("use_case") or "(none)"),
             "**Competency questions:**\n" + ("\n".join(f"CQ{i}. {q}" for i, q in enumerate(cqs, 1)) or "(none)"),
             "**Key notions (each becomes a module):**\n" + ("\n".join(
                 f"- {n['name']}" + (f": {_clip(n.get('description'), 160)}" if n.get("description") else "")
                 for n in notions) or "(none yet - the plan will propose the modules)"),
             "**Classes for domain and range:** " + (", ".join(classes) or "(none - leave domain and range empty)")]
    if lit:
        shown = lit[:PLAN_LITERATURE_RELATIONS]
        lines.append(f"**Relations stated in the literature** ({len(shown)} of {len(lit)}, most sources first; "
                     "subject - relation - object (sources)):\n" +
                     "\n".join(f"- {r['subject']} - {r['relation']} - {r['object']} ({len(r.get('docs') or [])})"
                               for r in shown))
    return [{"role": "system", "content": system},
            {"role": "user", "content": context_block(session) + "\n\n" + "\n\n".join(lines)}]

def approved_vocab(session) -> list:
    """Das freigegebene Vokabular, das die Generierung verwendet - leer, wenn keins freigegeben oder abgeschaltet."""
    v = session.get("property_vocab") or {}
    return v.get("relations") or [] if v.get("status") in ("approved", "applied") else []

# ── In der Generierung ─────────────────────────────────────────────────────────
# Wein-Lauf 3: "nur wo eine Frage es braucht" schob Farbe, Rebsorte und Herkunft in eine Sammelrelation - eine eigene
# Property fuer eine eigene Art von Verbindung ist erwuenscht, nur keine, die bloss Domain und Range einengt.
CORE_RULES = ("Use a core relation directly where exactly its meaning is meant and the classes lie within its domain "
              "and range - do not create a property that only restricts a core relation to particular classes. "
              "Create a module-specific object property where the module needs a connection of its own kind - to a "
              "different kind of thing (such as a value set, a kind or variety, a place or a time) or a distinction "
              "a competency question needs. Set its \"sub_property_of\" to a core relation only if it shares that "
              "relation's meaning (a more specific way of the same connection), with domain and range within that "
              "relation's; otherwise leave \"sub_property_of\" empty. Never define a core relation or its inverse "
              "yourself. Attributes (datatype properties) are not affected.")

def core_relation_block(vocab) -> str:
    if not vocab:
        return ""
    return ("\n\n**Core relations** (approved by the team for the whole ontology; they exist already):\n" +
            _vocab_lines(vocab) + "\n" + CORE_RULES)

def core_names(vocab) -> set:
    return {r["name"] for r in vocab} | {r["inverse"]["name"] for r in vocab if r.get("inverse")}

def core_properties(vocab, class_names, langs=("en",), module=CORE_MODULE) -> tuple:
    """Die Kernrelationen als Properties der Ontologie. Eine Domain oder Range, die die Planung nicht als Klasse
    angelegt hat, wird zu "beliebig" statt zu einer Platzhalterklasse - die Liste davon geht in den Bericht."""
    langs = list(langs) or ["en"]
    props, widened = [], []
    def side(r, k):
        v = r.get(k) or None
        if v and v not in class_names:
            widened.append(f"{r['name']} {k} {v}")
            return None
        return v
    for r in vocab:
        dom, rng = side(r, "domain"), side(r, "range")
        props.append({"name": r["name"], "type": "ObjectProperty", "description": r.get("description") or "",
                      "labels": relation_labels(r, langs),
                      "domain": dom, "range": rng, "characteristics": list(r.get("characteristics") or []),
                      "inverse_of": (r.get("inverse") or {}).get("name"), "module": module})
        if r.get("inverse"):
            props.append({"name": r["inverse"]["name"], "type": "ObjectProperty",
                          "labels": relation_labels(r["inverse"], langs),
                          "description": r["inverse"].get("description") or "", "domain": rng, "range": dom,
                          "inverse_of": r["name"], "module": module,
                          "characteristics": [c for c in r.get("characteristics") or [] if c in ("transitive", "symmetric")]})
    return props, widened

def _within(cls, outer, parents) -> bool:
    """cls liegt in outer: outer ist leer (beliebig), gleich cls oder eine Oberklasse von cls."""
    if not outer:
        return True
    seen = set()
    while cls and cls not in seen:
        if cls == outer:
            return True
        seen.add(cls)
        cls = parents.get(cls)
    return False

def check_core_relations(onto, vocab) -> dict:
    """Nach dem Zusammenfuehren: welche Relationen haengen unter keiner Kernrelation, und welche Unterproperty
    verletzt Domain oder Range ihrer Kernrelation (die Regeln aus DECISIONS 70, hier nur berichtet)."""
    core = core_names(vocab)
    props = {p["name"]: p for p in onto.get("properties") or [] if isinstance(p, dict) and p.get("name")}
    parents = {c["name"]: c.get("parent") for c in onto.get("classes") or [] if isinstance(c, dict) and c.get("name")}
    def core_above(p):
        seen = set()
        while p and p["name"] not in seen:
            seen.add(p["name"])
            if p["name"] in core:
                return p
            p = props.get(p.get("sub_property_of") or "")
        return None
    below, without, violations = [], [], []
    for p in relation_pairs(list(props.values())):
        if p["name"] in core or p.get("inverse_of") in core:
            continue
        c = core_above(p)
        if not c:
            without.append(p["name"])
            continue
        below.append(p["name"])
        for k in ("domain", "range"):
            if p.get(k) and not _within(p[k], c.get(k), parents):
                violations.append(f"{p['name']}: {k} {p[k]} is not within {c['name']}'s {k} {c.get(k)}")
    return {"relations": len(vocab), "below_core": below, "without_core": without, "violations": violations}


# ── Rueckmeldung zum Kernvokabular nach einer Generierung (DECISIONS 119) ──────
# VA 4a-4c: 20 der 41 Kernrelationen standen in keinem Lauf ueber einer Relation eines Moduls, und die Relationen
# ohne Kernrelation zeigten gehaeuft auf dieselbe Klasse der oberen Schicht. Beides sieht das Team in Schritt 7.
def core_usage(onto, vocab) -> dict:
    """Welche Kernrelationen keine Relation eines Moduls unter sich haben, und welche Relationen ohne Kernrelation
    gemeinsam auf eine Klasse der oberen Schicht zeigen (die naechstliegende, ab drei Relationen)."""
    from ontology_evaluation import _ancestors
    props = {p["name"]: p for p in onto.get("properties") or [] if isinstance(p, dict) and p.get("name")}
    core = core_names(vocab)
    main = {r["inverse"]["name"]: r["name"] for r in vocab if r.get("inverse")}
    below = {}
    for p in props.values():
        cur, seen = p.get("sub_property_of"), set()
        while p["name"] not in core and cur and cur not in seen:
            seen.add(cur)
            if cur in core:
                below[main.get(cur, cur)] = below.get(main.get(cur, cur), 0) + 1
                break
            cur = (props.get(cur) or {}).get("sub_property_of")
    upper = {c["name"] for c in onto.get("classes") or [] if isinstance(c, dict) and c.get("layer") == "upper"}
    anc = _ancestors(onto)
    without = check_core_relations(onto, vocab)["without_core"]
    groups = {}
    for n in without:
        rng = props[n].get("range")
        tops = (anc.get(rng, set()) | {rng}) & upper if rng else set()
        if tops:   # die tiefste: Specification vor InformationObject
            groups.setdefault(max(tops, key=lambda u: len(anc.get(u, ()))), []).append(n)
    return {"unused": [r["name"] for r in vocab if r["name"] not in below], "below": below,
            "without_core": len(without),
            "groups": [{"upper": u, "relations": sorted(ns)} for u, ns in sorted(groups.items(), key=lambda g: -len(g[1]))
                       if len(ns) >= 3]}

