"""Baut patterns_catalog.json aus dem ODPA Patterns Repository.

Quelle: https://github.com/odpa/patterns-repository

Aufruf:
    git clone --depth 1 https://github.com/odpa/patterns-repository odpa
    python tools/build_pattern_catalog.py odpa

Je Pattern-Verzeichnis werden die Metadaten-Tabelle (<Name>.md) und die
Formalisierung (.owl/.ttl) gelesen. Aus der OWL-Datei werden die lokal
definierten Klassen und Properties extrahiert, damit das LLM das Pattern
tatsaechlich als Template fuer ein Modul verwenden kann (MOMo Schritt 4).
"""
import json
import re
import xml.etree.ElementTree as ET
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

from rdflib import Graph, URIRef
from rdflib.namespace import OWL, RDF, RDFS

REPO_URL = "https://github.com/odpa/patterns-repository"

# Verzeichnisse, die Kategorien, Anleitungen oder Site-Infrastruktur sind — keine Patterns.
SKIP_DIRS = {
    "_layouts", "public", "Main", "ContentOPs", "AlignmentODPs", "ArchitecturalODPs",
    "LexicoSyntacticODPs", "LogicalODPs", "ReengineeringODPs",
}
SKIP_PREFIXES = ("How", "Submit", "Propose")

# Importierte Hilfsontologien, die in vielen Pattern-Ordnern mitliegen.
SUPPORT_FILES = {"dul.owl", "cpannotationschema.owl", "san.owl", "cos.owl", "kco.owl", "istc.owl"}

MAX_ELEMENTS = 25  # je Elementart, damit der Prompt kompakt bleibt


def _cell(text: str) -> str:
    """Bereinigt eine Zelle der MediaWiki-exportierten Markdown-Tabelle."""
    text = re.sub(r"<li>\s*", "; ", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)   # [label](link) -> label
    text = re.sub(r"\(\d+\)\s*$", "", text)                  # Download-Zaehler "(1355)"
    text = re.sub(r"\s+", " ", text).strip(" ;|")
    return "" if text.lower() in ("stub", "-", "none") else text


def parse_metadata(md_path: Path) -> dict:
    meta = {}
    for line in md_path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"\|\s*([^|]+?):\s*\|(.*)\|\s*$", line)
        if m:
            meta[m.group(1).strip()] = _cell(m.group(2))
    return meta


def _local(uri) -> str:
    return str(uri).rstrip("/#").split("#")[-1].split("/")[-1]


def _dedupe(items: list) -> list:
    """Patterns deklarieren Elemente teils unter mehreren Namespaces (z.B. DUL und eigener)
    mit gleichem lokalem Namen. Behalten wird der Eintrag mit den meisten Angaben."""
    best = {}
    # Unexpandierte IRIs wie "xsd:string" sind Fehler in der Quelldatei, keine Elemente.
    items = [it for it in items if it["name"] and ":" not in it["name"]]
    for it in items:
        if it["name"] not in best or len(it) > len(best[it["name"]]):
            best[it["name"]] = it
    return [best[n] for n in dict.fromkeys(i["name"] for i in items)]


def _elements(classes, obj_props, data_props, ns) -> dict:
    classes, obj_props, data_props = _dedupe(classes), _dedupe(obj_props), _dedupe(data_props)
    return {
        # eine Quelldatei ohne eigenen Namespace gab den lokalen Dateipfad - der ist keiner (DECISIONS 139)
        "namespace": "" if str(ns or "").startswith("file:") else ns,
        "classes": classes[:MAX_ELEMENTS],
        "object_properties": obj_props[:MAX_ELEMENTS],
        "datatype_properties": data_props[:MAX_ELEMENTS],
    }


