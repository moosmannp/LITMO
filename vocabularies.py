"""Standards und Vokabulare: Vorschlag, Laden, Wiederverwendung in der Generierung, Ausrichtung."""

import json, re, requests, threading
from ontology_edits import EditError, Editor
from store import SESSION_DIR

from project import _context, _ctx, label_languages, session_prefixes
from ontology_io import _BUILTIN_PREFIXES, KNOWN_PREFIXES, _looks_like_namespace, standards_to_prefixes
from corpus import concept_key

# Schritt 7 (DECISIONS 74): Standards mit Namespace, Praefix und einer Entscheidung, wie sie genutzt werden. Die
# Vokabulare selbst werden geladen (vom Namespace oder hochgeladen), damit spaetere Schritte echte Terme kennen.
STANDARD_DECISIONS = ("align", "use_terms", "reference")
STANDARDS_SYS = (
    "You are an ontology engineer. Suggest existing ontologies, vocabularies and standards that the project's "
    "ontology should reuse or align with. For each give:\n"
    "- name; kind: ontology | vocabulary | standard\n"
    "- namespace: the IRI its terms live in, ending in # or / (e.g. http://www.w3.org/ns/prov#) - NOT a specification, "
    "documentation or repository page; empty if it has no RDF vocabulary\n"
    "- prefix: its conventional prefix (e.g. prov)\n"
    "- documentation_url: where people can read about it\n"
    "- download_url: a direct link to an RDF file (Turtle, RDF/XML) if you know one for certain, else empty\n"
    "- decision: align (keep the project's own classes and link them to this vocabulary - the default), use_terms "
    "(use its terms directly - suits generic things such as agents, concepts, datasets, time), or reference (no RDF "
    "vocabulary, or only for orientation)\n"
    "- relevance: why it fits; reuse_hint: which of its parts or terms fit which part of the project\n"
    "Follow the reuse decisions in the project context. Write in English.\n"
    'Answer ONLY as JSON: {"standards":[{"name":"...","kind":"...","namespace":"...","prefix":"...",'
    '"documentation_url":"...","download_url":"...","decision":"align","relevance":"...","reuse_hint":"..."}]}')

def build_standards_prompt(domain, context=""):
    return [
        {"role": "system", "content": STANDARDS_SYS},
        {"role": "user", "content": "Domain and use case:\n" + domain + _ctx(context) +
         "\n\nSuggest 3-7 fitting ontologies or standards, most relevant first - general vocabularies (such as PROV-O, "
         "SKOS, Dublin Core, schema.org, FOAF, OWL-Time) as well as established ontologies of this domain."}
    ]

def clean_standard(s) -> dict:
    """Vereinheitlicht einen Standard (auch aeltere mit nur 'url'): Namespace nur, wenn er wie einer aussieht; sonst
    aus der Tabelle bekannter Vokabulare; Praefix als Bezeichner; Entscheidung aus der festen Liste."""
    s = dict(s) if isinstance(s, dict) else {}
    out = {"name": str(s.get("name") or "").strip()[:120] or "Unnamed",
           "kind": str(s.get("kind") or s.get("type") or "").strip()[:30],
           "relevance": str(s.get("relevance") or "").strip()[:600],
           "reuse_hint": str(s.get("reuse_hint") or "").strip()[:600]}
    ns = str(s.get("namespace") or "").strip()
    doc = str(s.get("documentation_url") or s.get("url") or "").strip()
    if not _looks_like_namespace(ns):
        ns = ""
    pfx = str(s.get("prefix") or "").strip().lower()
    known = standards_to_prefixes([{"name": out["name"], "url": doc}])
    if not ns and known:
        pfx, ns = next(iter(known.items()))
    elif ns and not re.match(r"^[a-z][\w-]*$", pfx or ""):
        pfx = next((p for p, n in KNOWN_PREFIXES.values() if n == ns), "") or _derived_prefix(ns)
    out.update(namespace=ns, prefix=pfx if ns else "", documentation_url=doc,
               download_url=str(s.get("download_url") or "").strip(),
               decision=s.get("decision") if s.get("decision") in STANDARD_DECISIONS else ("align" if ns else "reference"))
    out["url"] = doc                     # aeltere Teile der Oberflaeche zeigen 'url'
    for k in ("vocabulary", "load_error"):   # Ladezustand bleibt erhalten
        if s.get(k):
            out[k] = s[k]
    return out

# Bekannte Quellen fuer Vokabulare, deren Namespace keine RDF-Datei ausliefert (Stand Oktober 2026 geprueft)
VOCAB_SOURCES = {
    "https://schema.org/": "https://schema.org/version/latest/schemaorg-current-https.ttl",
    "http://purl.org/linked-data/cube#": "https://raw.githubusercontent.com/UKGovLD/publishing-statistical-data/"
                                         "master/specs/src/main/vocab/cube.ttl",
}
# Grosse Vokabulare (DECISIONS 100): FoodOn hat rund 40 MB. Die Termlisten liegen deshalb in einer Datei je
# Vokabular neben der Projektdatei (die nach jeder Aenderung neu geschrieben wird), und die Suche nach passenden
# Termen laeuft ueber einen Wortindex statt ueber alle Terme.
VOCAB_MAX_BYTES = 300_000_000
VOCAB_MAX_TERMS = 500_000
RDF_TYPES = {"text/turtle": "turtle", "application/x-turtle": "turtle", "application/rdf+xml": "xml",
             "application/ld+json": "json-ld", "application/n-triples": "nt", "application/owl+xml": None}

