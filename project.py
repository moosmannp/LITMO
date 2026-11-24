"""Projektkontext, Konventionen und der ODP-Katalog - was alle Schritte ueber das Projekt wissen."""

import json, re, unicodedata
from pathlib import Path

# ── ODP-Katalog (MOMo Schritt 4) ───────────────────────────────────────────────
# Erzeugt von tools/build_pattern_catalog.py aus https://github.com/odpa/patterns-repository

try:
    PATTERN_CATALOG = json.loads(Path(__file__).with_name("patterns_catalog.json").read_text(encoding="utf-8"))
except (OSError, ValueError):
    print("WARNUNG: patterns_catalog.json fehlt oder ist ungueltig — Pattern-Vorschlaege ohne Katalog.")
    PATTERN_CATALOG = {"source": "", "commit": "", "patterns": []}

def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())

_PATTERNS_BY_ID = {p["id"]: p for p in PATTERN_CATALOG["patterns"]}
_PATTERNS_BY_NORM = {}
for _p in PATTERN_CATALOG["patterns"]:
    _PATTERNS_BY_NORM.setdefault(_norm(_p["id"]), _p)
    _PATTERNS_BY_NORM.setdefault(_norm(_p["name"]), _p)

def find_pattern(ref):
    """Loest einen Pattern-Namen (exakte ID oder tolerante Schreibweise) im Katalog auf."""
    if not ref:
        return None
    return _PATTERNS_BY_ID.get(ref) or _PATTERNS_BY_NORM.get(_norm(ref))

def pattern_template_text(pat) -> str:
    """Kompakte Strukturbeschreibung eines Patterns als Modul-Template fuer den Prompt."""
    cls = ", ".join(c["name"] + (" subClassOf " + c["parent"] if c.get("parent") else "")
                    for c in pat.get("classes", []))
    props = ", ".join(p["name"] + (" (" + p.get("domain", "?") + " -> " + p.get("range", "?") + ")"
                                   if p.get("domain") or p.get("range") else "")
                      for p in pat.get("object_properties", []) + pat.get("datatype_properties", []))
    return ("    intent: " + (pat.get("intent") or "-") +
            "\n    classes: " + (cls or "-") + "\n    properties: " + (props or "-"))

def _catalog_listing() -> str:
    lines = []
    for p in PATTERN_CATALOG["patterns"]:
        desc = (p.get("intent") or p.get("solution") or "")[:110]
        if not desc:
            desc = "elements: " + ", ".join(c["name"] for c in p.get("classes", [])[:6])
        lines.append("- " + p["id"] + ": " + desc)
    return "\n".join(lines)

# ── MOMo Prompts ───────────────────────────────────────────────────────────────
MOMO_METHOD = (
    "You follow the MOMo (Modular Ontology Modeling) methodology: the ontology is built "
    "conceptually first (use cases, competency questions, key notions, design patterns, "
    "module schema diagrams) and the OWL file is only the final translation. Ontologies "
    "should be modular, extensible and reusable rather than one-off."
)

MAX_CQS = 10

def _cq_text(cq) -> str:
    return (cq.get("question", "") if isinstance(cq, dict) else str(cq)).strip()

# ── Projektkontext ─────────────────────────────────────────────────────────────
# Ein vom Team bestaetigtes Dokument mit Zweck, Scope, Glossar, Domaenenregeln, Datenquellen, Wiederverwendung
# und getroffenen Entscheidungen, plus Konventionen aus einem Formular. Es geht an JEDEN Prompt, damit spaetere
# Schritte die Entscheidungen des Teams kennen, statt sie zu raten.
DEFAULT_CONVENTIONS = {"namespace": "", "prefix": "", "label_languages": "en", "license": "", "owl_profile": "OWL 2 DL"}
CONTEXT_SOURCE_LIMIT = 120_000  # Zeichen einer hochgeladenen Kontextdatei (die Datenvorschau ist viel knapper)


def _context(session) -> dict:
    ctx = session.setdefault("context", {})
    ctx.setdefault("markdown", "")
    ctx.setdefault("questions", [])
    ctx.setdefault("source_name", "")
    ctx.setdefault("source_text", "")
    ctx["conventions"] = {**DEFAULT_CONVENTIONS, **(ctx.get("conventions") or {})}
    return ctx

def label_languages(session) -> list:
    raw = (session.get("context") or {}).get("conventions", {}).get("label_languages") or "en"
    langs = [l.strip().lower() for l in re.split(r"[,;\s]+", raw) if re.match(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]+)*$", l.strip())]
    return langs or ["en"]

def decided_definitions(session) -> list:
    """Die vom Team entschiedenen Definitionen (DECISIONS 83) als [(Begriff, Entscheidung)], ohne offen gelassene."""
    entries = ((session.get("context") or {}).get("definition_decisions") or {}).values()
    return [(e["concept"], e["decision"]) for e in entries if (e.get("decision") or {}).get("parts")]

def _ctx(context: str) -> str:
    return ("\n\n" + context) if context else ""

