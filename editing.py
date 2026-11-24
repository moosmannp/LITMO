"""Aenderungen per Edit-Operationen, Provenienz-Schutz, OOPS!-Pruefung und Turtle-Korrektur."""

import xml.etree.ElementTree as ET, json, requests, time
from fastapi import HTTPException
from ontology_edits import apply_edits, focus_modules, integrity_issues, ontology_listing, sanitize_names

import llm
from llm import parse_llm_json, usage_step
from project import apply_conventions, context_block, label_languages, MOMO_METHOD
from ontology_io import ontology_to_turtle, validate_turtle
from corpus import concept_key, doc_citation, _match_text, _plain
from vocabularies import known_prefixes, session_vocab

# ── OOPS! ──────────────────────────────────────────────────────────────────────
OOPS_URL = "https://oops.linkeddata.es/rest"
# Ist der Dienst nicht erreichbar (VA-Laeufe 1-3: keine Verbindung zu oops.linkeddata.es), soll nicht jeder Aufruf
# 60 s warten: kurze Frist fuer den Verbindungsaufbau, laengere fuer die Antwort, und nach einem Verbindungsfehler
# einige Minuten lang kein neuer Versuch (DECISIONS 113).
OOPS_CONNECT_TIMEOUT = 10
OOPS_READ_TIMEOUT = 120
OOPS_RETRY_AFTER = 600
OOPS_ERROR_CODES = ("TIMEOUT", "ERROR", "UNREACHABLE")
_oops_down_until = 0.0

def turtle_to_rdfxml(turtle):
    """OOPS! erwartet RDF/XML. Nicht parsebares Turtle wird nicht als 'XML' weitergereicht."""
    from rdflib import Graph
    g = Graph()
    g.parse(data=turtle, format="turtle")
    return g.serialize(format="xml")

def _oops_error(code, description):
    return {"code": code, "name": "OOPS! " + {"TIMEOUT": "timeout", "UNREACHABLE": "unreachable"}.get(code, "error"),
            "description": description, "importance": "minor", "count": 0, "affected": []}

def _unreachable(detail="") -> dict:
    return _oops_error("UNREACHABLE", "The OOPS! service (oops.linkeddata.es) cannot be reached - it is down or "
                                      "blocked by your network" + (f" ({detail})" if detail else "") +
                       ". The ontology was not checked for pitfalls.")

def check_oops(turtle):
    global _oops_down_until
    if time.time() < _oops_down_until:
        return [_unreachable(f"no connection a few minutes ago; next attempt after "
                             f"{time.strftime('%H:%M', time.localtime(_oops_down_until))}")]
    try:
        rdf_content = turtle_to_rdfxml(turtle)
    except Exception as ex:
        return [_oops_error("ERROR", "Ontology could not be converted to RDF/XML for OOPS!: " + str(ex)[:200])]
    xml_body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<OOPSRequest>\n'
        '  <OntologyURI></OntologyURI>\n'
        '  <OntologyContent><![CDATA[' + rdf_content + ']]></OntologyContent>\n'
        '  <Pitfalls></Pitfalls>\n'
        '  <OutputFormat>XML</OutputFormat>\n'
        '</OOPSRequest>'
    )
    try:
        resp = requests.post(OOPS_URL, data=xml_body.encode("utf-8"), headers={"Content-Type": "application/xml"},
                             timeout=(OOPS_CONNECT_TIMEOUT, OOPS_READ_TIMEOUT))
        resp.raise_for_status()
        return parse_oops_xml(resp.text)
    except (requests.ConnectTimeout, requests.ConnectionError) as ex:   # ConnectTimeout vor Timeout pruefen
        _oops_down_until = time.time() + OOPS_RETRY_AFTER
        return [_unreachable(type(ex).__name__)]
    except requests.Timeout:
        return [_oops_error("TIMEOUT", f"The OOPS! service accepted the ontology but did not answer within "
                                       f"{OOPS_READ_TIMEOUT} s.")]
    except Exception as ex:
        return [_oops_error("ERROR", "OOPS! request failed: " + str(ex)[:200])]

def _local_tag(el) -> str:
    return el.tag.rsplit("}", 1)[-1].lower()