def _parse_rdf(text, content_type="", url=""):
    """Versucht das passende Format: nach Content-Type, Dateiendung, sonst der Reihe nach."""
    from rdflib import Graph
    fmt = RDF_TYPES.get((content_type or "").split(";")[0].strip().lower())
    ext = {".ttl": "turtle", ".rdf": "xml", ".owl": "xml", ".xml": "xml", ".jsonld": "json-ld", ".nt": "nt"}
    guesses = [fmt] if fmt else []
    guesses += [v for k, v in ext.items() if url.lower().split("?")[0].endswith(k)] + ["turtle", "xml", "json-ld"]
    import logging
    logging.getLogger("rdflib.term").setLevel(logging.ERROR)   # FoodOn: einzelne fehlerhafte Datumswerte, harmlos
    last = None
    for f in dict.fromkeys(g for g in guesses if g):
        try:
            g = Graph()
            g.parse(data=text, format=f)
            if len(g):
                g.declared_prefixes = _text_prefixes(text)
                return g
        except Exception as ex:
            last = ex
    raise ValueError(f"not readable as RDF ({type(last).__name__ if last else 'empty'})")

def fetch_vocabulary(standard):
    """Laedt das Vokabular eines Standards: Download-URL, bekannte Quelle, dann der Namespace per Content
    Negotiation. Gibt (Graph, Quelle) zurueck oder wirft ValueError mit allen Fehlversuchen."""
    ns = standard.get("namespace") or ""
    candidates = [standard.get("download_url"), VOCAB_SOURCES.get(ns), ns.rstrip("#") if ns else None]
    headers = {"Accept": "text/turtle, application/rdf+xml;q=0.9, application/ld+json;q=0.5, */*;q=0.1"}
    errors = []
    for url in dict.fromkeys(u for u in candidates if u):
        try:
            r = requests.get(url, headers=headers, timeout=120, allow_redirects=True, stream=True)
            body = r.raw.read(VOCAB_MAX_BYTES + 1, decode_content=True)
            if r.status_code != 200:
                raise ValueError(f"HTTP {r.status_code}")
            if len(body) > VOCAB_MAX_BYTES:
                raise ValueError(f"larger than {VOCAB_MAX_BYTES // 1_000_000} MB")
            ctype = r.headers.get("content-type", "")
            if ctype.startswith("text/html"):
                raise ValueError("returns a web page, not RDF")
            return _parse_rdf(body.decode("utf-8", errors="replace"), ctype, r.url), r.url
        except Exception as ex:
            errors.append(f"{url}: {getattr(ex, 'args', [ex])[0] if isinstance(ex, ValueError) else type(ex).__name__}")
    raise ValueError("; ".join(errors) or "no URL to load from - give a download URL or upload the file")

def vocabulary_terms(g, namespace, prefix) -> dict:
    """Klassen und Properties des Vokabulars (nur im eigenen Namespace) mit Label, Definition, Oberbegriff,
    Domain und Range - die Termliste, gegen die spaetere Schritte pruefen und die sie dem Modell zeigen."""
    from rdflib import URIRef, Literal
    from rdflib.namespace import RDF, RDFS, OWL, SKOS
    def lit(node, preds):
        vals = [o for p in preds for o in g.objects(node, p) if isinstance(o, Literal) and str(o).strip()]
        en = [v for v in vals if (v.language or "").lower().startswith("en")] or [v for v in vals if not v.language] or vals
        return re.sub(r"\s+", " ", str(en[0])).strip() if en else ""
    def local(u):
        return str(u)[len(namespace):] if str(u).startswith(namespace) else None
    def ref(u):
        if not isinstance(u, URIRef):
            return ""
        return f"{prefix}:{local(u)}" if local(u) else str(u)
    kinds = {OWL.Class: "class", RDFS.Class: "class", OWL.ObjectProperty: "object", OWL.DatatypeProperty: "datatype",
             RDF.Property: "property", OWL.AnnotationProperty: "annotation"}
    terms = {}
    for t, kind in kinds.items():
        for s in g.subjects(RDF.type, t):
            name = isinstance(s, URIRef) and local(s)
            if not name or not re.match(r"^[A-Za-z_][\w.-]*$", name):
                continue
            prev = terms.get(name)
            if prev and prev["kind"] != "property":   # spezifischere Art behalten (ObjectProperty statt rdf:Property)
                continue
            terms[name] = {"name": name, "kind": kind, "label": lit(s, [SKOS.prefLabel, RDFS.label]),
                           "disjoint": [ref(o) for o in g.objects(s, OWL.disjointWith) if isinstance(o, URIRef)][:8]
                           if kind == "class" else [],
                           "definition": lit(s, [SKOS.definition, RDFS.comment, URIRef("http://purl.org/dc/terms/description")])[:300],
                           "parents": [ref(o) for o in g.objects(s, RDFS.subClassOf if kind == "class" else RDFS.subPropertyOf)
                                       if isinstance(o, URIRef)][:4]}
            if kind != "class":
                terms[name]["domain"] = ref(g.value(s, RDFS.domain))
                terms[name]["range"] = ref(g.value(s, RDFS.range))
    items = sorted(terms.values(), key=lambda t: (t["kind"] != "class", t["name"]))[:VOCAB_MAX_TERMS]
    return {"classes": [t for t in items if t["kind"] == "class"], "properties": [t for t in items if t["kind"] != "class"],
            "truncated": len(terms) > VOCAB_MAX_TERMS}

