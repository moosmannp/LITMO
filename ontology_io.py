"""Ontologie <-> Turtle/RDF: Prefixe, Serialisierung, Einlesen, Syntaxpruefung, SHACL."""

import re

from ontology_edits import COUNTED, restriction_key, restriction_text
from project import find_pattern, PATTERN_CATALOG

# ── OWL/Turtle ─────────────────────────────────────────────────────────────────

# ── Known Prefix Mapping ───────────────────────────────────────────────────────
KNOWN_PREFIXES = {
    "schema.org":        ("schema",   "https://schema.org/"),
    "schema":            ("schema",   "https://schema.org/"),
    "foaf":              ("foaf",     "http://xmlns.com/foaf/0.1/"),
    "dublin core":       ("dc",       "http://purl.org/dc/elements/1.1/"),
    "dcterms":           ("dcterms",  "http://purl.org/dc/terms/"),
    "dc":                ("dc",       "http://purl.org/dc/elements/1.1/"),
    "skos":              ("skos",     "http://www.w3.org/2004/02/skos/core#"),
    "prov-o":            ("prov",     "http://www.w3.org/ns/prov#"),
    "prov":              ("prov",     "http://www.w3.org/ns/prov#"),
    "ssn":               ("ssn",      "http://www.w3.org/ns/ssn/"),
    "sosa":              ("sosa",     "http://www.w3.org/ns/sosa/"),
    "goodrelations":     ("gr",       "http://purl.org/goodrelations/v1#"),
    "gr":                ("gr",       "http://purl.org/goodrelations/v1#"),
    "bfo":               ("bfo",      "http://purl.obolibrary.org/obo/BFO_"),
    "dolce":             ("dolce",    "http://www.loa-cnr.it/ontologies/DOLCE-Lite.owl#"),
    "vcard":             ("vcard",    "http://www.w3.org/2006/vcard/ns#"),
    "time":              ("time",     "http://www.w3.org/2006/time#"),
    "geo":               ("geo",      "http://www.w3.org/2003/01/geo/wgs84_pos#"),
    "org":               ("org",      "http://www.w3.org/ns/org#"),
    "dcat":              ("dcat",     "http://www.w3.org/ns/dcat#"),
    "data cube":         ("qb",       "http://purl.org/linked-data/cube#"),
    "qb":                ("qb",       "http://purl.org/linked-data/cube#"),
    "void":              ("void",     "http://rdfs.org/ns/void#"),
    "wikidata":          ("wd",       "http://www.wikidata.org/entity/"),
    "dbpedia":           ("dbr",      "http://dbpedia.org/resource/"),
    "iao":               ("iao",      "http://purl.obolibrary.org/obo/IAO_"),
    "ro":                ("ro",       "http://purl.obolibrary.org/obo/RO_"),
    "obi":               ("obi",      "http://purl.obolibrary.org/obo/OBI_"),
    "chebi":             ("chebi",    "http://purl.obolibrary.org/obo/CHEBI_"),
    "ncit":              ("ncit",     "http://ncicb.nci.nih.gov/xml/owl/EVS/Thesaurus.owl#"),
    "odrl":              ("odrl",    "http://www.w3.org/ns/odrl/2/"),
    "dpv":               ("dpv",     "https://w3id.org/dpv#"),
    "oa":                ("oa",      "http://www.w3.org/ns/oa#"),
    "as":                ("as",      "https://www.w3.org/ns/activitystreams#"),
    "brick":             ("brick",   "https://brickschema.org/schema/Brick#"),
    "schema.org":        ("schema",  "https://schema.org/"),
    "wot":               ("wot",     "https://www.w3.org/2019/wot/td#"),
    "qudt":              ("qudt",    "http://qudt.org/schema/qudt/"),
    "unit":              ("unit",    "http://qudt.org/vocab/unit/"),
    "ex":                ("ex",      "http://example.org/"),
}

# Hosts persistenter Namespaces: eine URL mit '/' am Ende ist dort ein Vokabular, sonst meist eine Webseite
NAMESPACE_HOSTS = ("purl.org/", "w3id.org/", "purl.obolibrary.org/", "schema.org/", "www.w3.org/ns/", "xmlns.com/")

def _looks_like_namespace(url) -> bool:
    """Ein Namespace endet auf '#', oder auf '/' bei einem Host fuer persistente Namespaces. Spezifikations- und
    Dokumentationsseiten (w3.org/TR/..., .../docs/), Repositories und Suchanfragen sind keine (DECISIONS 73)."""
    url = str(url or "").strip()
    if not re.match(r"^https?://[^\s?]+$", url) or "/TR/" in url or "github.com" in url:
        return False
    return url.endswith("#") or (url.endswith("/") and any(h in url for h in NAMESPACE_HOSTS))