def parse_oops_xml(xml_text):
    """Liest die OOPS!-Antwort, z.B.:
    <oops:OOPSResponse><oops:Pitfall><oops:Code>P10</oops:Code><oops:Name>…</oops:Name>
      <oops:Description>…</oops:Description><oops:Importance>Important</oops:Importance>
      <oops:NumberAffectedElements>3</oops:NumberAffectedElements>
      <oops:Affects><oops:AffectedElement>http://…</oops:AffectedElement>…</oops:Affects></oops:Pitfall>
    Tag-Namen werden ohne Namespace und ohne Gross-/Kleinschreibung verglichen, da die Antwort
    'Pitfall', 'Code', 'Importance' grossschreibt."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as ex:
        # Nie still eine leere Liste liefern — das sähe aus wie "keine Pitfalls".
        return [_oops_error("ERROR", "OOPS! returned an unreadable response: " + str(ex)[:150])]
    if _local_tag(root) != "oopsresponse":
        return [_oops_error("ERROR", "OOPS! returned an unexpected response (" + _local_tag(root) + ").")]

    pitfalls = []
    for pf in (el for el in root.iter() if _local_tag(el) == "pitfall"):
        fields = {}
        for child in pf:  # nur direkte Kinder; AffectedElement liegt tiefer
            fields.setdefault(_local_tag(child), (child.text or "").strip())
        affected = [(e.text or "").strip() for e in pf.iter() if _local_tag(e) == "affectedelement" and e.text]
        try:
            count = int(fields.get("numberaffectedelements") or 0)
        except ValueError:
            count = 0
        pitfalls.append({
            "code": fields.get("code") or "?",
            "name": fields.get("name") or "Unknown pitfall",
            "description": fields.get("description", ""),
            # OOPS! liefert "Critical"/"Important"/"Minor".
            "importance": (fields.get("importance") or "minor").lower(),
            "count": max(count, len(affected)),
            "affected": affected[:10],
        })
    return pitfalls

def format_pitfalls_for_llm(pitfalls):
    lines = []
    for p in pitfalls:
        lines.append(f"[{p['code']}] {p['name']} (importance: {p['importance']})")
        if p.get("description"):
            lines.append(f"  {p['description']}")
        if p.get("affected"):
            lines.append(f"  Affected: {', '.join(p['affected'])}")
        lines.append("")
    return "\n".join(lines)

# OOPS!-Pitfall-Katalog (https://oops.linkeddata.es/catalogue.jsp). Schon bei der Generierung vermeiden, statt
# erst nachtraeglich zu reparieren. Pitfalls, die das JSON-Format nicht ausdruecken kann (z.B. P14-P16,
# owl:allValuesFrom, Property Chains) oder die die Publikation betreffen (P37), fehlen bewusst.
OOPS_GUIDANCE = (
    "Avoid the pitfalls of the OOPS! catalogue (https://oops.linkeddata.es/catalogue.jsp):\n"
    "- P01/P07: one meaning per term — no polysemous names, no merged classes like 'StyleAndPeriod'.\n"
    "- P02/P30/P31/P12: no separate classes or properties for synonyms; declare EquivalentClasses only for truly "
    "identical meanings.\n"
    "- P03: never model 'is'/'isA' as a property — use the class hierarchy (parent) or individuals.\n"
    "- P04: no unconnected elements — every class and property is linked to the rest of the ontology.\n"
    "- P05/P25/P26: an inverse_of must really invert the property, never a property inverse to itself, none for "
    "symmetric properties. Declare an inverse only where a competency question or the data need both directions "
    "(a query can follow a property backwards; the missing inverse, OOPS! P13, is a minor pitfall).\n"
    "- P06/P24: no cycles in the class hierarchy and no class defined in terms of itself.\n"
    "- P08/P20: every class and property has a label and a description; labels name, descriptions explain.\n"
    "- P09/P11: every property has exactly one domain and one range (P19: never several), as general as the use "
    "case allows (P18: do not overspecialize them).\n"
    "- P10: declare DisjointClasses for sibling classes that cannot share instances.\n"
    "- P17: do not create subclasses that would better be individuals.\n"
    "- P21: no miscellaneous classes such as 'Other' or 'Misc'.\n"
    "- P22: one naming convention throughout.\n"
    "- P23: use xsd datatypes as ranges; never create classes like 'String' or 'Date'.\n"
    "- P32: no two classes with the same label.\n"
    "- P34/P35: every class or property you reference is declared, or reused with its standard prefix.\n"
    "- P36/P39: the namespace ends with '#' or '/' and contains no file extension.\n"
    "- P40: never invent new terms inside a reused vocabulary's namespace — only use terms that exist there.\n"
    "- P41: declare a license.\n"
)

# ── Aenderungen per Edit-Operationen ───────────────────────────────────────────
# Feedback, OOPS!-Korrekturen und Syntaxkorrekturen schreiben die Ontologie nicht mehr komplett neu (bei einer
# Ontologie mit ~250 Klassen waeren das 25.000-30.000 Ausgabe-Tokens je Aufruf, mehr als das Limit von
# OpenAI-kompatiblen Anbietern, und das Modell koennte unbeteiligte Teile wie Quellen und Links verlieren).
# Das Modell liefert nur Operationen (ontology_edits.py); der Server wendet sie deterministisch an, benennt
# bei Umbenennungen alle Verweise um und lehnt Operationen ab, die die Ontologie beschaedigen wuerden.
EDIT_OPS = (
    "Operations - each is an object with an \"op\" field; omit fields you do not change:\n"
    '- {"op":"add_class","name":"X","labels":{"<lang>":"label"},"description":"...","parent":"Y or null","module":"M",'
    '"sources":["citation"],"see_also":["uri"]}\n'
    '- {"op":"update_class","name":"X","labels":{...},"description":"...","parent":"Y or null","module":"M","sources":[...],'
    '"see_also":[...],"new_name":"Z"}   (labels are merged per language; sources and see_also are replaced)\n'
    '  add_class and update_class also take "inventory_concepts":["concept label"] - links to concepts of the literature '
    "inventory that the class represents (added, never replaced; only when a request names the concepts)\n"
    '- {"op":"rename_class","name":"X","new_name":"Z"}   (all references are updated)\n'
    '- {"op":"remove_class","name":"X","replace_with":"Y"}   (subclasses move up; replace_with takes over domain/range/'
    "individuals if X is still used)\n"
    '- {"op":"add_property","name":"p","type":"ObjectProperty|DatatypeProperty","domain":"X","range":"Y or xsd:string",'
    '"inverse_of":"q","labels":{...},"description":"...","module":"M"}\n'
    '- {"op":"update_property","name":"p","type":"ObjectProperty|DatatypeProperty","domain":"X","range":"Y",'
    '"inverse_of":"q or null","labels":{...},"description":"...","module":"M","new_name":"r"}   (an inverse is linked '
    "in both directions; when changing the type, give the new range too)\n"
    '  add_property and update_property also take "sub_property_of":"q or null" (its domain and range must lie within '
    'those of q) and "characteristics":["functional","inverse_functional","transitive","symmetric","asymmetric"] '
    "(a DatatypeProperty can only be functional; a transitive property cannot also be functional or asymmetric)\n"
    '- {"op":"rename_property","name":"p","new_name":"r"}   {"op":"remove_property","name":"p"}\n'
    '- {"op":"merge_property","name":"p","into":"q"}   (p disappears, every reference points to q; the inverse of p '
    "is merged into the inverse of q)\n"
    '- {"op":"add_individual","name":"i","class":"X","labels":{...}}   {"op":"update_individual","name":"i","class":"X",'
    '"labels":{...}}   {"op":"remove_individual","name":"i"}\n'
    '- {"op":"add_axiom","type":"DisjointClasses|EquivalentClasses|SubClassOf","classes":["A","B"],"module":"M",'
    '"scoped":true|false,"natural_language":"plain English reading"}   {"op":"remove_axiom","type":"...","classes":["A","B"]}\n'
    '- {"op":"add_restriction","class":"X","property":"p","kind":"some|only|min|max|exactly","value":"Y or xsd:...",'
    '"n":1,"natural_language":"..."}   (X SubClassOf p some Y: every X has a p to some Y; only: all its p values are Y; '
    "min/max/exactly need n. X must lie within the domain of p and Y within its range)   "
    '{"op":"remove_restriction","class":"X","property":"p","kind":"...","value":"Y"}\n'
    '- {"op":"add_module","name":"M","key_notion":"...","pattern":"PatternID or null","documentation":"..."}   '
    '{"op":"update_module","name":"M","documentation":"...","pattern":"...","key_notion":"...","new_name":"N"}   '
    '{"op":"remove_module","name":"M","move_to":"N"}\n'
    '- {"op":"update_ontology","ontology_name":"...","summary":"...","license":"uri"}\n'
)

EDIT_SYS = (MOMO_METHOD + "\nYou maintain an existing modular OWL ontology. You receive a compact listing of it and "
            "a request: team feedback, findings of a quality check, or a syntax error. Do NOT rewrite the ontology. "
            "Answer with the OPERATIONS that make exactly the requested change; the server applies them.\n"
            "Rules:\n"
            "1. Use the exact names from the listing for classes, properties, individuals and modules. Prefixed "
            "names (schema:Person) refer to reused vocabularies.\n"
            "2. Change only what the request needs - the smallest set of operations wins. Everything you do not "
            "mention stays exactly as it is, including the sources and see_also of every class. Never rename or "
            "restructure what the request does not touch.\n"
            "3. List operations in a sensible order (a parent before its subclasses). An operation that the server "
            "rejects is reported back to you once so you can correct it.\n"
            "4. New classes: UpperCamelCase, singular and specific; new properties: lowerCamelCase, directional and "
            "verb-based. Give every new class, property and individual a label for EACH language listed under "
            "'Label languages' in the project conventions and a description in the first of those languages. Put new "
            "elements into the module they belong to.\n"
            "5. Never invent sources or see_also URIs: the server keeps only citations and URIs that already occur in "
            "the ontology, come from the literature corpus, or are given in the request.\n"
            + OOPS_GUIDANCE + EDIT_OPS +
            'Answer ONLY as JSON: {"summary":"one or two sentences: what you changed and why","ops":[...]}. '
            'If nothing needs to change, return an empty "ops" list and explain why in "summary".')

MAX_FEEDBACK_LOG = 8

def build_edit_prompt(session, onto, request, focus_text="", context=None):
    lang = label_languages(session)[0]
    parts = ["**Current ontology:**\n" + ontology_listing(onto, focus_modules(onto, focus_text), lang)]
    ctx = context_block(session) if context is None else context
    if ctx:
        parts.append(ctx)
    log = [e for e in session.get("feedback_log") or [] if isinstance(e, dict) and e.get("feedback")][-MAX_FEEDBACK_LOG:]
    if log:
        parts.append("**Earlier change requests of the team (already applied - do not undo them):**\n" +
                     "\n".join("- " + _plain(e["feedback"], 300) for e in log))
    parts.append("**Request:**\n" + request)
    return [{"role": "system", "content": EDIT_SYS}, {"role": "user", "content": "\n\n".join(parts)}]

def _ops_from(raw) -> tuple:
    result = parse_llm_json(raw)
    ops = result.get("ops") if isinstance(result, dict) else None
    if ops is None and isinstance(result, dict) and (result.get("summary") or result.get("skipped")):
        ops = []          # "nothing fits" without an ops field is a valid answer: change nothing (DECISIONS 80)
    if not isinstance(ops, list):
        raise ValueError("the model's answer contains no list of operations")
    skipped = [{"item": _plain(x.get("concept") or x.get("item"), 200), "reason": _plain(x.get("reason"), 300)}
               for x in result.get("skipped") or [] if isinstance(x, dict) and (x.get("concept") or x.get("item"))]
    return ops, _plain(result.get("summary"), 600), skipped

def _describe_op(op) -> str:
    if not isinstance(op, dict):
        return str(op)[:120]
    return f"{op.get('op')} {op.get('name') or ''}".strip() + (f" ({op.get('type')})" if op.get("type") and not op.get("name") else "")

def guard_provenance(old, new, session, request) -> list:
    """Sources and see_also URIs the model added must already occur in the ontology, come from the literature corpus
    or be named in the request - an invented citation would look exactly like a real one. Returns what was dropped."""
    corpus = session.get("corpus") or {}
    allowed_src = {doc_citation(d) for d in corpus.get("docs") or []}
    allowed_uri = {s["uri"] for c in ((corpus.get("inventory") or {}).get("concepts") or [])
                   for s in c.get("sources") or [] if s.get("uri")}
    for c in old.get("classes") or []:
        allowed_src |= set(c.get("sources") or [])
        allowed_uri |= set(c.get("see_also") or [])
    req_text = _match_text(request)
    dropped = []
    # Links to inventory concepts: only real concepts, written as their label (coverage matches on it)
    label_of = {}
    for c in ((corpus.get("inventory") or {}).get("concepts") or []):
        for v in [c["label"], *c.get("variants", [])]:
            label_of.setdefault(concept_key(v), c["label"])
    old_links = {c.get("name"): set(c.get("inventory_concepts") or []) for c in old.get("classes") or []}
    for c in new.get("classes") or []:
        if c.get("inventory_concepts"):
            had = old_links.get(c.get("name"), set())
            links = [x if x in had else label_of.get(concept_key(x)) for x in c["inventory_concepts"]]
            dropped += [f"{c.get('name')}: inventory concept '{x}'" for x, l in zip(c["inventory_concepts"], links) if not l]
            c["inventory_concepts"] = list(dict.fromkeys(l for l in links if l))
            if not c["inventory_concepts"]:
                del c["inventory_concepts"]
    for c in new.get("classes") or []:
        if c.get("sources"):
            keep = [s for s in c["sources"] if s in allowed_src or (len(_match_text(s)) > 8 and _match_text(s) in req_text)]
            dropped += [f"{c.get('name')}: source '{s}'" for s in c["sources"] if s not in keep]
            c["sources"] = keep
        if c.get("see_also"):
            keep = [u for u in c["see_also"] if u in allowed_uri or u in request]
            dropped += [f"{c.get('name')}: see_also <{u}>" for u in c["see_also"] if u not in keep]
            c["see_also"] = keep
    return dropped

def edit_ontology(session, llm_config, onto, request, step, focus_text=None):
    """Lets the model describe the change as operations and applies them. Returns (new ontology, report) with
    report = {summary, operations, applied, rejected, new_issues, dropped_provenance}. Rejected operations go back to
    the model once."""
    lang = label_languages(session)[0]
    prefixes = known_prefixes(session)
    messages = build_edit_prompt(session, onto, request, focus_text if focus_text is not None else request)
    with usage_step(step):
        raw = llm.json_text(llm_config, llm.call_llm(llm_config, messages))   # kaputtes JSON reparieren (DECISIONS 108)
    ops, summary, skipped = _ops_from(raw)
    vocab = session_vocab(session)
    new, report = apply_edits(onto, ops, lang, prefixes, vocab)
    report.update({"summary": summary, "operations": len(ops), "skipped": skipped})
    if report["rejected"]:
        lines = "\n".join(f"- {json.dumps(r['op'], ensure_ascii=False)[:300]}\n  reason: {r['reason']}" for r in report["rejected"][:20])
        retry = messages + [{"role": "assistant", "content": raw},
                            {"role": "user", "content": "The server could not apply these operations:\n" + lines +
                             "\n\nAnswer with corrected operations for exactly these (same JSON format; an empty list "
                             "if they are no longer needed)."}]
        try:
            with usage_step(step + " (corrections)"):
                ops2, _, _ = _ops_from(llm.json_text(llm_config, llm.call_llm(llm_config, retry)))
            new2, report2 = apply_edits(new, ops2, lang, prefixes, vocab)
            new = new2
            report["applied"] += report2["applied"]
            report["merged"] = {**report.get("merged", {}), **report2.get("merged", {})}
            report["merge_records"] = report.get("merge_records", []) + report2.get("merge_records", [])
            report["rejected"] = report2["rejected"] + ([] if ops2 else report["rejected"])
        except Exception as ex:  # die Korrekturrunde ist ein Zusatz - das erste Ergebnis bleibt gueltig
            report["correction_error"] = f"{type(ex).__name__}: {str(ex)[:150]}"
    report["dropped_provenance"] = guard_provenance(onto, new, session, request)
    # was eine Zusammenfuehrung an Klassenpaaren aufgibt: Kandidaten fuer Klassenrestriktionen (DECISIONS 125)
    session["merge_records"] = ((session.get("merge_records") or []) + report.get("merge_records", []))[-2000:]
    report["new_issues"] = [i for i in integrity_issues(new) if i not in set(integrity_issues(onto))]
    for r in report["rejected"]:
        r["op"] = _describe_op(r["op"])
    return new, report

def edit_error(report) -> HTTPException:
    reasons = "; ".join(f"{r['op']}: {r['reason']}" for r in report["rejected"][:5])
    return HTTPException(status_code=422, detail=f"None of the model's {report['operations']} changes could be "
                                                 f"applied ({reasons}). The ontology is unchanged.")

# Kritische und wichtige Pitfalls werden automatisch behoben, "minor" nur berichtet.
AUTO_FIX_IMPORTANCE = ("critical", "important")

def run_oops_and_fix(turtle, onto, session, llm_config, standards=None, custom_prefixes=None):
    pitfalls = check_oops(turtle)
    real = [p for p in pitfalls if p["code"] not in OOPS_ERROR_CODES]
    report = {"pitfalls": pitfalls, "total": len(real), "fix_applied": False}
    to_fix = [p for p in real if p["importance"] in AUTO_FIX_IMPORTANCE]
    if not to_fix or not llm_config:
        return None, turtle, report

    request = ("The OOPS! ontology pitfall scanner found these critical and important problems:\n\n" +
               format_pitfalls_for_llm(to_fix) +
               "\nFix exactly these problems with the smallest set of operations and change nothing else. Keep the "
               "module structure and keep existing scoped axioms.")
    try:
        onto_fixed, edit = edit_ontology(session, llm_config, onto, request, "OOPS! fix")
        if not edit["applied"]:
            report["fix_error"] = "The model proposed no applicable change" + \
                (": " + "; ".join(r["reason"] for r in edit["rejected"][:3]) if edit["rejected"] else ".")
            return None, turtle, report
        apply_conventions(onto_fixed, session)
        turtle_fixed = ontology_to_turtle(onto_fixed, standards, custom_prefixes)
    except Exception as ex:
        report["fix_error"] = type(ex).__name__ + ": " + str(ex)[:200]
        return None, turtle, report
    valid, error = validate_turtle(turtle_fixed)
    if not valid:
        # Eine "Korrektur", die ungueltiges Turtle erzeugt, ist schlechter als das Original.
        report["fix_error"] = "The corrected ontology was not valid Turtle and was discarded: " + error[:200]
        return None, turtle, report

    # Erneut pruefen, damit der Bericht den Stand NACH der Korrektur zeigt.
    after = check_oops(turtle_fixed)
    after_real = [p for p in after if p["code"] not in OOPS_ERROR_CODES]
    fixed_codes = {p["code"] for p in to_fix} - {p["code"] for p in after_real}
    report.update({
        "pitfalls": after,
        "total": len(after_real),
        "fix_applied": True,
        "fixed": [{"code": p["code"], "name": p["name"]} for p in to_fix if p["code"] in fixed_codes],
        "fixed_count": len(fixed_codes),
        "still_unfixed": len([p for p in after_real if p["importance"] in AUTO_FIX_IMPORTANCE]),
        "fix_changes": [a["summary"] for a in edit["applied"]],
        "fix_rejected": len(edit["rejected"]),
    })
    return onto_fixed, turtle_fixed, report

def validate_and_fix_turtle(turtle_str, onto, session, llm_config, standards=None, custom_prefixes=None):
    """Validiert Turtle. Syntaxfehler kommen praktisch nur von ungueltigen Bezeichnern; die werden zuerst ohne
    LLM umbenannt, erst danach bekommt das Modell den Fehler zu sehen (als Edit-Operationen)."""
    valid, error = validate_turtle(turtle_str)
    report = {"valid": valid, "error": error, "fixed": False}
    if valid:
        return onto, turtle_str, report

    lang = label_languages(session)[0]
    onto2, renames = sanitize_names(onto, lang)
    if renames:
        report["renamed"] = renames[:30]
        turtle2 = ontology_to_turtle(onto2, standards, custom_prefixes)
        valid2, error2 = validate_turtle(turtle2)
        if valid2:
            report.update({"valid": True, "error": "", "fixed": True})
            return onto2, turtle2, report
        onto, turtle_str, error = onto2, turtle2, error2
        report["error"] = error2

    if llm_config:
        request = ("The Turtle serialization of the ontology has a syntax error:\n\n" + error[:600] +
                   "\n\nFind the class, property or individual names or values that cause it and correct them with "
                   "operations (valid local names: letters, digits, _ and - only).")
        try:
            onto_fixed, edit = edit_ontology(session, llm_config, onto, request, "Turtle syntax fix")
            if edit["applied"]:
                apply_conventions(onto_fixed, session)
                turtle_fixed = ontology_to_turtle(onto_fixed, standards, custom_prefixes)
                valid3, error3 = validate_turtle(turtle_fixed)
                report.update({"fixed": True, "valid": valid3, "error": error3 if not valid3 else ""})
                return onto_fixed, turtle_fixed, report
        except Exception as ex:
            report["fix_error"] = str(ex)

    return onto, turtle_str, report