# Prefixe (DECISIONS 99): ein Vokabular behaelt seinen eigenen Prefix - den, den seine Datei fuer ihren Namespace
# erklaert (vin fuer das W3C-Wein-Vokabular), sonst den bekannten. Kollidiert er mit dem Prefix des Projekts, wechselt
# das Projekt seinen; zwei Vokabulare mit demselben Prefix fuer verschiedene Namespaces gehen nicht.
PREFIX_RE = re.compile(r"^[a-z][\w-]*$")

def _text_prefixes(text) -> dict:
    """Namespace -> Prefix, wie die Datei sie erklaert. rdflib behaelt je Namespace nur einen Prefix: bindet eine
    RDF/XML-Datei ihn als Default (xmlns=) und als xmlns:vin=, geht vin verloren (W3C-Wein-Vokabular)."""
    out = {}
    patterns = (r'xmlns:([A-Za-z][\w.-]*)\s*=\s*["\']([^"\']+)["\']',              # RDF/XML
                r'(?:@prefix|PREFIX)\s+([A-Za-z][\w.-]*)\s*:\s*<([^>]+)>',             # Turtle, SPARQL-Stil
                r'"([A-Za-z][\w.-]*)"\s*:\s*"([^"]+[#/])"')                            # JSON-LD @context
    for pat in patterns:
        for pfx, ns in re.findall(pat, text or ""):
            out.setdefault(ns, pfx)
    return out

def declared_prefix(g, ns) -> str:
    """Der Prefix, den die Datei selbst fuer den Namespace erklaert."""
    for pfx, uri in g.namespaces():
        if str(uri) == ns and pfx and PREFIX_RE.match(str(pfx)):
            return str(pfx)
    pfx = (getattr(g, "declared_prefixes", None) or {}).get(ns, "")
    return pfx if PREFIX_RE.match(pfx) else ""

RESERVED_PREFIXES = {"owl": "http://www.w3.org/2002/07/owl#", "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
                     "rdfs": "http://www.w3.org/2000/01/rdf-schema#", "xsd": "http://www.w3.org/2001/XMLSchema#",
                     "sh": "http://www.w3.org/ns/shacl#", "opla": "http://ontologydesignpatterns.org/opla#"}

def _derived_prefix(ns) -> str:
    """Prefix aus dem Namespace: das letzte Pfadstueck, das mit einem Buchstaben beginnt (".../onto/1.0/" -> onto).
    Ein Prefix darf nicht mit einer Ziffer beginnen; gibt es kein solches Stueck, kommt ein v davor."""
    parts = [re.sub(r"[^a-z0-9]", "", p) for p in re.split(r"[/#:]", re.sub(r"^[a-z]+://", "", ns.lower()))]
    word = next((p for p in reversed(parts) if p[:1].isalpha()), "")
    if not word:
        word = next(("v" + p for p in reversed(parts) if p), "")
    return word[:12]

def prefix_owner(session, pfx, ns, exclude=None) -> str:
    """Name des Vokabulars oder eigenen Prefixes, das pfx schon fuer einen anderen Namespace verwendet."""
    if RESERVED_PREFIXES.get(pfx, ns) != ns:     # owl, rdf ... schreibt der Export selbst
        return f"the built-in namespace {RESERVED_PREFIXES[pfx]}"
    for s in session.get("suggested_standards") or []:
        if isinstance(s, dict) and s is not exclude and s.get("prefix") == pfx and s.get("namespace") and s["namespace"] != ns:
            return s.get("name") or pfx
    for p, voc in (session.get("vocabularies") or {}).items():
        if p == pfx and voc.get("namespace") and voc["namespace"] != ns and (exclude or {}).get("prefix") != p:
            return voc.get("name") or pfx
    if (session.get("custom_prefixes") or {}).get(pfx, ns) != ns:
        return f"the additional prefix {pfx}"
    return ""

def make_room_for_prefix(session, pfx) -> dict:
    """Nutzt das Projekt selbst den Prefix eines Vokabulars, bekommt das Projekt einen neuen: <prefix>-onto."""
    conv = _context(session)["conventions"]
    if (conv.get("prefix") or "").strip().lower() != pfx:
        return {}
    taken = {s.get("prefix") for s in session.get("suggested_standards") or [] if isinstance(s, dict)}
    taken |= set(session.get("vocabularies") or {}) | set(session.get("custom_prefixes") or {})
    new, i = f"{pfx}-onto", 2
    while new in taken:
        new, i = f"{pfx}-onto{i}", i + 1
    conv["prefix"] = new
    return {"old": pfx, "new": new}