def standards_to_prefixes(standards):
    """Leitet Prefix-Deklarationen aus den ausgewaehlten Standards ab: ein ausdruecklich angegebener Prefix mit
    Namespace, sonst ein bekanntes Vokabular, dessen Schluessel als ganzes Wort im Namen steht (der laengste zuerst:
    "DCAT 3" ist dcat, nicht dc), sonst aus einer URL, die wie ein Namespace aussieht. Eine Webseite ergibt keinen
    Prefix - ein falscher Namespace waere schlimmer als keiner."""
    prefixes = {}
    keys = sorted(KNOWN_PREFIXES, key=len, reverse=True)
    for s in (standards or []):
        if not isinstance(s, dict):
            continue
        pfx, ns = str(s.get("prefix") or "").strip(), str(s.get("namespace") or "").strip()
        if pfx and re.match(r"^[A-Za-z][\w-]*$", pfx) and _looks_like_namespace(ns):
            prefixes[pfx] = ns
            continue
        name_key = str(s.get("name") or "").lower()
        hit = next((k for k in keys if re.search(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", name_key)), None)
        if hit:
            p, n = KNOWN_PREFIXES[hit]
            prefixes[p] = n
            continue
        url = str(s.get("url") or "").strip()
        if _looks_like_namespace(url):
            seg = re.sub(r"[^a-z0-9]", "", url.rstrip("#/").split("/")[-1].lower())[:12]
            if seg and seg[0].isalpha() and seg not in prefixes:
                prefixes[seg] = url
    return prefixes

_BUILTIN_PREFIXES = {"owl", "rdf", "rdfs", "xsd", "sh"}

def _ttl_str(s: str) -> str:
    """Escape a string literal for Turtle."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")

def _ttl_local(s: str) -> str:
    """Macht aus einem beliebigen Namen einen gueltigen Turtle-Local-Name."""
    local = re.sub(r'[^A-Za-z0-9_]', '', (s or "").replace(" ", ""))
    return local if local and not local[0].isdigit() else "M" + local

def _has_known_prefix(value: str, std_prefixes: dict) -> bool:
    """Gibt True zurück wenn value bereits einen bekannten Prefix trägt (z.B. 'prov:Entity')."""
    all_prefixes = {p + ":" for p in (_BUILTIN_PREFIXES | set(std_prefixes))}
    return any(value.startswith(p) for p in all_prefixes)

def _collect_used_prefixes(onto: dict, std_prefixes: dict) -> dict:
    """Scannt alle Strings im onto-Dict nach prefix:LocalName-Mustern und ergänzt
    fehlende Prefixes aus KNOWN_PREFIXES."""
    known_by_pfx = {pfx: ns_uri for _, (pfx, ns_uri) in KNOWN_PREFIXES.items()}
    # Baue Lookup: kurzname → URI (Duplikate werden durch dict-Reihenfolge aufgelöst)
    extra = {}
    # Alle relevanten Stringwerte sammeln
    candidates = []
    for cls in onto.get("classes", []):
        candidates += [cls.get("parent", "")]
    for p in onto.get("properties", []):
        candidates += [p.get("domain", ""), p.get("range", "")]
    for i in onto.get("individuals", []):
        candidates += [i.get("class", "")]
    for ax in onto.get("axioms", []):  # auch Axiome koennen externe Klassen nennen (z.B. per Edit-Operation)
        candidates += [c for c in ax.get("classes") or [] if isinstance(c, str)]
    for r in onto.get("restrictions") or []:
        candidates += [x for x in (r.get("property"), r.get("value")) if isinstance(x, str)]
    pattern = re.compile(r'^([a-zA-Z][a-zA-Z0-9_\-]*):[A-Za-z0-9_]')
    all_known = _BUILTIN_PREFIXES | set(std_prefixes)
    for val in candidates:
        if not val:
            continue
        m = pattern.match(val)
        if m:
            pfx = m.group(1)
            if pfx not in all_known and pfx not in extra and pfx in known_by_pfx:
                extra[pfx] = known_by_pfx[pfx]
    return extra

def _label_lines(entity, fallback):
    """rdfs:label je Sprache. Aeltere Ontologien haben nur label_de (deutsch)."""
    labels = entity.get("labels") if isinstance(entity.get("labels"), dict) else {}
    labels = {str(k).strip().lower(): v for k, v in labels.items()
              if v and re.match(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]+)*$", str(k).strip())}
    if not labels:
        labels = {"de": entity["label_de"]} if entity.get("label_de") else {"en": fallback}
    return ['    rdfs:label "' + _ttl_str(str(v)) + '"@' + lang + ' ;' for lang, v in labels.items()]

PROPERTY_CHARACTERISTIC_TYPES = {"functional": "FunctionalProperty", "inverse_functional": "InverseFunctionalProperty",
                                 "transitive": "TransitiveProperty", "symmetric": "SymmetricProperty",
                                 "asymmetric": "AsymmetricProperty"}

def _is_datatype(ref) -> bool:
    return str(ref).startswith(("xsd:", "rdf:", "rdfs:Literal"))

def _restriction_node(r, term) -> str:
    """Eine Klassenrestriktion als anonyme owl:Restriction (Phase 5, DECISIONS 125)."""
    value, kind = term(r["value"]), r.get("kind")
    head = "[ a owl:Restriction ; owl:onProperty " + term(r["property"]) + " ; "
    if kind == "only":
        return head + "owl:allValuesFrom " + value + " ]"
    if kind in COUNTED:
        card = {"min": "minQualifiedCardinality", "max": "maxQualifiedCardinality", "exactly": "qualifiedCardinality"}[kind]
        on = "owl:onDataRange " if _is_datatype(r["value"]) else "owl:onClass "
        return head + f'owl:{card} "{int(r.get("n") or 0)}"^^xsd:nonNegativeInteger ; ' + on + value + " ]"
    return head + "owl:someValuesFrom " + value + " ]"

def ontology_to_turtle(onto, standards=None, custom_prefixes=None):
    ns = onto.get("namespace", "http://example.org/onto#")
    desc_lang = onto.get("description_language") or "en"  # Sprache von rdfs:comment und Ontologie-Label
    name = onto.get("ontology_name") or "Ontology"
    std_prefixes = standards_to_prefixes(standards or onto.get("_standards", []))
    if custom_prefixes:
        std_prefixes.update(custom_prefixes)
    std_prefixes.update(_collect_used_prefixes(onto, std_prefixes))
    prefix_lines = [
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .",
        "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
    ]
    for pfx, ns_uri in sorted(std_prefixes.items()):
        prefix_lines.append("@prefix " + pfx + ": <" + ns_uri + "> .")
    prefix_lines.append("@prefix : <" + ns + "> .")
    modules = [m for m in onto.get("modules", []) if isinstance(m, dict) and m.get("name")]
    if modules:
        prefix_lines.insert(-1, "@prefix opla: <http://ontologydesignpatterns.org/opla#> .")
    term = lambda x: x if _has_known_prefix(x, std_prefixes) else ":" + x
    restrictions = {}
    for r in onto.get("restrictions") or []:
        if isinstance(r, dict) and r.get("class") and r.get("property") and r.get("value") and \
                r.get("kind") in ("some", "only", *COUNTED):
            restrictions.setdefault(r["class"], []).append(r)
    lines = prefix_lines + ["",
        "<" + ns.rstrip("#/") + "> a owl:Ontology ;",
        '    rdfs:label "' + _ttl_str(name) + '"@' + desc_lang +
        (" ;\n    <http://purl.org/dc/terms/license> <" + onto["license"].strip() + ">"  # OOPS! P41
         if re.match(r"^https?://[^\s<>\"]+$", (onto.get("license") or "").strip()) else "") + " .", "",
    ]
    # MOMo Schritt 10: OPLa-Annotationen fuer Module und deren Pattern-Provenienz.
    # Die OPLa-Terme selbst deklarieren, sonst meldet OOPS! P34/P35 (untyped class/property).
    if modules:
        lines += ["opla:Module a owl:Class .",
                  "opla:isNativeTo a owl:AnnotationProperty .",
                  "opla:reusesPatternAsTemplate a owl:AnnotationProperty .", ""]
    if any(c.get("sources") for c in onto.get("classes", []) if isinstance(c, dict)):
        lines += ["<http://purl.org/dc/terms/source> a owl:AnnotationProperty .", ""]
    for m in modules:
        mod_ref = ":" + _ttl_local(m["name"]) + "Module"
        lines.append(mod_ref + " a opla:Module ;")
        lines.append('    rdfs:label "' + _ttl_str(m["name"]) + '"@en ;')
        if m.get("key_notion"):
            lines.append('    rdfs:comment "Key notion: ' + _ttl_str(m["key_notion"]) + '"@en ;')
        if m.get("documentation"):
            lines.append('    rdfs:comment "' + _ttl_str(m["documentation"]) + '"@en ;')
        if m.get("pattern"):
            pat = find_pattern(m["pattern"])
            if pat:
                # Datei im ODPA-Repository: aufloesbar und zeigt genau die verwendete Version.
                # (Die Ontologie-IRIs der Patterns sind oft Protege-Defaults.)
                lines.append("    opla:reusesPatternAsTemplate <" + pat["owl_url"] + "> ;")
            else:
                # Nicht im Katalog (z.B. frei eingetragen): nur als Kommentar dokumentieren.
                lines.append('    rdfs:comment "Based on pattern: ' + _ttl_str(m["pattern"]) + '"@en ;')
        lines[-1] = lines[-1].rstrip(" ;") + " ."
        lines.append("")
    for cls in onto.get("classes", []):
        lines.append(":" + cls["name"] + " a owl:Class ;")
        lines += _label_lines(cls, cls["name"])
        if cls.get("description"):
            lines.append('    rdfs:comment "' + _ttl_str(cls["description"]) + '"@' + desc_lang + ' ;')
        if modules and cls.get("module"):
            lines.append("    opla:isNativeTo :" + _ttl_local(cls["module"]) + "Module ;")
        if cls.get("parent"):
            par = cls["parent"]
            lines.append("    rdfs:subClassOf " + (par if _has_known_prefix(par, std_prefixes) else ":" + par) + " ;")
        for r in restrictions.get(cls["name"], []):
            lines.append("    rdfs:subClassOf " + _restriction_node(r, term) + " ;")
        # Herkunft aus dem Literaturkorpus: Quellen der Definition und gleichbedeutende Begriffe bestehender Ontologien
        for src in cls.get("sources") or []:
            if isinstance(src, str) and src.strip():
                lines.append('    <http://purl.org/dc/terms/source> "' + _ttl_str(src.strip()) + '" ;')
        for uri in cls.get("see_also") or []:
            if isinstance(uri, str) and re.match(r"^https?://[^\s<>\"]+$", uri.strip()):
                lines.append("    rdfs:seeAlso <" + uri.strip() + "> ;")
        lines[-1] = lines[-1].rstrip(" ;") + " ."
        lines.append("")
    for p in onto.get("properties", []):
        ot = "owl:ObjectProperty" if p.get("type") == "ObjectProperty" else "owl:DatatypeProperty"
        ot += "".join(" , owl:" + PROPERTY_CHARACTERISTIC_TYPES[c] for c in p.get("characteristics") or []
                      if c in PROPERTY_CHARACTERISTIC_TYPES)
        lines.append(":" + p["name"] + " a " + ot + " ;")
        lines += _label_lines(p, p["name"])
        if p.get("description"):
            lines.append('    rdfs:comment "' + _ttl_str(p["description"]) + '"@' + desc_lang + ' ;')
        if p.get("domain"):
            d = p["domain"]
            lines.append("    rdfs:domain " + (d if _has_known_prefix(d, std_prefixes) else ":" + d) + " ;")
        if p.get("range"):
            r = p["range"]
            lines.append("    rdfs:range " + (r if _has_known_prefix(r, std_prefixes) else ":" + r) + " ;")
        if p.get("inverse_of") and p.get("type") == "ObjectProperty" and p["inverse_of"] != p["name"]:
            inv = p["inverse_of"]
            lines.append("    owl:inverseOf " + (inv if _has_known_prefix(inv, std_prefixes) else ":" + inv) + " ;")
        if p.get("sub_property_of") and p["sub_property_of"] != p["name"]:
            sup = p["sub_property_of"]
            lines.append("    rdfs:subPropertyOf " + (sup if _has_known_prefix(sup, std_prefixes) else ":" + sup) + " ;")
        if modules and p.get("module"):
            lines.append("    opla:isNativeTo :" + _ttl_local(p["module"]) + "Module ;")
        lines[-1] = lines[-1].rstrip(" ;") + " ."
        lines.append("")
    # Wiederverwendete Klassen aus Standards (z.B. schema:Person als Oberklasse) explizit als Klasse
    # deklarieren — sonst meldet OOPS! P34 (untyped class).
    external = set()
    for cls in onto.get("classes", []):
        external.add(cls.get("parent") or "")
    for p in onto.get("properties", []):
        external.add(p.get("domain") or "")
        if p.get("type") == "ObjectProperty":
            external.add(p.get("range") or "")
    for i in onto.get("individuals", []):
        external.add(i.get("class") or "")
    for ax in onto.get("axioms", []):
        external.update(c for c in ax.get("classes", []) if c)
    external.update(r["value"] for rs in restrictions.values() for r in rs if not _is_datatype(r["value"]))
    for ref in sorted(external):
        if (_has_known_prefix(ref, std_prefixes) and not ref.startswith(("xsd:", "rdf:", "rdfs:", "owl:"))):
            lines.append(ref + " a owl:Class .")
    # Properties wiederverwendeter Vokabulare als Oberproperty: deklarieren (OOPS! P34/P35)
    used_props = {(p["sub_property_of"], p.get("type") or "ObjectProperty") for p in onto.get("properties", [])
                  if ":" in str(p.get("sub_property_of") or "")}
    used_props |= {(r["property"], "DatatypeProperty" if _is_datatype(r["value"]) else "ObjectProperty")
                   for rs in restrictions.values() for r in rs if ":" in r["property"]}
    for ref, kind in sorted(used_props):
        if _has_known_prefix(ref, std_prefixes) and not ref.startswith(("rdf:", "rdfs:", "owl:")):
            lines.append(ref + " a owl:" + kind + " .")
    if lines[-1] != "":
        lines.append("")
    for i in onto.get("individuals", []):
        cls_val = i.get("class", "")
        cls_ref = cls_val if _has_known_prefix(cls_val, std_prefixes) else ":" + cls_val
        lines.append(":" + i["name"] + " a " + cls_ref + " ;")
        lines += _label_lines(i, i["name"])
        lines[-1] = lines[-1].rstrip(" ;") + " ."
        lines.append("")
    for ax in onto.get("axioms", []):
        ax_type = ax.get("type", "")
        ax_classes = [c if _has_known_prefix(c, std_prefixes) else ":" + c for c in ax.get("classes", []) if c]
        if len(ax_classes) < 2:
            continue
        if ax_type == "DisjointClasses":
            lines.append("[ a owl:AllDisjointClasses ; owl:members ( " + " ".join(ax_classes) + " ) ] .")
        elif ax_type == "EquivalentClasses" and len(ax_classes) == 2:
            lines.append(ax_classes[0] + " owl:equivalentClass " + ax_classes[1] + " .")
        elif ax_type == "SubClassOf" and len(ax_classes) == 2:
            lines.append(ax_classes[0] + " rdfs:subClassOf " + ax_classes[1] + " .")
        lines.append("")
    # Nur Praefixe deklarieren, die vorkommen: ausgewaehlte Standards ohne Verwendung waeren tote Zeilen
    body = "\n".join(lines[len(prefix_lines):])
    def used(line):
        pfx = line.split()[1][:-1]
        return pfx in ("owl", "rdf", "rdfs", "xsd", "") or re.search(r"(?<![\w-])" + re.escape(pfx) + r":", body)
    return "\n".join([l for l in prefix_lines if used(l)] + lines[len(prefix_lines):])

def _graph_labels(g, node, fallback):
    from rdflib.namespace import RDFS
    labels = {}
    for lit in g.objects(node, RDFS.label):
        labels.setdefault(getattr(lit, "language", None) or "en", str(lit))
    return labels or {"en": fallback}

OPLA = "http://ontologydesignpatterns.org/opla#"
DCT_SOURCE = "http://purl.org/dc/terms/source"

def _own_namespace(g, onto_node) -> str:
    """Der eigene Namespace: der leere Prefix, sonst die Ontologie-IRI mit dem Trenner, den ihre Klassen verwenden.
    Vorher wurde er immer auf '#' gesetzt - ein Namespace auf '/' aenderte sich beim Speichern (Code-Review T1)."""
    from rdflib.namespace import OWL, RDF
    empty = next((str(uri) for pfx, uri in g.namespaces() if pfx == ""), None)
    if empty:
        return empty
    if onto_node is None:
        return ""
    base = str(onto_node).rstrip("#/")
    subjects = [str(x) for t in (OWL.Class, OWL.ObjectProperty, OWL.DatatypeProperty) for x in g.subjects(RDF.type, t)]
    return base + "/" if any(x.startswith(base + "/") for x in subjects) and \
        not any(x.startswith(base + "#") for x in subjects) else base + "#"

def rdf_graph_to_onto(g, source_turtle: str, prefer=None) -> dict:
    """Rekonstruiert ein onto-Dict aus einem rdflib-Graph - mit allem, was ontology_to_turtle schreibt: Module
    (opla:Module, opla:isNativeTo), Quellen (dcterms:source), seeAlso, Axiome (Disjunktheit, Aequivalenz, weitere
    Oberklassen), und externe Terme mit ihrem Prefix (schema:Person, xsd:string) statt nur dem lokalen Namen
    (Code-Review T1: vorher gingen beim Speichern im Turtle-Editor Module, Axiome und externe Verweise verloren).
    prefer: Klasse -> Oberklasse, die bei mehreren Oberklassen die Hauptoberklasse bleibt (die bisherige)."""
    from rdflib.namespace import OWL, RDFS, RDF
    from rdflib import URIRef, Literal
    from rdflib.collection import Collection

    onto_node = g.value(predicate=RDF.type, object=OWL.Ontology)
    ns = _own_namespace(g, onto_node)
    bound = sorted(((str(uri), pfx) for pfx, uri in g.namespaces() if pfx), key=lambda x: -len(x[0]))
    local_re = re.compile(r"[A-Za-z_][\w.-]*$")

    def own(u):
        return isinstance(u, URIRef) and (not ns or (str(u).startswith(ns) and bool(local_re.match(str(u)[len(ns):]))))

    def ref(u):
        """Eigener Term: lokaler Name; fremder Term: prefix:lokal, wenn der Graph den Prefix kennt."""
        if not isinstance(u, URIRef):
            return None
        s_ = str(u)
        if own(u):
            return s_[len(ns):] if ns else s_.split("#")[-1].split("/")[-1]
        for nsu, pfx in bound:
            if s_.startswith(nsu) and local_re.match(s_[len(nsu):]):
                return f"{pfx}:{s_[len(nsu):]}"
        return s_.split("#")[-1].split("/")[-1]

    module_type = URIRef(OPLA + "Module")
    module_name = {}
    modules = []
    for m in sorted(set(g.subjects(RDF.type, module_type)), key=str):
        name = str(g.value(m, RDFS.label) or ref(m) or "")
        if not name:
            continue
        key_notion, docs, pattern = "", [], None
        for c in g.objects(m, RDFS.comment):
            text = str(c)
            if text.startswith("Key notion: "):
                key_notion = text[len("Key notion: "):]
            elif text.startswith("Based on pattern: "):
                pattern = text[len("Based on pattern: "):]
            else:
                docs.append(text)
        url = g.value(m, URIRef(OPLA + "reusesPatternAsTemplate"))
        if url is not None:
            pattern = next((x["id"] for x in PATTERN_CATALOG.get("patterns", []) if x.get("owl_url") == str(url)),
                           pattern or str(url))
        module_name[m] = name
        modules.append({"name": name, "key_notion": key_notion or name, "pattern": pattern,
                        "documentation": " ".join(docs)})
    native = lambda x: module_name.get(g.value(x, URIRef(OPLA + "isNativeTo")))

    prefer = prefer or {}
    classes, class_nodes, axioms, restrictions = [], set(), [], []
    cards = {OWL.minQualifiedCardinality: "min", OWL.maxQualifiedCardinality: "max", OWL.qualifiedCardinality: "exactly",
             OWL.minCardinality: "min", OWL.maxCardinality: "max", OWL.cardinality: "exactly"}

    def restriction(name, node):
        """owl:Restriction unter rdfs:subClassOf als Klassenrestriktion; was das Modell nicht kennt (hasValue,
        zusammengesetzte Fuellungen) bleibt aus."""
        prop = ref(g.value(node, OWL.onProperty))
        if not prop:
            return None
        for pred, kind in ((OWL.someValuesFrom, "some"), (OWL.allValuesFrom, "only")):
            v = g.value(node, pred)
            if v is not None:
                return {"class": name, "property": prop, "kind": kind, "value": ref(v), "n": None} if ref(v) else None
        for pred, kind in cards.items():
            n = g.value(node, pred)
            if n is None:
                continue
            filler = g.value(node, OWL.onClass) or g.value(node, OWL.onDataRange)
            value = ref(filler) if filler is not None else ("owl:Thing" if (prop_type(prop) != "DatatypeProperty")
                                                            else "rdfs:Literal")
            try:
                return {"class": name, "property": prop, "kind": kind, "value": value, "n": int(n)} if value else None
            except ValueError:
                return None
        return None
    prop_type = lambda name: next(("DatatypeProperty" for p in g.subjects(RDF.type, OWL.DatatypeProperty)
                                   if ref(p) == name), "ObjectProperty")
    # Klassen, die als Durchschnitt definiert sind (owl:intersectionOf, direkt oder unter owl:equivalentClass): die
    # benannten Glieder werden Oberklassen, einfache Restriktionen Klassenrestriktionen - als notwendige Bedingungen,
    # die Definition selbst kennt das Modell nicht (DECISIONS 138; W3C-Wein: RedWine = Wine und hasColor value Red,
    # vorher blieben 62 von 74 Klassen ohne Oberklasse)
    def definitions(cls):
        lists = list(g.objects(cls, OWL.intersectionOf))
        lists += [x for e in g.objects(cls, OWL.equivalentClass) if not isinstance(e, URIRef)
                  for x in g.objects(e, OWL.intersectionOf)]
        return [m for lst in lists for m in Collection(g, lst)]
    read_defs = 0
    for cls in sorted(set(g.subjects(RDF.type, OWL.Class)), key=str):
        if not own(cls) or cls == module_type:
            continue
        name = ref(cls)
        members = definitions(cls)
        read_defs += bool(members)
        supers = sorted(({ref(x) for x in g.objects(cls, RDFS.subClassOf) if isinstance(x, URIRef)} |
                         {ref(m) for m in members if isinstance(m, URIRef)}) - {name})
        own_supers = [x for x in supers if ":" not in x]
        if name in prefer and (prefer[name] in supers or prefer[name] is None):
            parent = prefer[name]          # die bisherige Hauptoberklasse, auch "keine" (obere Schicht: Agent)
        else:
            parent = (own_supers or supers or [None])[0]
        axioms += [{"type": "SubClassOf", "classes": [name, x]} for x in supers if x != parent]
        for node in [*g.objects(cls, RDFS.subClassOf), *(m for m in members if not isinstance(m, URIRef))]:
            if not isinstance(node, URIRef) and (node, RDF.type, OWL.Restriction) in g:
                r = restriction(name, node)
                if r:
                    restrictions.append(r)
        entry = {"name": name, "labels": _graph_labels(g, cls, name), "description": str(g.value(cls, RDFS.comment) or ""),
                 "parent": parent, "sources": sorted(str(x) for x in g.objects(cls, URIRef(DCT_SOURCE))
                                                     if isinstance(x, Literal)),
                 "see_also": sorted(str(x) for x in g.objects(cls, RDFS.seeAlso) if isinstance(x, URIRef))}
        if native(cls):
            entry["module"] = native(cls)
        classes.append(entry)
        class_nodes.add(cls)

    properties, prop_nodes = [], set()
    for prop_type, type_str in [(OWL.ObjectProperty, "ObjectProperty"), (OWL.DatatypeProperty, "DatatypeProperty")]:
        for prop in sorted(set(g.subjects(RDF.type, prop_type)), key=str):
            if not own(prop):
                continue   # nur verwendete Properties anderer Vokabulare (z.B. prov:used als Oberproperty)
            name = ref(prop)
            entry = {"name": name, "type": type_str, "domain": ref(g.value(prop, RDFS.domain)),
                     "range": ref(g.value(prop, RDFS.range)), "inverse_of": ref(g.value(prop, OWL.inverseOf)),
                     "labels": _graph_labels(g, prop, name), "description": str(g.value(prop, RDFS.comment) or "")}
            sup = ref(g.value(prop, RDFS.subPropertyOf))
            if sup:
                entry["sub_property_of"] = sup
            chars = [c for c, t in PROPERTY_CHARACTERISTIC_TYPES.items() if (prop, RDF.type, OWL[t]) in g]
            if chars:
                entry["characteristics"] = chars
            if native(prop):
                entry["module"] = native(prop)
            properties.append(entry)
            prop_nodes.add(prop)

    # Individuen: eigene Terme mit einem Klassentyp - nicht Module, Annotationen oder die Ontologie selbst, jedes einmal
    skip_types = {OWL.NamedIndividual, OWL.Class, OWL.ObjectProperty, OWL.DatatypeProperty, OWL.AnnotationProperty,
                  OWL.Ontology, module_type, OWL.AllDisjointClasses}
    individuals = []
    for ind in sorted(set(g.subjects(RDF.type, None)), key=str):
        if not own(ind) or ind in class_nodes or ind in prop_nodes or ind in module_name or ind == onto_node:
            continue
        types = sorted((t for t in g.objects(ind, RDF.type) if isinstance(t, URIRef) and t not in skip_types), key=str)
        if types:
            name = ref(ind)
            individuals.append({"name": name, "class": ref(types[0]), "labels": _graph_labels(g, ind, name)})

    # Axiome: Disjunktheit (Liste oder paarweise) und Aequivalenz zwischen benannten Klassen
    seen = set()
    for node in g.subjects(RDF.type, OWL.AllDisjointClasses):
        members = g.value(node, OWL.members)
        names = [ref(x) for x in Collection(g, members)] if members is not None else []
        if len(names) >= 2 and all(names):
            axioms.append({"type": "DisjointClasses", "classes": names})
            seen.add(frozenset(names))
    for a, b in g.subject_objects(OWL.disjointWith):
        names = [ref(a), ref(b)]
        if all(names) and frozenset(names) not in seen:
            axioms.append({"type": "DisjointClasses", "classes": sorted(names)})
            seen.add(frozenset(names))
    for a, b in g.subject_objects(OWL.equivalentClass):
        names = [ref(a), ref(b)]
        if all(names) and isinstance(a, URIRef) and isinstance(b, URIRef):
            axioms.append({"type": "EquivalentClasses", "classes": names})

    module_of = {c["name"]: c.get("module") for c in classes}
    for r in restrictions:
        r["module"] = module_of.get(r["class"])
        r["natural_language"] = restriction_text(r)
    onto_iri = str(onto_node) if onto_node is not None else ""
    name = str(g.value(onto_node, RDFS.label) or onto_iri.rstrip("#/").split("/")[-1]) if onto_node is not None else "Ontology"
    # was das Modell nicht traegt, sagen statt still weglassen (DECISIONS 138)
    unread = {label: len(list(g.subject_objects(p))) for label, p in (
        ("hasValue restrictions", OWL.hasValue), ("enumerations (owl:oneOf)", OWL.oneOf),
        ("unions (owl:unionOf)", OWL.unionOf), ("complements (owl:complementOf)", OWL.complementOf))}
    report = {"definitions_read_as_superclasses": read_defs, "not_read": {k: v for k, v in unread.items() if v}}
    return {
        "modules": modules,
        "classes": classes,
        "properties": properties,
        "individuals": individuals,
        "axioms": axioms,
        **({"restrictions": restrictions} if restrictions else {}),
        "namespace": ns or "http://example.org/onto#",
        "ontology_name": name,
        "license": str(g.value(onto_node, URIRef("http://purl.org/dc/terms/license")) or "") if onto_node is not None else "",
        "summary": f"Loaded from a file: {len(classes)} classes, {len(properties)} properties, {len(individuals)} individuals.",
        "import_report": report,
    }

def graph_prefixes_used(g, onto) -> dict:
    """Die Prefixe des Graphen, die die externen Verweise des onto-Dicts verwenden (prefix -> Namespace) - damit der
    Turtle-Export sie wieder deklariert."""
    bound = {pfx: str(uri) for pfx, uri in g.namespaces() if pfx}
    refs = [c.get("parent") for c in onto.get("classes") or []]
    refs += [p.get(k) for p in onto.get("properties") or [] for k in ("domain", "range", "sub_property_of", "inverse_of")]
    refs += [i.get("class") for i in onto.get("individuals") or []]
    refs += [x for a in onto.get("axioms") or [] for x in a.get("classes") or []]
    refs += [r.get(k) for r in onto.get("restrictions") or [] for k in ("property", "value")]
    used = {r.split(":", 1)[0] for r in refs if isinstance(r, str) and ":" in r}
    return {p: bound[p] for p in sorted(used) if p in bound}

def keep_from_previous(new, old) -> dict:
    """Nach dem Speichern im Turtle-Editor: was Turtle nicht traegt, aus der bisherigen Fassung uebernehmen - die
    Begriffe des Inventars und die obere Schicht je Klasse, Erklaerung und Modul je Axiom, Modul-Angaben,
    Beschreibungssprache und Zusammenfassung (Code-Review T1)."""
    if not old:
        return new
    old_cls = {c.get("name"): c for c in old.get("classes") or [] if isinstance(c, dict)}
    for c in new["classes"]:
        o = old_cls.get(c["name"]) or {}
        for k in ("inventory_concepts", "layer"):
            if o.get(k):
                c[k] = o[k]
        if o.get("module") and not c.get("module"):
            c["module"] = o["module"]
    for kind in ("properties", "individuals"):      # die Begriffe der Literatur auch hier (DECISIONS 136)
        before = {x.get("name"): x for x in old.get(kind) or [] if isinstance(x, dict)}
        for x in new.get(kind) or []:
            if (before.get(x.get("name")) or {}).get("inventory_concepts"):
                x["inventory_concepts"] = before[x["name"]]["inventory_concepts"]
    key = lambda a: (a.get("type"), tuple(a.get("classes") or []) if a.get("type") == "SubClassOf"
                     else tuple(sorted(a.get("classes") or [])))
    old_ax = {key(a): a for a in old.get("axioms") or [] if isinstance(a, dict)}
    for a in new["axioms"]:
        o = old_ax.get(key(a)) or {}
        for k in ("natural_language", "module", "scoped"):
            if k in o:
                a[k] = o[k]
    old_res = {restriction_key(r): r for r in old.get("restrictions") or [] if isinstance(r, dict)}
    for r in new.get("restrictions") or []:
        o = old_res.get(restriction_key(r)) or {}
        for k in ("natural_language", "module"):
            if o.get(k):
                r[k] = o[k]
    old_mod = {m.get("name"): m for m in old.get("modules") or [] if isinstance(m, dict)}
    order = list(old_mod)                     # RDF kennt keine Reihenfolge: die bisherige der Module behalten
    new["modules"].sort(key=lambda m: order.index(m["name"]) if m["name"] in order else len(order))
    for m in new["modules"]:
        o = old_mod.get(m["name"]) or {}
        for k in ("key_notion", "pattern", "documentation"):   # die Key Notion steht im Turtle nur als Kommentar
            if o.get(k) and (k == "key_notion" or not m.get(k)):
                m[k] = o[k]
    for k in ("description_language", "summary"):
        if old.get(k):
            new[k] = old[k]
    return new

# ── Turtle Syntax Validation ───────────────────────────────────────────────────
def validate_turtle(turtle_str):
    """Validiert Turtle-Syntax via rdflib. Gibt (valid, error_msg) zurueck."""
    try:
        from rdflib import Graph
        g = Graph()
        g.parse(data=turtle_str, format="turtle")
        return True, ""
    except Exception as ex:
        return False, str(ex)

# ── SHACL Generator ────────────────────────────────────────────────────────────
def _shacl_count(v):
    """minCount/maxCount: leer -> keine Angabe, sonst eine nicht-negative ganze Zahl (Code-Review T9)."""
    if v is None or not str(v).strip():
        return None
    try:
        n = int(str(v).strip())
    except ValueError:
        n = -1
    if n < 0:
        raise ValueError(f"min and max count must be whole numbers of 0 or more, not {v!r}")
    return n

def generate_shacl_turtle(onto, constraints):
    ns = onto.get("namespace", "http://example.org/onto#")
    from collections import defaultdict
    out = [
        "@prefix sh:   <http://www.w3.org/ns/shacl#> .",
        "@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .",
        "@prefix :     <" + ns + "> .",
        "",
        "# SHACL Shapes fuer " + onto.get("ontology_name", "Ontologie"),
        "",
    ]
    by_class = defaultdict(list)
    for c in constraints:
        if c.get("target_class"):
            by_class[c["target_class"]].append(c)
    for cls, cons in sorted(by_class.items()):
        valid_cons = [c for c in cons if c.get("property_name", "").strip()]
        if not valid_cons:
            continue
        out.append(":" + cls + "Shape a sh:NodeShape ;")
        out.append("    sh:targetClass :" + cls + " ;")
        for i, c in enumerate(valid_cons):
            prop = c.get("property_name", "")
            if not prop:
                continue
            out.append("    sh:property [")
            out.append("        sh:path :" + prop + " ;")
            mc, xc = _shacl_count(c.get("min_count")), _shacl_count(c.get("max_count"))
            if mc is not None:
                out.append("        sh:minCount " + str(mc) + " ;")
            if xc is not None:
                out.append("        sh:maxCount " + str(xc) + " ;")
            dt = (c.get("datatype") or "").strip()
            if dt:
                if not dt.startswith("xsd:") and not dt.startswith("<"):
                    dt = "xsd:" + dt
                out.append("        sh:datatype " + dt + " ;")
            nk = (c.get("node_kind") or "").strip()
            if nk:
                out.append("        sh:nodeKind " + nk + " ;")
            out[-1] = out[-1].rstrip(" ;")
            out.append("    ] ;")
        out[-1] = "    ] ."           # nur das letzte Property-Objekt schliesst die Form (vorher jedes: kein Turtle)
        out.append("")
    return "\n".join(out)