def extract_owlxml(owl_path: Path) -> dict:
    """Minimaler Leser fuer OWL/XML (von rdflib nicht unterstuetzt)."""
    root = ET.parse(owl_path).getroot()
    q = lambda tag: "{http://www.w3.org/2002/07/owl#}" + tag
    # abbreviatedIRI hat die Form "prefix:Name" — fuer den lokalen Namen genuegt der Teil nach dem Doppelpunkt.
    iri = lambda el: el.get("IRI") or (el.get("abbreviatedIRI") or "").split(":", 1)[-1]

    decl = {"Class": [], "ObjectProperty": [], "DataProperty": []}
    for d in root.iter(q("Declaration")):
        for kind in decl:
            for el in d.findall(q(kind)):
                if iri(el):
                    decl[kind].append(_local(iri(el)))

    parents, dom, rng = {}, {}, {}
    for ax in root.iter(q("SubClassOf")):
        cs = ax.findall(q("Class"))
        if len(cs) == 2:
            parents.setdefault(_local(iri(cs[0])), _local(iri(cs[1])))
    for tag, target in (("ObjectPropertyDomain", dom), ("ObjectPropertyRange", rng),
                        ("DataPropertyDomain", dom)):
        for ax in root.iter(q(tag)):
            prop = ax.find(q("ObjectProperty"))
            if prop is None:
                prop = ax.find(q("DataProperty"))
            cls = ax.find(q("Class"))
            if prop is not None and cls is not None:
                target.setdefault(_local(iri(prop)), _local(iri(cls)))

    def prop(name):
        e = {"name": name}
        if name in dom: e["domain"] = dom[name]
        if name in rng: e["range"] = rng[name]
        return e

    classes = [{"name": c, **({"parent": parents[c]} if c in parents else {})}
               for c in sorted(set(decl["Class"])) if c]
    return _elements(classes, [prop(p) for p in sorted(set(decl["ObjectProperty"])) if p],
                     [prop(p) for p in sorted(set(decl["DataProperty"])) if p],
                     root.get("ontologyIRI", ""))


def extract_elements(owl_path: Path) -> dict:
    head = owl_path.read_text(encoding="utf-8", errors="replace")[:4000]
    if "ontologyIRI=" in head:
        try:
            return extract_owlxml(owl_path)
        except Exception:
            return {}

    g = Graph()
    for fmt in ("xml", "turtle"):
        try:
            g.parse(owl_path, format=fmt)
            break
        except Exception:
            g = Graph()
    if not len(g):
        return {}

    onto = g.value(predicate=RDF.type, object=OWL.Ontology)
    # rdflib folgt owl:imports nicht — alles im Graph ist in dieser Datei deklariert.
    # Nur Vokabular-Bausteine (owl:Thing, rdfs:Literal, …) ausblenden.
    builtin = (str(OWL), str(RDF), str(RDFS), "http://www.w3.org/2001/XMLSchema#")
    own = lambda u: isinstance(u, URIRef) and not str(u).startswith(builtin)

    classes, obj_props, data_props = [], [], []
    for c in sorted(set(g.subjects(RDF.type, OWL.Class)), key=str):
        if own(c):
            parent = next((p for p in g.objects(c, RDFS.subClassOf) if own(p)), None)
            classes.append({"name": _local(c), **({"parent": _local(parent)} if parent else {})})
    for pt, bucket in ((OWL.ObjectProperty, obj_props), (OWL.DatatypeProperty, data_props)):
        for p in sorted(set(g.subjects(RDF.type, pt)), key=str):
            if own(p):
                d, r = g.value(p, RDFS.domain), g.value(p, RDFS.range)
                entry = {"name": _local(p)}
                if isinstance(d, URIRef):
                    entry["domain"] = _local(d)
                if isinstance(r, URIRef):
                    entry["range"] = _local(r)
                bucket.append(entry)
    return _elements(classes, obj_props, data_props, str(onto) if onto else "")


def owl_candidates(pattern_dir: Path) -> list:
    files = [f for f in list(pattern_dir.glob("*.owl")) + list(pattern_dir.glob("*.ttl"))
             if f.name.lower() not in SUPPORT_FILES and not re.match(r"(ex\d*|.*example.*)\.", f.name, re.I)]
    # Bevorzugt die Datei, deren Name dem Verzeichnis am naechsten kommt.
    key = re.sub(r"[^a-z]", "", pattern_dir.name.lower())
    files.sort(key=lambda f: (re.sub(r"[^a-z]", "", f.stem.lower()) != key,
                              key not in re.sub(r"[^a-z]", "", f.stem.lower()), f.name))
    return files