def store_vocabulary(session, standard, g, source, session_id=None) -> dict:
    ns = standard.get("namespace") or ""
    if not ns:   # aus der Datei: der Namespace mit den meisten deklarierten Termen
        from rdflib.namespace import RDF, OWL, RDFS
        counts = {}
        for t in (OWL.Class, RDFS.Class, OWL.ObjectProperty, OWL.DatatypeProperty, RDF.Property):
            for s in g.subjects(RDF.type, t):
                base = re.match(r"^(.*[#/])[^#/]+$", str(s))
                if base:
                    counts[base.group(1)] = counts.get(base.group(1), 0) + 1
        ns = max(counts, key=counts.get) if counts else ""
        standard["namespace"] = ns
    if ns and not standard.get("prefix"):
        standard["prefix"] = declared_prefix(g, ns) or next((p for p, n in KNOWN_PREFIXES.values() if n == ns), "") or \
            _derived_prefix(ns) or "ext"
    owner = prefix_owner(session, standard["prefix"], ns, exclude=standard)
    if owner:
        raise ValueError(f"its prefix {standard['prefix']} is already used by {owner} for another namespace - "
                         "remove one of the two")
    terms = vocabulary_terms(g, ns, standard["prefix"])
    if not terms["classes"] and not terms["properties"]:
        raise ValueError(f"the file declares no classes or properties in the namespace {ns or '(unknown)'}")
    entry = {"name": standard["name"], "namespace": ns, "source": source,
             "counts": {"classes": len(terms["classes"]), "properties": len(terms["properties"])}}
    if session_id:      # in eine eigene Datei, nicht in die Projektdatei
        entry["terms_file"] = save_vocab_terms(session_id, standard["prefix"], terms)
    else:
        entry.update(terms)
    session.setdefault("vocabularies", {})[standard["prefix"]] = entry
    standard["vocabulary"] = {"classes": len(terms["classes"]), "properties": len(terms["properties"]),
                              "source": source, "truncated": terms["truncated"]}
    standard.pop("load_error", None)
    standard["prefix_change"] = make_room_for_prefix(session, standard["prefix"])
    return standard

def save_vocab_terms(session_id, prefix, terms) -> str:
    """Schreibt die Termliste eines Vokabulars neben die Projektdatei; der Pfad relativ zum Projektordner."""
    rel = f"{session_id}/vocabularies/{re.sub(r'[^A-Za-z0-9_-]', '_', prefix)}.json"
    path = SESSION_DIR / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"classes": terms["classes"], "properties": terms["properties"],
                               "truncated": terms.get("truncated", False)}, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return rel

_VOCAB_CACHE, _VOCAB_LOCK = {}, threading.Lock()

def _vocab_data(voc) -> dict:
    """Termlisten, Namensverzeichnis und Wortindex eines geladenen Vokabulars - aus der Datei (zwischengespeichert,
    solange sie sich nicht aendert) oder, bei aelteren Projekten, aus dem Eintrag selbst."""
    if not voc.get("terms_file"):
        key = ("inline", id(voc), len(voc.get("classes") or []), len(voc.get("properties") or []))
        load = lambda: {"classes": voc.get("classes") or [], "properties": voc.get("properties") or []}
    else:
        path = SESSION_DIR / voc["terms_file"]
        try:
            key = (str(path), path.stat().st_mtime)
        except OSError:
            return _index({"classes": [], "properties": []})
        load = lambda: json.loads(path.read_text(encoding="utf-8"))
    with _VOCAB_LOCK:
        hit = _VOCAB_CACHE.get(key[:2] if key[0] == "inline" else key[0])
        if hit and hit[0] == key:
            return hit[1]
    data = _index(load())
    with _VOCAB_LOCK:
        _VOCAB_CACHE[key[:2] if key[0] == "inline" else key[0]] = (key, data)
    return data

def _index(terms) -> dict:
    """Wortindex fuer die Suche passender Terme: nur Terme, die ein Wort mit dem Gesuchten teilen, kommen in Frage."""
    by_token, by_key = {"class": {}, "property": {}}, {"class": {}, "property": {}}
    entries = {"class": [], "property": []}
    for t in terms["classes"] + terms["properties"]:
        kind = "class" if t["kind"] == "class" else "property"
        if t.get("kind") == "annotation":
            continue
        toks = _term_tokens(t["name"], t.get("label")) if kind == "class" else _term_tokens(t["name"])
        i = len(entries[kind])
        entries[kind].append((t, toks))
        for tok in toks:
            by_token[kind].setdefault(tok, []).append(i)
        for k in {concept_key(t["name"]), concept_key(t.get("label"))} - {""}:
            by_key[kind].setdefault(k, []).append(i)
    return {"classes": terms["classes"], "properties": terms["properties"],
            "by_name": {t["name"]: t for t in terms["classes"] + terms["properties"]},
            "entries": entries, "by_token": by_token, "by_key": by_key}