def context_block(session) -> str:
    """Projektkontext und Konventionen als Prompt-Abschnitt."""
    ctx = session.get("context") or {}
    conv = {**DEFAULT_CONVENTIONS, **(ctx.get("conventions") or {})}
    parts = []
    md = (ctx.get("markdown") or "").strip()
    if md:
        parts.append("**Project context (agreed by the team - it overrides your defaults; items marked [confirm] "
                     "are unconfirmed assumptions):**\n" + md)
    decided = decided_definitions(session)
    if decided:
        lines = []
        for concept, d in decided:
            if len(d["parts"]) == 1:
                lines.append(f"- {concept} -> class {d['parts'][0]['name']}: {d['parts'][0]['definition']}")
            else:
                lines.append(f"- {concept} -> split into {len(d['parts'])} classes: " +
                             "; ".join(f"{p['name']}: {p['definition']}" for p in d["parts"]))
        parts.append("**Decided definitions** (the team resolved these conflicts between the sources; they take "
                     "precedence over the glossary and over the sources. Each named class has exactly this definition "
                     "as its description - use it word for word):\n" + "\n".join(lines))
    langs = label_languages(session)
    lines = [f"- Label languages: {', '.join(langs)} (descriptions in '{langs[0]}')"]
    if conv["namespace"].strip():
        lines.append(f"- Ontology namespace: {conv['namespace'].strip()}")
    if conv["prefix"].strip():
        lines.append(f"- Ontology prefix: {conv['prefix'].strip()}")
    if conv["license"].strip():
        lines.append(f"- License: {conv['license'].strip()}")
    if conv["owl_profile"].strip():
        lines.append(f"- OWL profile: {conv['owl_profile'].strip()} - use only constructs allowed in it")
    parts.append("**Project conventions:**\n" + "\n".join(lines))
    return "\n\n".join(parts)

def apply_conventions(onto: dict, session) -> dict:
    """Setzt die Formular-Konventionen deterministisch durch, statt sich auf das LLM zu verlassen."""
    conv = {**DEFAULT_CONVENTIONS, **((session.get("context") or {}).get("conventions") or {})}
    ns = conv["namespace"].strip()
    if ns:
        onto["namespace"] = ns if ns.endswith(("#", "/")) else ns + "#"
    if conv["license"].strip():
        onto["license"] = conv["license"].strip()
    onto["description_language"] = label_languages(session)[0]
    return onto

def session_prefixes(session, onto=None) -> dict:
    """Eigene Prefixe der Session plus der Prefix aus den Konventionen fuer den Ontologie-Namespace."""
    prefixes = dict(session.get("custom_prefixes") or {})
    for pfx, voc in (session.get("vocabularies") or {}).items():   # geladene Vokabulare (Schritt 7)
        if voc.get("namespace"):
            prefixes.setdefault(pfx, voc["namespace"])
    conv = (session.get("context") or {}).get("conventions") or {}
    pfx = (conv.get("prefix") or "").strip()
    ns = (onto or session.get("ontology") or {}).get("namespace")
    if pfx and ns and re.match(r"^[A-Za-z][A-Za-z0-9_-]*$", pfx):
        prefixes[pfx] = ns
    return prefixes

# Umlaute umschreiben, andere Akzente ablegen - vorher fielen sie weg (Qualitaetswein -> QualitTswein, Code-Review)
_TRANSLIT = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"})

def nth(seq, item):
    """Das item-te Element (ab 1) aus einer Antwort des Modells, sonst None - "item": 0 waehlte frueher das letzte (F8)."""
    try:
        k = int(item)
    except (TypeError, ValueError):
        return None
    return seq[k - 1] if 1 <= k <= len(seq) else None

def _class_name(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "").translate(_TRANSLIT)).encode("ascii", "ignore").decode()
    words = re.findall(r"[A-Za-z0-9]+", s)
    name = "".join(w[:1].upper() + w[1:] for w in words)
    return name if name and not name[0].isdigit() else ("C" + name if name else "")

# Entscheidungen der Verbesserungsaktionen (DECISIONS 76): je Aktion Schluessel -> {item, reason}. Der Schluessel ist,
# was die Aktion beim naechsten Mal auslaesst (Klassen- oder Property-Name; bei der Hierarchie der normalisierte Text).
DECISION_KEYS = {"hierarchy": "gap_hierarchy_decisions", "upper": "gap_upper_decisions",
                 "properties": "gap_property_decisions", "align": "gap_align_decisions",
                 "restrictions": "gap_restriction_decisions"}

def decision_store(session, kind) -> dict:
    """Die Entscheidungen einer Aktion als dict; aeltere Projekte speicherten nur eine Liste von Schluesseln."""
    key = DECISION_KEYS[kind]
    v = session.get(key)
    if isinstance(v, list):
        v = {x: {"item": x, "reason": ""} for x in v}
    session[key] = v if isinstance(v, dict) else {}
    return session[key]

def relation_key(narrower, broader) -> str:
    """Schluessel einer Hierarchie-Entscheidung, wie ihn "Build hierarchy" speichert ("A is a kind of B", normalisiert)."""
    return _norm(f"{narrower} is a kind of {broader}")

def declined_relations(session):
    """(narrower, broader) -> True, wenn die Beziehung mit Grund abgelehnt wurde - fuer die Evaluation (DECISIONS 111)."""
    store = session.get("gap_hierarchy_decisions") or {}
    check = lambda n, b: relation_key(n, b) in store
    check.keys = set(store)        # auch entschiedene Taxonomien (hierarchy_coverage zaehlt sie nicht mehr als offen)
    return check

def named_notions(notions) -> list:
    """Nur Key Notions mit Namen: eine leere Zeile aus dem Formular ist keine Key Notion."""
    return [n for n in notions or [] if isinstance(n, dict) and str(n.get("name") or "").strip()]

def _momo(session):
    return session.setdefault("momo", {"use_case": "", "data_sources": "", "competency_questions": [],
                                       "key_notions": [], "patterns": []})