def _git(repo: Path, *args) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def build(repo: Path) -> dict:
    # Branch aus dem Clone lesen statt raten (das Repository nutzt "master").
    branch, commit = _git(repo, "rev-parse", "--abbrev-ref", "HEAD"), _git(repo, "rev-parse", "HEAD")
    tree_url = REPO_URL + "/tree/" + branch + "/"
    blob_url = REPO_URL + "/blob/" + branch + "/"
    # Die OWL-Datei landet als OPLa-Provenienz im Export: auf den Commit pinnen, damit der Link
    # auf genau die Version zeigt, deren Struktur verwendet wurde.
    pinned_url = REPO_URL + "/blob/" + commit + "/"
    patterns, seen = [], {}  # Struktur-Fingerprint -> Index in patterns
    for d in sorted(p for p in repo.iterdir() if p.is_dir()):
        if d.name.startswith(".") or d.name in SKIP_DIRS or d.name.startswith(SKIP_PREFIXES):
            continue
        # Erste Datei, die tatsaechlich Elemente liefert — manche Ordner enthalten leere
        # oder kaputte Dateien (z.B. gespeicherte HTML-Seiten) neben der eigentlichen.
        owl, elements = None, {}
        for f in owl_candidates(d):
            elements = extract_elements(f)
            if elements.get("classes") or elements.get("object_properties"):
                owl = f
                break
        if not owl:
            continue  # Ohne Formalisierung taugt das Pattern nicht als Modul-Template.
        md = next((m for m in sorted(d.glob("*.md")) if m.name != "index.md"), None)
        meta = parse_metadata(md) if md else {}
        # Das Repository enthaelt einige Patterns doppelt unter verschiedenen Ordnernamen
        # (z.B. "Airline" und "Airline.owl"). Gleiche Struktur allein reicht nicht: duenne
        # Patterns wie Topic/SimpleTopic haben identische Elemente, aber verschiedene Intents.
        intent = meta.get("Intent", "")
        fingerprint = (tuple(c["name"] for c in elements["classes"]),
                       tuple(p["name"] for p in elements["object_properties"]),
                       tuple(p["name"] for p in elements["datatype_properties"]))
        dup_of = seen.get(fingerprint)
        if dup_of is not None:
            other = patterns[dup_of]["intent"]
            same = re.sub(r"\W", "", intent.lower()) == re.sub(r"\W", "", other.lower())
            if same or not intent:
                continue
            if not other:
                patterns[dup_of] = None  # Kopie ohne Beschreibung durch diese ersetzen
        diagram = next((i for ext in ("png", "jpg", "jpeg", "gif", "svg")
                        for i in sorted(d.glob("*." + ext)) if not re.match(r"\d+px-", i.name)), None)
        seen[fingerprint] = len(patterns)
        patterns.append({
            "id": d.name,
            "name": meta.get("Name") or d.name,
            "intent": meta.get("Intent", ""),
            "domains": meta.get("Domains", ""),
            "competency_questions": meta.get("Competency Questions", ""),
            "solution": meta.get("Solution description", ""),
            "consequences": meta.get("Consequences", ""),
            "specialization_of": meta.get("Specialization Of", ""),
            "url": tree_url + quote(d.name),
            "owl_url": pinned_url + quote(d.name) + "/" + quote(owl.name),
            "diagram_url": (blob_url + quote(d.name) + "/" + quote(diagram.name) + "?raw=true") if diagram else "",
            **elements,
        })

    patterns = [p for p in patterns if p]
    return {"source": REPO_URL, "branch": branch, "commit": commit, "count": len(patterns), "patterns": patterns}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python tools/build_pattern_catalog.py <path-to-cloned-patterns-repository>")
    catalog = build(Path(sys.argv[1]))
    out = Path(__file__).resolve().parent.parent / "patterns_catalog.json"
    out.write_text(json.dumps(catalog, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {catalog['count']} patterns to {out}")