def vocab_terms(voc) -> dict:
    """Klassen und Properties eines geladenen Vokabulars (aus Datei oder Eintrag)."""
    d = _vocab_data(voc)
    return {"classes": d["classes"], "properties": d["properties"]}

def vocab_candidates(voc, kind, toks, keys) -> list:
    """Indizes der Terme einer Art, die ein Wort oder einen Begriffsschluessel mit dem Gesuchten teilen."""
    d = _vocab_data(voc)
    found = set()
    for tok in toks:
        found.update(d["by_token"][kind].get(tok, ()))
    for k in keys:
        found.update(d["by_key"][kind].get(k, ()))
    return [d["entries"][kind][i] for i in sorted(found)]

def session_vocab(session) -> dict:
    """Termlisten der geladenen Vokabulare fuer die Pruefung: prefix -> {Name: Term}."""
    return {pfx: _vocab_data(voc)["by_name"] for pfx, voc in (session.get("vocabularies") or {}).items()}

# Teil B (DECISIONS 77): Terme der geladenen Vokabulare schon bei der Generierung anbieten
REUSE_TERMS_LIMIT = 25        # je Modul bzw. im Einzelaufruf 40

def relevant_vocab_terms(session, texts, limit=REUSE_TERMS_LIMIT) -> list:
    """Terme der geladenen Vokabulare, die zu den Begriffen passen, die gerade modelliert werden (gleicher Name oder
    Label, Kopfwort, Wortueberschneidung - wie bei 'Align'; ein laengerer Text muss alle Woerter des Terms
    enthalten). Nur Treffer: ein ganzes kleines Vokabular in jedes Modul zu geben, war Rauschen. Jeder Treffer mit
    der Entscheidung des Teams."""
    vocabs = session.get("vocabularies") or {}
    if not vocabs:
        return []
    decision = {s.get("prefix"): s.get("decision") for s in session.get("suggested_standards") or [] if isinstance(s, dict)}
    own = []
    for t in texts:
        t = str(t or "").strip()
        if t:
            words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", t).split()
            own.append((_term_tokens(t), _term_tokens(words[-1]) if words else set(), concept_key(t)))
    best = {}
    for pfx, voc in vocabs.items():
        if decision.get(pfx) == "reference":
            continue
        # nur Terme, die ein Wort oder einen Begriffsschluessel teilen - sonst kann keine Regel unten greifen
        cands = {}
        for kind in ("class", "property"):
            for toks, _, key in own:
                for t, ttoks in vocab_candidates(voc, kind, toks, [key] if key else []):
                    cands[t["name"]] = (t, ttoks)
        for t, ttoks in cands.values():
            ref = f"{pfx}:{t['name']}"
            score = 0.0
            for toks, head, key in own:
                if not toks or not ttoks:
                    continue
                if key and key in (concept_key(t["name"]), concept_key(t.get("label"))):
                    score = max(score, 3.0)
                elif t["kind"] == "class" and len(ttoks) == 1 and ttoks == head:
                    score = max(score, 2.0)
                elif len(toks) > 4 and ttoks <= toks:
                    score = max(score, 1.5)       # a longer text (use case, question) mentions all words of the term
                else:
                    j = len(toks & ttoks) / len(toks | ttoks)
                    if j >= 0.5:
                        score = max(score, 1.0 + j)
            if score > 0:
                best[ref] = (score, ref, t, decision.get(pfx) or "align")
    ranked = sorted(best.values(), key=lambda x: (-x[0], x[1]))[:limit]
    return [{"ref": r, "kind": t["kind"], "label": t.get("label") or "", "definition": t.get("definition") or "",
             "parents": t.get("parents") or [], "domain": t.get("domain") or "", "range": t.get("range") or "",
             "decision": d} for _, r, t, d in ranked]

def reuse_block(terms) -> str:
    """Prompt-Abschnitt mit den angebotenen Termen und den Regeln, wie sie zu verwenden sind."""
    if not terms:
        return ""
    lines = [f"- {t['ref']} ({t['kind']}, team decision: {t['decision']})" + (f' "{t["label"]}"' if t["label"] else "") +
             (f", below {', '.join(t['parents'][:2])}" if t["parents"] else "") +
             (f", {t['domain'] or '(any)'} -> {t['range'] or '(any)'}" if t["kind"] != "class" else "") +
             (f": {_clip(t['definition'], 150)}" if t["definition"] else "") for t in terms]
    return ("\n\n**Reusable vocabulary terms** (loaded by the team; these prefixed names exist - use no other prefixed "
            "terms). A prefix belongs only to these vocabulary terms: refer to the ontology's own classes, also those of "
            "other modules, by their bare name (Audience, never User:Audience).\n" + "\n".join(lines) + "\n"
            "How to reuse them: for a term marked 'align', keep your own class or property and link it - set the class's "
            "\"parent\" to the term when the term is its natural superclass, or add a SubClassOf or (identical meaning "
            "only) EquivalentClasses axiom; set a property's \"sub_property_of\" to a vocabulary property when every "
            "statement made with it also holds for that property (its domain and range must lie within the vocabulary "
            "property's). For a term marked 'use_terms' you may also use the term itself as parent, domain or range "
            "instead of defining an own class for it - but planned classes keep their names. Link only where the "
            "meaning fits.")

def repair_module_prefixes(onto, prefixes) -> tuple:
    """'User:Audience' meint die Klasse Audience des Moduls User - das Modell schreibt das gelegentlich, wenn es
    Klassen anderer Module anspricht. Im Export waere es :User:Audience, ein Verweis ins Leere. Ist der 'Praefix' kein
    Vokabular-Praefix, aber ein Modulname (oder die Klasse existiert), wird der blosse Klassenname daraus."""
    classes = {c.get("name") for c in onto.get("classes") or [] if isinstance(c, dict)}
    modules = {m.get("name") for m in onto.get("modules") or [] if isinstance(m, dict)}
    repaired = []
    def fix(ref):
        if not (isinstance(ref, str) and ":" in ref):
            return ref
        pfx, local = ref.split(":", 1)
        if pfx in prefixes or pfx in ("xsd", "rdf", "rdfs", "owl") or local not in classes:
            return ref
        if pfx in modules or pfx not in prefixes:
            repaired.append(f"repaired {ref} -> {local}")
            return local
        return ref
    for c in onto.get("classes") or []:
        c["parent"] = fix(c.get("parent"))
    for a in onto.get("axioms") or []:
        a["classes"] = [fix(x) for x in a.get("classes") or []]
    for p in onto.get("properties") or []:
        for k in ("domain", "range"):
            p[k] = fix(p.get(k))
    for i in onto.get("individuals") or []:
        i["class"] = fix(i.get("class"))
    return onto, repaired

def check_external_refs(session, onto) -> tuple:
    """Nach der Generierung: Verweise auf Terme geladener Vokabulare pruefen wie bei den Edit-Operationen (der Term
    existiert, ist von der richtigen Art, eine Subproperty passt in Domain und Range). Was nicht passt, wird entfernt
    und berichtet - ein erfundener Term waere im Export ein Verweis ins Leere."""
    onto, repaired = repair_module_prefixes(onto, known_prefixes(session) | set(session_vocab(session)))
    vocab = session_vocab(session)
    if not vocab:
        return onto, repaired
    ed = Editor(onto, label_languages(session)[0], known_prefixes(session), vocab)
    dropped = list(repaired)
    def ok_class(ref):
        if not (isinstance(ref, str) and ":" in ref and ref.split(":", 1)[0] in vocab):
            return True
        try:
            ed._class(ref)
            return True
        except EditError as ex:
            dropped.append(str(ex))
            return False
    for c in ed.o["classes"]:
        if not ok_class(c.get("parent")):
            c["parent"] = None
    ed.o["axioms"] = [a for a in ed.o["axioms"] if all(ok_class(x) for x in a.get("classes") or [])]
    for p in ed.o["properties"]:
        for side in ("domain", "range"):
            if (side == "domain" or p.get("type") == "ObjectProperty") and not ok_class(p.get(side)):
                p[side] = None
    for p in ed.o["properties"]:
        sup = p.get("sub_property_of")
        if isinstance(sup, str) and ":" in sup and sup.split(":", 1)[0] in vocab:
            try:
                ed._super(p, sup)
            except EditError as ex:
                dropped.append(f"{p['name']}: {ex}")
                p.pop("sub_property_of", None)
    ed.o["restrictions"] = [r for r in ed.o["restrictions"] if ok_class(r.get("value"))]
    return ed.result(), dropped

def turtle_for_reasoning(session, turtle) -> str:
    """Ontologie plus die Axiome der verwendeten Vokabular-Terme (Oberbegriffe, Disjunktheit, Domain, Range) -
    nicht das ganze Vokabular: schema.org mit tausenden Termen wuerde den Reasoner sprengen, und nur die verwendeten
    Terme koennen mit der Ontologie kollidieren (DECISIONS 75)."""
    vocab, prefixes = session_vocab(session), {p: v["namespace"] for p, v in (session.get("vocabularies") or {}).items()}
    if not vocab:
        return turtle
    todo = [m.group(0) for m in re.finditer(r"(?<![\w:/#-])(" + "|".join(map(re.escape, vocab)) + r"):[A-Za-z_][\w.-]*",
                                           turtle)]
    seen, lines = set(), []
    def ref(r):
        return r if re.match(r"^[a-z][\w-]*:", r) and r.split(":", 1)[0] in prefixes else f"<{r}>"
    while todo:
        r = todo.pop()
        if r in seen:
            continue
        seen.add(r)
        pfx, local = r.split(":", 1)
        t = (vocab.get(pfx) or {}).get(local)
        if not t:
            continue
        related = [x for x in (t.get("parents") or []) + (t.get("disjoint") or []) +
                   [t.get("domain") or "", t.get("range") or ""] if x]
        todo += [x for x in related if ":" in x and x.split(":", 1)[0] in vocab]
        if t["kind"] == "class":
            lines.append(f"{r} a owl:Class .")
            lines += [f"{r} rdfs:subClassOf {ref(p)} ." for p in t.get("parents") or [] if not p.startswith("_")]
            lines += [f"{r} owl:disjointWith {ref(d)} ." for d in t.get("disjoint") or []]
        elif t["kind"] in ("object", "datatype", "property"):
            kind = {"object": "owl:ObjectProperty", "datatype": "owl:DatatypeProperty"}.get(t["kind"], "rdf:Property")
            lines.append(f"{r} a {kind} .")
            lines += [f"{r} rdfs:subPropertyOf {ref(p)} ." for p in t.get("parents") or []]
            if t["kind"] == "object":
                lines += [f"{r} rdfs:{side} {ref(t[side])} ." for side in ("domain", "range") if t.get(side)]
    if not lines:
        return turtle
    head = "\n".join(f"@prefix {p}: <{ns}> ." for p, ns in prefixes.items())
    return turtle + "\n\n# axioms of the reused vocabulary terms (for reasoning only)\n" + head + "\n" + "\n".join(lines)

def known_prefixes(session) -> set:
    """Prefixes the Turtle export can declare: built-in, selected standards, the team's own prefixes and the
    vocabularies of KNOWN_PREFIXES. A prefixed name with any other prefix would make the Turtle invalid."""
    return (set(_BUILTIN_PREFIXES) | set(standards_to_prefixes(session.get("_standards", [])))
            | set(session_prefixes(session)) | {pfx for _, (pfx, _ns) in KNOWN_PREFIXES.items()})

def _clip(text, n=110):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= n else text[:n - 1] + "…"

ALIGN_MAX_CANDIDATES = 4
ALIGN_MAX_LABELS = 8
_ALIGN_STOP = set("""a an the of and or to in on for by with as is are was were be been has have had at from into
its this that""".split())

def _term_tokens(*texts) -> set:
    from ontology_evaluation import _stem
    words = set()
    for t in texts:
        t = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(t or ""))
        words |= {_stem(w) for w in re.findall(r"[a-z0-9]+", t.lower()) if w not in _ALIGN_STOP and len(w) > 1}
    return words

def _linked_externally(onto, vocab_prefixes) -> set:
    """Eigene Terme, die schon an einen Term eines geladenen Vokabulars angebunden sind."""
    ext = lambda r: isinstance(r, str) and ":" in r and r.split(":", 1)[0] in vocab_prefixes
    done = {c["name"] for c in onto.get("classes") or [] if ext(c.get("parent"))}
    done |= {a["classes"][0] for a in onto.get("axioms") or [] if a.get("type") in ("SubClassOf", "EquivalentClasses")
             and len(a.get("classes") or []) == 2 and ext(a["classes"][1])}
    done |= {p["name"] for p in onto.get("properties") or [] if ext(p.get("sub_property_of"))}
    return done

def term_candidates(vocabs, kind, name, label="", limit=ALIGN_MAX_CANDIDATES) -> list:
    """Die aehnlichsten Terme geladener Vokabulare zu einem eigenen Namen, als (Punkte, prefix:Name, Term): gleicher
    Name oder gleiches Label, das Kopfwort ist der Term ('ProvenanceActivity' -> prov:Activity), oder starke
    Wortueberschneidung. Fuer die Align-Aktion und fuer die Anbindung nach der Planung (DECISIONS 101)."""
    toks = _term_tokens(name, label) if kind == "class" else _term_tokens(name)
    if not toks:
        return []
    head = _term_tokens(re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name).split()[-1])
    keys = {concept_key(name), concept_key(label)} - {""}
    scored = []
    for pfx, voc in vocabs.items():        # ueber den Wortindex statt ueber alle Terme (DECISIONS 100)
        for t, ttoks in vocab_candidates(voc, kind, toks, keys if kind == "class" else ()):
            if not ttoks:
                continue
            ref = f"{pfx}:{t['name']}"
            if kind == "class" and (concept_key(t["name"]) in keys or concept_key(t.get("label")) in keys):
                score = 3.0
            elif kind == "property" and ttoks == toks:
                score = 3.0
            elif kind == "class" and len(ttoks) == 1 and ttoks == head:
                score = 2.0
            else:
                j = len(toks & ttoks) / len(toks | ttoks)
                if j < 0.5:
                    continue
                score = 1.0 + j
            scored.append((score, ref, t))
    scored.sort(key=lambda s: (-s[0], s[1]))
    return scored[:limit]

def class_candidates(vocabs, name, labels=(), limit=ALIGN_MAX_CANDIDATES) -> list:
    """term_candidates fuer eine Klasse mit mehreren Bezeichnungen: ihrem Namen und den Labels und Varianten der
    Inventar-Begriffe, die sie vertritt (VA-Lauf 1: der Name allein fand nur fuer 8 von 219 geplanten Klassen
    Kandidaten). Je Term zaehlt die beste Bezeichnung."""
    best = {}
    found = term_candidates(vocabs, "class", name, re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name), limit=20)
    for label in list(dict.fromkeys(x for x in labels if isinstance(x, str) and x.strip()))[:ALIGN_MAX_LABELS]:
        found += term_candidates(vocabs, "class", label, label, limit=20)
    for score, ref, t in found:
        if ref not in best or score > best[ref][0]:
            best[ref] = (score, ref, t)
    return sorted(best.values(), key=lambda s: (-s[0], s[1]))[:limit]

def align_candidates(session) -> list:
    """Je eigener Klasse und Property die aehnlichsten Terme der geladenen Vokabulare: gleicher Name oder gleiches
    Label, das Kopfwort des eigenen Namens ist der Term ('ProvenanceActivity' -> prov:Activity), oder starke
    Wortueberschneidung. Schon angebundene oder bewusst nicht angebundene Terme fehlen."""
    vocabs = session.get("vocabularies") or {}
    onto = session.get("ontology") or {}
    if not vocabs or not onto:
        return []
    decided = set(session.get("gap_align_decisions") or [])
    linked = _linked_externally(onto, set(vocabs))
    out = []
    own = [("class", c) for c in onto.get("classes") or [] if isinstance(c, dict) and c.get("name")] + \
          [("property", p) for p in onto.get("properties") or [] if isinstance(p, dict) and p.get("name")]
    for kind, x in own:
        if x["name"] in linked or x["name"] in decided:
            continue
        label = next(iter((x.get("labels") or {}).values()), "")
        toks = _term_tokens(x["name"], label) if kind == "class" else _term_tokens(x["name"])
        if not toks:
            continue
        scored = class_candidates(vocabs, x["name"], [label, *(x.get("inventory_concepts") or [])]) \
            if kind == "class" else term_candidates(vocabs, kind, x["name"], label)
        if scored:
            out.append({"name": x["name"], "kind": kind if kind == "class" else x.get("type"), "module": x.get("module"),
                        "description": x.get("description") or "",
                        "domain": x.get("domain"), "range": x.get("range"),
                        "candidates": [{"ref": r, "kind": t.get("kind"), "label": t.get("label") or "",
                                        "definition": t.get("definition") or "", "parents": t.get("parents") or [],
                                        "domain": t.get("domain") or "", "range": t.get("range") or ""}
                                       for _, r, t in scored[:ALIGN_MAX_CANDIDATES]]})
    return out

def align_listing(cands) -> str:
    """Die eigenen Terme mit ihren Kandidaten, fuer die Align-Aktion und die Anbindung nach den Modulen."""
    lines = []
    for c in cands:
        head = f"- {c['name']} ({c['kind']}" + (f", module {c['module']}" if c.get("module") else "") + ")"
        if c["kind"] != "class":
            head += f": {c.get('domain') or '(any)'} -> {c.get('range') or '(any)'}"
        lines.append(head + (f": {_clip(c['description'], 160)}" if c.get("description") else ""))
        for t in c["candidates"]:
            lines.append(f"    candidate {t['ref']} ({t['kind']})" + (f' "{t["label"]}"' if t["label"] else "") +
                         (f", below {', '.join(t['parents'][:2])}" if t["parents"] else "") +
                         (f", {t['domain'] or '(any)'} -> {t['range'] or '(any)'}" if t["kind"] != "class" else "") +
                         (f": {_clip(t['definition'], 140)}" if t["definition"] else ""))
    return "\n".join(lines)

def build_align_intro(session) -> str:
    standards = {s.get("prefix"): s for s in session.get("suggested_standards") or [] if isinstance(s, dict)}
    vocabs = "\n".join(f"- {p}: {v.get('name')} <{v.get('namespace')}>" +
                       (f" - the team chose to {('use its terms directly' if standards[p].get('decision') == 'use_terms' else 'align with it')}"
                        if p in standards else "") for p, v in (session.get("vocabularies") or {}).items())
    return (
        "Link this ontology's own classes and properties to terms of reused vocabularies, so that it interoperates with "
        "them. Loaded vocabularies:\n" + vocabs + "\n\n"
        "For each own term listed below, with its candidate terms, decide by MEANING (definitions), not by name:\n"
        "- add_axiom SubClassOf [own class, prefix:Term] if every instance of the own class is an instance of the "
        "vocabulary class - the usual case;\n"
        "- add_axiom EquivalentClasses [own class, prefix:Term] only if both have exactly the same instances;\n"
        "- update_property with \"sub_property_of\": \"prefix:term\" if every statement made with the own property also "
        "holds with the vocabulary property; its domain and range must lie within the vocabulary property's (the server "
        "checks this, including the classes you link in the same answer);\n"
        "- nothing, if no candidate fits - list the own term under \"skipped\" with the reason.\n"
        "Use only the candidate terms given. Never rename, remove or redefine own terms. Do not link a class to two "
        "vocabulary classes that exclude each other.\n"
        'Answer as {"summary":"...","ops":[...],"skipped":[{"item":"OwnTermName","reason":"..."}]}\n\nOwn terms and candidates:\n')
