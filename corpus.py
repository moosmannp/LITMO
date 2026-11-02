"""Eingaben: Datendateien des Use Cases, Literatur-Korpus, Paper-Karten und Begriffsinventar."""

import copy, csv, io, re, unicodedata
from datetime import datetime, timezone
from pathlib import Path
from fastapi import HTTPException

import llm
from store import SESSION_DIR
from llm import _usage_log, usage_step, usage_summary
from project import CONTEXT_SOURCE_LIMIT, MOMO_METHOD

# ── File Parsing ───────────────────────────────────────────────────────────────
# Jede hochgeladene Datei wird je nach Art aufbereitet:
#   - Tabellen (CSV, Excel): ein Spaltenprofil ueber ALLE Zeilen und Tabellenblaetter — kompakter und
#     aussagekraeftiger als ein paar Rohzeilen.
#   - Textdokumente (PDF, Markdown, Text): der Volltext. In die Prompts geht nur ein Auszug ("summary");
#     der Volltext fliesst einmal in den Entwurf des Projektkontexts und wird dort verdichtet.
#   - RDF (Turtle, JSON-LD, RDF/XML): eine Uebersicht der Klassen und Properties.
TEXT_EXCERPT_CHARS = 4000        # Auszug eines Textdokuments in der Datenvorschau
MAX_PROFILE_COLUMNS = 60
MAX_PROFILE_ROWS = 200_000       # Obergrenze fuer die Profilierung sehr grosser Tabellen
DATA_TEXT_TOTAL_LIMIT = 300_000  # Volltext aller Dokumente zusammen im Kontext-Entwurf

def _short_val(v, n=40) -> str:
    from datetime import datetime as _dt
    if isinstance(v, _dt) and not (v.hour or v.minute or v.second):
        v = v.date()  # Excel liefert reine Datumswerte als datetime um 00:00
    v = str(v).replace("\n", " ").strip()
    return v if len(v) <= n else v[:n - 1] + "…"

_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2})?)?|\d{1,2}[./]\d{1,2}[./]\d{2,4})$")

def _value_type(v) -> str:
    from datetime import date
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, float):
        return "integer" if v.is_integer() else "decimal"
    if isinstance(v, date):
        return "date"
    t = str(v).strip()
    if t.lower() in ("true", "false", "yes", "no", "ja", "nein"):
        return "boolean"
    if re.match(r"^[+-]?\d+$", t):
        return "integer"
    if re.match(r"^[+-]?(\d+[.,]\d*|[.,]\d+)([eE][+-]?\d+)?$", t):
        return "decimal"
    if _DATE_RE.match(t):
        return "date"
    return "string"

def _num(v):
    try:
        return float(str(v).replace(",", "."))
    except ValueError:
        return None

def profile_table(title: str, header: list, rows) -> str:
    """Spaltenprofil: Typ, Anteil leerer Werte, Wertebereich bzw. haeufigste Werte, plus Beispielzeilen."""
    from collections import Counter
    header = [(_short_val(h, 50) if h not in (None, "") else f"column_{i + 1}") for i, h in enumerate(header)]
    ncols = len(header)
    counters = [Counter() for _ in range(ncols)]
    types = [Counter() for _ in range(ncols)]
    nums = [[None, None] for _ in range(ncols)]
    empty = [0] * ncols
    samples, n = [], 0
    for row in rows:
        row = list(row)
        if not any(c not in (None, "") and str(c).strip() for c in row):
            continue
        n += 1
        if len(samples) < 3:
            samples.append(row)
        for i in range(ncols):
            v = row[i] if i < len(row) else None
            if v is None or not str(v).strip():
                empty[i] += 1
                continue
            t = _value_type(v)
            types[i][t] += 1
            if len(counters[i]) < 5000 or v in counters[i]:
                counters[i][_short_val(v)] += 1
            if t in ("integer", "decimal"):
                x = v if isinstance(v, (int, float)) else _num(v)
                if x is not None:
                    lo, hi = nums[i]
                    nums[i] = [x if lo is None else min(lo, x), x if hi is None else max(hi, x)]
        if n >= MAX_PROFILE_ROWS:
            break
    lines = [f"Table {title}: {n:,} data rows{' (profiled the first ' + format(MAX_PROFILE_ROWS, ',') + ')' if n >= MAX_PROFILE_ROWS else ''}, "
             f"{ncols} columns"]
    for i, name in enumerate(header[:MAX_PROFILE_COLUMNS]):
        filled = n - empty[i]
        if not filled:
            lines.append(f"- {name}: always empty")
            continue
        # Typ: der vorherrschende; gemischte Zahlen gelten als decimal
        t = types[i].most_common(1)[0][0]
        if set(types[i]) <= {"integer", "decimal"} and "decimal" in types[i]:
            t = "decimal"
        mixed = "" if types[i][t] >= 0.95 * filled else " (mixed types)"
        distinct = len(counters[i])
        desc = f"- {name}: {t}{mixed}, {distinct:,}{'+' if distinct >= 5000 else ''} distinct"
        if empty[i]:
            pct = 100 * empty[i] / n
            desc += f", {'<1' if pct < 1 else format(pct, '.0f')}% empty"
        if t in ("integer", "decimal") and nums[i][0] is not None:
            lo, hi = nums[i]
            fmt = (lambda x: f"{x:g}")
            desc += f", range {fmt(lo)} to {fmt(hi)}"
        if distinct <= 12:
            desc += "; values: " + ", ".join(f"{v} ({c})" for v, c in counters[i].most_common())
        else:
            desc += "; e.g. " + ", ".join(v for v, _ in counters[i].most_common(4))
        lines.append(desc)
    if ncols > MAX_PROFILE_COLUMNS:
        lines.append(f"- … {ncols - MAX_PROFILE_COLUMNS} more columns: " + ", ".join(header[MAX_PROFILE_COLUMNS:]))
    if samples:
        lines.append("Example rows:")
        lines += ["  " + " | ".join(_short_val(c if c is not None else "", 30) for c in r[:ncols]) for r in samples]
    return "\n".join(lines)

def _profile_csv(content: bytes, fname: str) -> str:
    text = _decode_text(content)
    try:
        dialect = csv.Sniffer().sniff(text[:20000], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    header = next(reader, [])
    return profile_table(fname, header, reader)

def _profile_excel(content: bytes, fname: str) -> str:
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    parts = []
    for ws in wb.worksheets:
        rows = ws.iter_rows(values_only=True)
        header = None
        for r in rows:  # erste nicht-leere Zeile ist die Kopfzeile
            if any(c not in (None, "") for c in r):
                header = list(r)
                break
        if header is None:
            parts.append(f"Sheet '{ws.title}': empty")
            continue
        parts.append(profile_table(f"{fname} / sheet '{ws.title}'", header, rows))
    return "\n\n".join(parts)

def _summarize_rdf(g, label: str) -> str:
    from collections import Counter
    from rdflib import URIRef
    from rdflib.namespace import RDF, OWL, RDFS
    def short(t):
        try:
            return g.namespace_manager.normalizeUri(t)
        except Exception:
            return str(t)
    declared = sorted({short(c) for c in g.subjects(RDF.type, OWL.Class)} |
                      {short(c) for c in g.subjects(RDF.type, RDFS.Class)})
    props = sorted({short(p) for t in (OWL.ObjectProperty, OWL.DatatypeProperty, RDF.Property)
                    for p in g.subjects(RDF.type, t)})
    used_types = Counter(short(o) for o in g.objects(None, RDF.type)
                         if o not in (OWL.Class, RDFS.Class, OWL.ObjectProperty, OWL.DatatypeProperty,
                                      OWL.AnnotationProperty, OWL.Ontology, RDF.Property, OWL.NamedIndividual))
    used_preds = Counter(short(p) for p in g.predicates())
    lines = [f"{label}: {len(g):,} triples"]
    if declared:
        lines.append(f"Declared classes ({len(declared)}): " + ", ".join(declared[:60]) + (" …" if len(declared) > 60 else ""))
    if props:
        lines.append(f"Declared properties ({len(props)}): " + ", ".join(props[:60]) + (" …" if len(props) > 60 else ""))
    if used_types:
        lines.append("Instances per class: " + ", ".join(f"{c} ({n:,})" for c, n in used_types.most_common(25)))
    lines.append("Predicates in use: " + ", ".join(f"{p} ({n:,})" for p, n in used_preds.most_common(30)))
    # Nur Namespaces, die in der Datei vorkommen — rdflib bindet viele bekannte Prefixe von sich aus
    from itertools import islice
    terms = {str(t) for triple in islice(g, 50_000) for t in triple if isinstance(t, URIRef)}
    used_ns = [f"{p}: <{ns}>" for p, ns in g.namespaces() if any(t.startswith(str(ns)) for t in terms)]
    if used_ns:
        lines.append("Namespaces: " + ", ".join(used_ns))
    return "\n".join(lines)

def _pdf_visible_text(page) -> str:
    """Text einer PDF-Seite, aber nur aus dem sichtbaren Seitenbereich. Manche PDFs (z.B. aus IEEE Xplore)
    enthalten pro Seite die ganze Doppelseite und zeigen nur einen Ausschnitt — pypdf liest sonst alles
    doppelt."""
    box = page.cropbox
    x0, y0, x1, y1 = float(box.left), float(box.bottom), float(box.right), float(box.top)
    out, last_y = [], None
    def visit(text, cm, tm, font_dict, font_size):
        nonlocal last_y
        if not text:
            return
        x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
        y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
        if not (x0 - 5 <= x <= x1 + 5 and y0 - 5 <= y <= y1 + 5):
            return
        if last_y is not None and abs(y - last_y) > 2 and out and not out[-1].endswith("\n"):
            out.append("\n")
        out.append(text)
        last_y = y
    page.extract_text(visitor_text=visit)
    return "".join(out)

def pdf_text(content: bytes, page_markers: bool = False):
    """Volltext einer PDF, bereinigt: nur sichtbarer Text, keine Steuerzeichen aus Schriften ohne
    Zeichenzuordnung, Ligaturen aufgeloest, Silbentrennung am Zeilenende zusammengefuegt.
    Mit page_markers beginnt jede Seite mit "[page N]", damit das Modell Fundstellen angeben kann."""
    import pypdf, unicodedata
    reader = pypdf.PdfReader(io.BytesIO(content))
    pages = []
    for page in reader.pages:
        try:
            t = _pdf_visible_text(page)
        except Exception:
            t = ""
        pages.append(t if t.strip() else (page.extract_text() or ""))
    if page_markers:
        pages = [f"[page {i}]\n{p.strip()}" for i, p in enumerate(pages, 1)]
    text = unicodedata.normalize("NFKC", "\n\n".join(p.strip() for p in pages))
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]+", "", text)
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip(), len(reader.pages)

def analyze_file(content: bytes, filename: str) -> dict:
    """Liefert {"kind", "summary", "full_text"}: summary geht in die Prompts, full_text (nur bei Textdokumenten)
    einmal in den Entwurf des Projektkontexts."""
    fn = filename.lower()
    try:
        if fn.endswith(".csv"):
            return {"kind": "table", "summary": _profile_csv(content, filename), "full_text": ""}
        if fn.endswith((".xlsx", ".xlsm")):
            return {"kind": "table", "summary": _profile_excel(content, filename), "full_text": ""}
        if fn.endswith(".xls"):
            return {"kind": "error", "summary": "[Old .xls format is not supported - please save as .xlsx or .csv]",
                    "full_text": ""}
        rdf_format = ("turtle" if fn.endswith((".ttl", ".turtle")) else "json-ld" if fn.endswith(".jsonld")
                      else "xml" if fn.endswith((".rdf", ".owl", ".xml")) else None)
        if rdf_format:
            from rdflib import Graph
            g = Graph()
            try:
                g.parse(data=content.decode("utf-8", errors="replace"), format=rdf_format)
                return {"kind": "rdf", "summary": _summarize_rdf(g, filename), "full_text": ""}
            except Exception:
                pass  # nicht parsebar: wie Text behandeln
        if fn.endswith(".pdf"):
            text, n_pages = pdf_text(content)
            note = f"PDF, {n_pages} pages"
        else:
            text = _decode_text(content).strip()
            note = "text"
    except Exception as ex:
        return {"kind": "error", "summary": f"[Could not read {filename}: {type(ex).__name__}: {str(ex)[:150]}]",
                "full_text": ""}
    full = text[:CONTEXT_SOURCE_LIMIT]
    if len(text) > CONTEXT_SOURCE_LIMIT:
        full += f"\n\n[... truncated after {CONTEXT_SOURCE_LIMIT:,} of {len(text):,} characters]"
    excerpt = text[:TEXT_EXCERPT_CHARS]
    if len(text) > TEXT_EXCERPT_CHARS:
        excerpt += (f"\n[… excerpt of {len(text):,} characters ({note}); the full text is read for the "
                    f"project context in step 4]")
    return {"kind": "text", "summary": excerpt, "full_text": full}

def data_documents_text(session) -> str:
    """Volltexte der hochgeladenen Textdokumente fuer den Kontext-Entwurf, mit Gesamtobergrenze."""
    parts, used = [], 0
    for f in session.get("data_files") or []:
        if f.get("kind") != "text" or not f.get("full_text"):
            continue
        room = DATA_TEXT_TOTAL_LIMIT - used
        if room <= 0:
            parts.append(f"=== {f['name']} === (omitted - total limit of {DATA_TEXT_TOTAL_LIMIT:,} characters reached)")
            continue
        text = f["full_text"][:room]
        used += len(text)
        parts.append(f"=== {f['name']} ===\n" + text)
    return "\n\n".join(parts)

def _store_uploads(session, analyzed: list, append: bool):
    files = (session.get("data_files") or []) if append else []
    files += analyzed
    session["data_files"] = files
    session["data_preview"] = "\n\n".join(f"=== {f['name']}{f.get('suffix', '')} ===\n{f['summary']}" for f in files)

def extract_full_text(content: bytes, filename: str) -> str:
    """Volltext einer Kontextdatei (Schritt 3)."""
    fn = filename.lower()
    if fn.endswith(".pdf"):
        text, _ = pdf_text(content)
    elif fn.endswith((".md", ".markdown", ".txt")):
        text = _decode_text(content)
    else:
        raise HTTPException(status_code=400, detail="Context files must be Markdown, text or PDF "
                                                    "(.md, .txt, .pdf). Save Word documents as PDF first.")
    text = text.strip()
    if len(text) > CONTEXT_SOURCE_LIMIT:
        text = text[:CONTEXT_SOURCE_LIMIT] + f"\n\n[... truncated after {CONTEXT_SOURCE_LIMIT:,} characters]"
    return text

# ── Literatur-Korpus ───────────────────────────────────────────────────────────
# Fuer Dutzende Paper reicht der Projektkontext nicht: dessen Entwurf liest hoechstens 300.000 Zeichen. Statt
# alles in einen Prompt zu stecken, wird jedes Paper einzeln zu einer "Paper Card" verdichtet (Begriffe mit
# Definition, Seite und woertlichem Zitat, Relationen, Taxonomien, CQ-Kandidaten, Vokabulare). Die Cards werden
# danach zu einem Begriffsinventar zusammengefuehrt: Synonyme gebuendelt, abweichende Definitionen als Konflikte
# markiert, Themen als Modul-Kandidaten. Die Volltexte liegen als Dateien neben der Session und nicht in deren
# JSON, die nach jeder aendernden Anfrage neu geschrieben wird.
CORPUS_DOC_LIMIT = 200_000         # Zeichen je Paper im Extraktions-Prompt (~50.000 Tokens)
CORPUS_EXTENSIONS = (".pdf", ".txt", ".md", ".markdown")
ONTOLOGY_EXTENSIONS = (".ttl", ".turtle", ".rdf", ".owl", ".xml", ".jsonld", ".nt")
TABLE_EXTENSIONS = (".csv", ".xlsx", ".xlsm")
MAX_SOURCE_CONCEPTS = 1500         # Begriffe aus einer bestehenden Ontologie oder Begriffstabelle
MAX_TABLE_ROWS = 20_000
CARD_EFFORT = "medium"             # Lesen und Verdichten braucht weniger Denkaufwand als Modellieren
MAX_CARD_CONCEPTS = 60
MAX_CARD_ITEMS = 30
MAX_CARD_CQS = 8
INVENTORY_PROMPT_LIMIT = 200_000   # Zeichen der Begriffsliste im Konsolidierungs-Prompt (~50.000 Tokens)

def source_type(doc) -> str:
    """paper (Volltext, LLM-Extraktion), ontology (RDF) oder glossary (Begriffstabelle)."""
    return doc.get("source_type") or "paper"

def _corpus(session) -> dict:
    c = session.setdefault("corpus", {})
    c.setdefault("docs", [])
    c.setdefault("inventory", None)
    return c

def corpus_text_path(session_id, doc_id) -> Path:
    return SESSION_DIR / session_id / "corpus" / (doc_id + ".txt")

def corpus_text(content: bytes, filename: str):
    """Volltext eines Papers mit Seitenmarken; liefert (text, seitenzahl oder None)."""
    if filename.lower().endswith(".pdf"):
        return pdf_text(content, page_markers=True)
    return _decode_text(content).strip(), None

# Bestehende Ontologien und Begriffstabellen werden ohne LLM in eine Card uebersetzt: Labels, Definitionen,
# Oberklassen und Properties stehen dort bereits explizit — eine Extraktion wuerde nur Fehler hinzufuegen.
_SKIP_NS = ("http://www.w3.org/2002/07/owl#", "http://www.w3.org/2000/01/rdf-schema#",
            "http://www.w3.org/1999/02/22-rdf-syntax-ns#", "http://www.w3.org/2001/XMLSchema#")

def _rdf_format(fn: str):
    fn = fn.lower()
    if fn.endswith((".ttl", ".turtle")):
        return "turtle"
    if fn.endswith(".jsonld"):
        return "json-ld"
    if fn.endswith(".nt"):
        return "nt"
    return "xml"

def _local_name(uri) -> str:
    s = re.split(r"[#/]", str(uri).rstrip("#/"))[-1]
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", s).replace("_", " ").strip() or str(uri)

def ontology_card(content: bytes, filename: str) -> dict:
    """Card einer bestehenden Ontologie: Klassen mit Label, Definition, Oberklasse und Synonymen, Object
    Properties als Relationen (Domain -> Range), Namespace und Importe als Vokabulare."""
    from rdflib import Graph, URIRef, Literal
    from rdflib.namespace import RDF, RDFS, OWL, SKOS, DCTERMS, DC
    g = Graph()
    # OWL/XML laesst sich von rdflib als (leeres) RDF/XML lesen - daher am Wurzelelement erkennen
    owl_xml = re.search(rb"<(\w+:)?Ontology[\s>]", content[:5000]) and b"rdf:RDF" not in content[:5000]
    hint = " It looks like OWL/XML, which is not supported - save it as RDF/XML or Turtle (e.g. with Protégé)." \
        if owl_xml else ""
    try:
        g.parse(data=content.decode("utf-8", errors="replace"), format=_rdf_format(filename))
    except Exception as ex:
        raise ValueError(f"not parseable as RDF ({type(ex).__name__}).{hint}")
    IAO_DEF = URIRef("http://purl.obolibrary.org/obo/IAO_0000115")
    OBO_SYN = [URIRef("http://www.geneontology.org/formats/oboInOwl#hasExactSynonym"),
               URIRef("http://www.geneontology.org/formats/oboInOwl#hasRelatedSynonym")]

    def literals(node, preds):
        return [o for p in preds for o in g.objects(node, p) if isinstance(o, Literal) and str(o).strip()]
    def best(lits):  # englisch, sonst ohne Sprachangabe, sonst irgendeine
        for l in lits:
            if (l.language or "").lower().startswith("en"):
                return str(l)
        for l in lits:
            if not l.language:
                return str(l)
        return str(lits[0]) if lits else ""
    def label(node):
        lits = literals(node, [SKOS.prefLabel, RDFS.label])
        return best(lits) or _local_name(node)

    classes = [c for t in (OWL.Class, RDFS.Class) for c in g.subjects(RDF.type, t)
               if isinstance(c, URIRef) and not str(c).startswith(_SKIP_NS)]
    classes = list(dict.fromkeys(classes))
    if not classes:
        raise ValueError("no classes found." + hint)
    concepts = []
    for c in classes[:MAX_SOURCE_CONCEPTS]:
        term = label(c)
        names = {str(l) for l in literals(c, [SKOS.prefLabel, RDFS.label, SKOS.altLabel, *OBO_SYN])}
        parents = [p for p in g.objects(c, RDFS.subClassOf) if isinstance(p, URIRef) and not str(p).startswith(_SKIP_NS)]
        concepts.append({"term": _plain(term, 120),
                         "definition": _plain(best(literals(c, [SKOS.definition, IAO_DEF, RDFS.comment, DCTERMS.description])), 600),
                         "broader": _plain(label(parents[0]), 120) if parents else "",
                         "synonyms": sorted(_plain(n, 120) for n in names if n != term)[:8],
                         "page": None, "quote": "", "quote_ok": False, "uri": str(c)})
    relations = []
    for p in dict.fromkeys(p for p in g.subjects(RDF.type, OWL.ObjectProperty) if isinstance(p, URIRef)):
        doms = [d for d in g.objects(p, RDFS.domain) if isinstance(d, URIRef)]
        rngs = [r for r in g.objects(p, RDFS.range) if isinstance(r, URIRef)]
        if doms and rngs:
            relations.append({"subject": label(doms[0]), "relation": _plain(label(p), 80),
                              "object": label(rngs[0]), "page": None, "uri": str(p)})
    onto = next((o for o in g.subjects(RDF.type, OWL.Ontology) if isinstance(o, URIRef)), None)
    if onto is not None:
        namespace = str(onto)
    else:
        from collections import Counter
        ns = Counter(re.match(r"^(.*[#/])", str(c)).group(1) for c in classes if re.match(r"^(.*[#/])", str(c)))
        namespace = ns.most_common(1)[0][0] if ns else ""
    meta = lambda preds: _plain(best(literals(onto, preds)), 300) if onto is not None else ""
    vocabularies = [{"name": _local_name(i) or str(i), "uri": str(i)} for i in g.objects(onto, OWL.imports)] if onto is not None else []
    n_props = len(set(g.subjects(RDF.type, OWL.ObjectProperty)) | set(g.subjects(RDF.type, OWL.DatatypeProperty)))
    scope = meta([DCTERMS.description, RDFS.comment, DC.description])
    return {"title": meta([DCTERMS.title, RDFS.label, DC.title]) or filename, "authors": meta([DCTERMS.creator, DC.creator]),
            "year": (meta([DCTERMS.created, DCTERMS.issued, DCTERMS.modified, DC.date]) or "")[:4],
            "scope": scope or f"Existing ontology with {len(classes)} classes and {n_props} properties.",
            "contribution": "ontology", "namespace": namespace,
            "stats": {"classes": len(classes), "properties": n_props, "triples": len(g),
                      "truncated": len(classes) > MAX_SOURCE_CONCEPTS},
            "concepts": concepts, "relations": relations[:MAX_SOURCE_CONCEPTS], "taxonomies": [],
            "competency_questions": [], "vocabularies": vocabularies}

def read_table(content: bytes, filename: str) -> dict:
    """Tabelle als {"sheets": {name: {"header": [...], "rows": [[...]]}}} (Werte als Text)."""
    cell = lambda v: "" if v is None else re.sub(r"\s+", " ", str(v)).strip()
    sheets = {}
    if filename.lower().endswith(".csv"):
        text = _decode_text(content)
        try:
            dialect = csv.Sniffer().sniff(text[:20000], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        rows = [[cell(v) for v in r] for r in csv.reader(io.StringIO(text), dialect)]
        sheets["CSV"] = rows
    else:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        for ws in wb.worksheets:
            sheets[ws.title] = [[cell(v) for v in r] for _, r in zip(range(MAX_TABLE_ROWS + 50), ws.iter_rows(values_only=True))]
    out = {}
    for name, rows in sheets.items():
        rows = [r for r in rows if any(r)]
        if not rows:
            continue
        header = [h or f"Column {i + 1}" for i, h in enumerate(rows[0])]
        body = [r + [""] * (len(header) - len(r)) for r in rows[1:MAX_TABLE_ROWS + 1]]
        out[name] = {"header": header, "rows": [r[:len(header)] for r in body], "total_rows": len(rows) - 1}
    if not out:
        raise ValueError("the table is empty")
    return {"sheets": out}

_COLUMN_HINTS = {
    "term": ("preflabel", "label", "term", "concept", "name", "class", "begriff", "bezeichnung", "title"),
    "definition": ("definition", "description", "comment", "meaning", "explanation", "beschreibung", "erklaerung", "desc"),
    "broader": ("broader", "parent", "superclass", "subclassof", "isa", "supertype", "category", "oberbegriff"),
    "synonyms": ("synonym", "altlabel", "alias", "alternative", "aka", "abbreviation"),
    "uri": ("uri", "iri", "url"),
}

def guess_columns(header: list, rows: list) -> dict:
    """Ordnet Spalten nach ihren Ueberschriften den Rollen Begriff, Definition, Oberbegriff, Synonyme, URI zu."""
    norm = [re.sub(r"[^a-z]", "", h.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")) for h in header]
    mapping, used = {}, set()
    for role, hints in _COLUMN_HINTS.items():
        for hint in hints:
            hit = next((i for i, n in enumerate(norm) if i not in used and hint in n), None)
            if hit is not None:
                mapping[role] = hit
                used.add(hit)
                break
    if "uri" not in mapping:  # eine Spalte mit http-Werten ist die URI, auch ohne passende Ueberschrift
        for i in range(len(header)):
            vals = [r[i] for r in rows[:50] if r[i]]
            if i not in used and vals and sum(v.startswith("http") for v in vals) > 0.8 * len(vals):
                mapping["uri"] = i
                used.add(i)
                break
    if "term" not in mapping:
        mapping["term"] = next((i for i in range(len(header)) if i not in used), 0)
    return mapping

def table_card(table: dict, sheet: str, mapping: dict, filename: str) -> dict:
    data = table["sheets"].get(sheet)
    if not data:
        raise HTTPException(status_code=400, detail=f"Sheet '{sheet}' not found")
    ncol = len(data["header"])
    col = lambda role: mapping.get(role) if isinstance(mapping.get(role), int) and 0 <= mapping[role] < ncol else None
    if col("term") is None:
        raise HTTPException(status_code=400, detail="Choose the column that holds the terms")
    get = lambda r, role: r[col(role)] if col(role) is not None else ""
    concepts, seen = [], set()
    for r in data["rows"]:
        term = _plain(get(r, "term"), 120)
        key = concept_key(term)
        if not key or key in seen:
            continue
        seen.add(key)
        syns = [_plain(s, 120) for s in re.split(r"[;|]", get(r, "synonyms")) if _plain(s)]
        concepts.append({"term": term, "definition": _plain(get(r, "definition"), 600),
                         "broader": _plain(get(r, "broader"), 120), "synonyms": syns[:8], "page": None,
                         "quote": "", "quote_ok": False, "uri": _plain(get(r, "uri"), 300)})
    return {"title": filename + (f" / {sheet}" if len(table["sheets"]) > 1 else ""), "authors": "", "year": "",
            "scope": f"Concept table with {len(concepts)} terms.", "contribution": "glossary", "namespace": "",
            "stats": {"rows": data["total_rows"], "truncated": len(concepts) > MAX_SOURCE_CONCEPTS},
            "concepts": concepts[:MAX_SOURCE_CONCEPTS], "relations": [], "taxonomies": [],
            "competency_questions": [], "vocabularies": []}

def table_mapping_info(table: dict) -> dict:
    """Spalten, Vorschlag und Beispielzeilen je Blatt — fuer die Zuordnung im Browser."""
    return {name: {"header": s["header"], "total_rows": s["total_rows"], "sample": s["rows"][:5],
                   "guess": guess_columns(s["header"], s["rows"])} for name, s in table["sheets"].items()}

def _plain(v, limit=None) -> str:
    s = re.sub(r"\s+", " ", str(v if v is not None else "")).strip()
    return s[:limit] if limit else s

def _page(v):
    try:
        p = int(v)
        return p if p > 0 else None
    except (TypeError, ValueError):
        return None

def _match_text(s) -> str:
    """Vergleichsform fuer Zitate: Zeilenumbrueche, Satzzeichen und Gross-/Kleinschreibung zaehlen nicht."""
    return re.sub(r"[^a-z0-9]+", " ", unicodedata.normalize("NFKC", str(s)).lower()).strip()

CARD_SYS = (MOMO_METHOD + "\nYou read ONE paper of a literature corpus from which an ontology will be built, and "
            "condense what it contributes to the domain model into a PAPER CARD. Later steps never see the paper "
            "again, only your card - so it must be precise and traceable to the paper.\n"
            "Extract:\n"
            "- concepts: the domain terms the paper DEFINES or characterizes - not every noun. Skip generic research "
            "vocabulary (study, participant, method, result) unless it belongs to the domain itself. Per concept: the "
            "term as the paper writes it; its definition in the paper's sense (paraphrased, at most 2 sentences); a "
            "broader term if the paper states or clearly implies one; synonyms and abbreviations the paper uses; the "
            "page (from the [page N] markers, null if there are none); and a short VERBATIM quote of at most 25 words, "
            "copied exactly from the paper, that supports the definition.\n"
            "- relations between concepts that the paper states (subject, a short verb phrase, object).\n"
            "- taxonomies or classifications the paper proposes (e.g. a typology of tasks): name and categories.\n"
            "- competency questions that the paper's model or framework lets one answer ('Which ...?', 'What ...?'), "
            "at most " + str(MAX_CARD_CQS) + ".\n"
            "- vocabularies, ontologies or standards the paper uses or refers to.\n"
            "Rules: Use only what the paper says; never add domain knowledge of your own. At most "
            + str(MAX_CARD_CONCEPTS) + " concepts - prefer those central to the paper's contribution. Write in English "
            "whatever the language of the paper, but keep quotes in the original language.\n"
            'Answer ONLY as JSON: {"title":"","authors":"","year":"","scope":"1-2 sentences: which aspect of the domain '
            'the paper covers","contribution":"taxonomy|framework|model|survey|ontology|empirical|method|other",'
            '"concepts":[{"term":"","definition":"","broader":"","synonyms":[""],"page":1,"quote":""}],'
            '"relations":[{"subject":"","relation":"","object":"","page":1}],'
            '"taxonomies":[{"name":"","categories":[""],"page":1}],'
            '"competency_questions":[""],"vocabularies":[{"name":"","uri":""}]}')

def build_card_prompt(session, doc, text):
    momo = session.get("momo") or {}
    md = ((session.get("context") or {}).get("markdown") or "").strip()
    parts = ["**Ontology to be built (decides which concepts are relevant):**\n" + (momo.get("use_case") or "(not described)")]
    if md:
        parts.append("**Project context:**\n" + md)
    body = text[:CORPUS_DOC_LIMIT]
    if len(text) > CORPUS_DOC_LIMIT:
        body += f"\n\n[... truncated after {CORPUS_DOC_LIMIT:,} of {len(text):,} characters]"
    parts.append(f"**Paper ({doc['name']}):**\n" + body)
    return [{"role": "system", "content": CARD_SYS},
            {"role": "user", "content": "\n\n".join(parts) + "\n\nWrite the paper card."}]

def clean_card(raw: dict, text: str) -> dict:
    """Bringt die Antwort in eine feste Form und prueft jedes Zitat gegen den Volltext (quote_ok)."""
    raw = raw if isinstance(raw, dict) else {}
    haystack = _match_text(text)
    def lst(key):
        v = raw.get(key)
        return v if isinstance(v, list) else []
    concepts, seen = [], set()
    for c in lst("concepts"):
        if not isinstance(c, dict) or not _plain(c.get("term")):
            continue
        key = concept_key(c["term"])
        if not key or key in seen:
            continue
        seen.add(key)
        quote = _plain(c.get("quote"), 400)
        q = _match_text(quote)
        syns = c.get("synonyms") if isinstance(c.get("synonyms"), list) else []
        concepts.append({"term": _plain(c["term"], 120), "definition": _plain(c.get("definition"), 600),
                         "broader": _plain(c.get("broader"), 120),
                         "synonyms": [_plain(s, 120) for s in syns if _plain(s)][:8],
                         "page": _page(c.get("page")), "quote": quote,
                         "quote_ok": bool(quote) and len(q) >= 10 and q in haystack})
    relations = [{"subject": _plain(r.get("subject"), 120), "relation": _plain(r.get("relation"), 80),
                  "object": _plain(r.get("object"), 120), "page": _page(r.get("page"))}
                 for r in lst("relations")
                 if isinstance(r, dict) and _plain(r.get("subject")) and _plain(r.get("relation")) and _plain(r.get("object"))]
    taxonomies = [{"name": _plain(t.get("name"), 120), "page": _page(t.get("page")),
                   "categories": [_plain(x, 120) for x in (t.get("categories") or []) if _plain(x)][:MAX_CARD_ITEMS]}
                  for t in lst("taxonomies") if isinstance(t, dict) and _plain(t.get("name"))]
    vocabularies = [{"name": _plain(v.get("name"), 120), "uri": _plain(v.get("uri"), 300)}
                    for v in lst("vocabularies") if isinstance(v, dict) and _plain(v.get("name"))]
    return {"title": _plain(raw.get("title"), 300), "authors": _plain(raw.get("authors"), 300),
            "year": _plain(raw.get("year"), 10), "scope": _plain(raw.get("scope"), 600),
            "contribution": _plain(raw.get("contribution"), 30),
            "concepts": concepts[:MAX_CARD_CONCEPTS], "relations": relations[:MAX_CARD_ITEMS],
            "taxonomies": taxonomies[:MAX_CARD_ITEMS],
            "competency_questions": [_plain(q, 300) for q in lst("competency_questions") if _plain(q)][:MAX_CARD_CQS],
            "vocabularies": vocabularies[:MAX_CARD_ITEMS]}

_LEADING_ARTICLE = re.compile(r"^(the|a|an) ")

def _key_words(term) -> list:
    s = unicodedata.normalize("NFKC", str(term or ""))
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z][a-z])", " ", s).lower()  # CamelCase aus Ontologien: VisualEncoding
    s = re.sub(r"[-_/]+", " ", s)
    s = re.sub(r"[^\w\s]", "", s)
    s = _LEADING_ARTICLE.sub("", re.sub(r"\s+", " ", s).strip())
    return s.split(" ") if s else []

def concept_key(term) -> str:
    """Vergleichsschluessel fuer Begriffe: Schreibweise, Bindestriche, Artikel und Plural des letzten Worts
    zaehlen nicht ("Visual Encodings" = "visual-encoding")."""
    words = _key_words(term)
    return " ".join(words[:-1] + [_singular(words[-1])]) if words else ""

# Singular und Plural muessen denselben Schluessel ergeben (Code-Review T11, DECISIONS 121): vorher blieben
# metric/metrics, topic/topics, bias/biases ("bia"/"biase"), analysis/analyses und axis/axes getrennt
CONCEPT_KEY_VERSION = 2
_IRREGULAR_PLURALS = {"analyses": "analysis", "hypotheses": "hypothesis", "syntheses": "synthesis", "theses": "thesis",
                      "diagnoses": "diagnosis", "crises": "crisis", "emphases": "emphasis", "axes": "axis",
                      "indices": "index", "matrices": "matrix", "vertices": "vertex", "appendices": "appendix",
                      "criteria": "criterion", "phenomena": "phenomenon", "taxa": "taxon"}
_SINGULAR_S = {"bias", "alias", "atlas", "canvas", "gas", "lens", "status", "virus", "focus", "campus", "corpus",
               "census", "consensus", "bonus", "stimulus", "radius", "apparatus", "nexus", "thesaurus", "chaos"}

def _singular(w) -> str:
    if w in _IRREGULAR_PLURALS:
        return _IRREGULAR_PLURALS[w]
    if w in _SINGULAR_S:
        return w
    if w.endswith("es") and w[:-2] in _SINGULAR_S:          # biases, statuses, lenses
        return w[:-2]
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 4 and w.endswith(("sses", "xes", "ches", "shes")):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
        return w[:-1]                                         # auch -ics: metrics -> metric (nur ein Schluessel)
    return w

def _concept_key_v1(term) -> str:
    """Der Schluessel bis DECISIONS 121 - nur, um gespeicherte Entscheidungen auf den neuen umzuschluesseln."""
    words = _key_words(term)
    if not words:
        return ""
    w = words[-1]
    if len(w) > 4 and w.endswith("ies"):
        w = w[:-3] + "y"
    elif len(w) > 4 and w.endswith(("sses", "xes", "ches", "shes")):
        w = w[:-2]
    elif len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is", "ics")):
        w = w[:-1]
    return " ".join(words[:-1] + [w])

def migrate_concept_keys(session) -> int:
    """Schluesselt die gespeicherten Entscheidungen eines Projekts auf den neuen Begriffsschluessel um: die
    ausgeschlossenen Begriffe (gap_decisions, nur Schluessel -> Grund: ueber die Bezeichnungen des Inventars) und die
    entschiedenen Definitionen (sie tragen ihren Begriff). Einmal je Projekt; liefert die Zahl geaenderter Schluessel."""
    if session.get("concept_key_version") == CONCEPT_KEY_VERSION:
        return 0
    changed = 0
    remap = {}
    for c in ((session.get("corpus") or {}).get("inventory") or {}).get("concepts") or []:
        for v in [c.get("label"), *c.get("variants", [])]:
            if v and _concept_key_v1(v) != concept_key(v):
                remap.setdefault(_concept_key_v1(v), concept_key(v))
    gap = session.get("gap_decisions")
    if isinstance(gap, dict):
        new = {}
        for k, reason in gap.items():
            nk = remap.get(k, k)
            changed += nk != k
            new.setdefault(nk, reason)
        session["gap_decisions"] = new
    defs = (session.get("context") or {}).get("definition_decisions")
    if isinstance(defs, dict):
        new = {}
        for k, e in defs.items():
            nk = concept_key(e.get("concept")) if isinstance(e, dict) and e.get("concept") else remap.get(k, k)
            changed += nk != k
            new.setdefault(nk or k, e)
        session["context"]["definition_decisions"] = new
    session["concept_key_version"] = CONCEPT_KEY_VERSION
    return changed

def _is_abbreviation(s) -> bool:
    return bool(re.fullmatch(r"[A-Z0-9]{2,6}s?", str(s).strip()))

def _decode_text(content) -> str:
    """Text einer Datei: UTF-8 (mit oder ohne BOM), sonst Windows-1252 - so speichert das deutsche Excel CSV;
    vorher wurden die Umlaute zu Ersatzzeichen."""
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return content.decode("cp1252", errors="replace")

def group_concepts(docs) -> list:
    """Buendelt die Begriffe aller Cards deterministisch: gleicher Vergleichsschluessel oder als Synonym
    genannt. Abkuerzungen verbinden nichts (sonst wuerde "VA" fremde Begriffe zusammenziehen), sie bleiben
    nur als Variante erhalten. Ein abgekuerzter Begriff ("VA") kommt unter seine erste Langform ("visual
    analytics"), nicht unter die Abkuerzung, die verschiedene Langformen haben kann."""
    parent = {}
    def find(k):
        while parent.setdefault(k, k) != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k
    entries = []
    for d in docs:
        for c in (d.get("card") or {}).get("concepts", []):
            links = [concept_key(s) for s in c.get("synonyms", []) if not _is_abbreviation(s)]
            key = links[0] if _is_abbreviation(c["term"]) and links and links[0] else concept_key(c["term"])
            for other in links:
                if other:
                    parent[find(other)] = find(key)
            find(key)
            entries.append((key, d["id"], c))
    groups = {}
    for key, doc_id, c in entries:
        g = groups.setdefault(find(key), {"terms": [], "variants": set(), "sources": []})
        g["terms"].append(c["term"])
        g["variants"].update([c["term"], *c.get("synonyms", [])])
        g["sources"].append({"doc": doc_id, "term": c["term"], "definition": c.get("definition", ""),
                             "broader": c.get("broader", ""), "page": c.get("page"), "quote": c.get("quote", ""),
                             "quote_ok": c.get("quote_ok", False), "uri": c.get("uri", "")})
    concepts = []
    for g in groups.values():
        counts = {}
        for t in g["terms"]:
            counts[t] = counts.get(t, 0) + 1
        label = max(counts, key=lambda t: (counts[t], not _is_abbreviation(t), -len(t)))
        concepts.append({"label": label, "variants": sorted(v for v in g["variants"] if v != label),
                         "sources": g["sources"], "definition": "", "conflict": False})
    for c in concepts:
        c["papers"] = len({s["doc"] for s in c["sources"]})
    concepts.sort(key=lambda c: (-c["papers"], -len(c["sources"]), c["label"].lower()))
    for i, c in enumerate(concepts, 1):
        c["id"] = f"c{i}"
    return concepts

def _aggregate_card_lists(docs, concepts):
    """Relationen, Taxonomien, CQ-Kandidaten und Vokabulare ueber alle Cards, mit Herkunft."""
    concept_of = {}
    for c in concepts:
        for t in [c["label"], *c["variants"]]:
            concept_of.setdefault(concept_key(t), c["id"])
    relations, cqs, vocabs, taxonomies = {}, {}, {}, []
    for d in docs:
        card = d.get("card") or {}
        for r in card.get("relations", []):
            k = (concept_key(r["subject"]), _match_text(r["relation"]), concept_key(r["object"]))
            e = relations.setdefault(k, {"subject": r["subject"], "relation": r["relation"], "object": r["object"],
                                         "subject_id": concept_of.get(k[0]), "object_id": concept_of.get(k[2]),
                                         "docs": []})
            if d["id"] not in e["docs"]:
                e["docs"].append(d["id"])
        for q in card.get("competency_questions", []):
            e = cqs.setdefault(_match_text(q), {"question": q, "docs": []})
            if d["id"] not in e["docs"]:
                e["docs"].append(d["id"])
        for v in card.get("vocabularies", []):
            e = vocabs.setdefault(_match_text(v["name"]), {"name": v["name"], "uri": v.get("uri", ""), "docs": []})
            e["uri"] = e["uri"] or v.get("uri", "")
            if d["id"] not in e["docs"]:
                e["docs"].append(d["id"])
        for t in card.get("taxonomies", []):
            taxonomies.append({**t, "doc": d["id"]})
    by_support = lambda items: sorted(items, key=lambda e: -len(e["docs"]))
    return by_support(relations.values()), taxonomies, by_support(cqs.values()), by_support(vocabs.values())

INVENTORY_SYS = (MOMO_METHOD + "\nYou consolidate the CONCEPT INVENTORY of a literature corpus from which an ontology "
                 "will be built. Each concept below comes from one or more sources, with their definitions (doc ids "
                 "such as d1a2b3c4d5 identify the sources). Sources are papers, EXISTING ONTOLOGIES or concept tables "
                 "(glossaries); a disagreement between an existing ontology and the literature counts as a conflict "
                 "too. In what follows, 'papers' means all sources. Do four things:\n"
                 "1. merges: groups of concepts that denote the SAME notion under different names (synonyms, spelling "
                 "variants, abbreviation and full form). Only true synonyms - a narrower, broader or related notion is "
                 "NOT a synonym. Give the preferred label.\n"
                 "2. conflicts: concepts that different papers define in substantively DIFFERENT ways (different "
                 "meaning or extent, contradicting characterizations) - not mere differences in wording. Per conflict: "
                 "the concept id, a one-sentence neutral statement of the issue, and the distinct positions, each with "
                 "the doc ids of the papers holding it. The team will decide these, so do not take sides.\n"
                 "3. themes: group the concepts into 4-12 themes that could become ontology modules (a part of the "
                 "domain such as tasks, data or users). Each theme has a name, a one-sentence description and its "
                 "concept ids, most central first. A concept belongs to at most one theme; peripheral concepts may "
                 "be left out.\n"
                 "4. definitions: for each concept defined by two or more papers WITHOUT a conflict, one consolidated "
                 "definition of at most 2 sentences, faithful to the papers.\n"
                 "Use only the ids given. Answer ONLY as JSON: "
                 '{"merges":[{"ids":["c1","c7"],"label":"preferred label"}],'
                 '"conflicts":[{"concept":"c3","issue":"...","positions":[{"view":"...","docs":["d..."]}]}],'
                 '"themes":[{"name":"...","description":"...","concepts":["c1","c2"]}],'
                 '"definitions":[{"concept":"c1","definition":"..."}]}')

def _inventory_listing(concepts, multi_limit, single_limit=0) -> str:
    """Begriffsliste fuer den Konsolidierungs-Prompt. Begriffe aus mehreren Quellen bekommen alle Definitionen
    (nur dort kann es Konflikte geben), Begriffe aus einer Quelle hoechstens eine kurze."""
    lines = []
    for c in concepts:
        head = f"{c['id']} | {c['label']}"
        if c["variants"]:
            head += " (also: " + "; ".join(c["variants"][:6]) + ")"
        head += f" | {c['papers']} source(s)"
        lines.append(head)
        limit = multi_limit if c["papers"] > 1 else single_limit
        if limit:
            for s in c["sources"][:8 if c["papers"] > 1 else 1]:
                if s["definition"]:
                    lines.append(f"  - {s['doc']}: {s['definition'][:limit]}")
    return "\n".join(lines)

def build_inventory_prompt(session, docs, concepts):
    kind = {"paper": "paper", "ontology": "existing ontology", "glossary": "concept table"}
    paper_lines = "\n".join(f"- {d['id']} [{kind.get(source_type(d), 'paper')}]: "
                            f"{(d['card'] or {}).get('title') or d['name']}"
                            f" ({(d['card'] or {}).get('year') or 'n.d.'})" for d in docs)
    # Alles muss in einen Aufruf passen - Synonyme und Konflikte lassen sich nur im Gesamtbild erkennen. Wird es
    # zu lang, fallen zuerst die Definitionen der Einzel-Begriffe weg, dann werden die uebrigen gekuerzt.
    for multi, single in ((300, 100), (300, 0), (200, 0), (140, 0), (90, 0), (50, 0), (0, 0)):
        listing = _inventory_listing(concepts, multi, single)
        if len(listing) <= INVENTORY_PROMPT_LIMIT:
            break
    else:
        listing = listing[:INVENTORY_PROMPT_LIMIT] + "\n[... list truncated]"
    use_case = (session.get("momo") or {}).get("use_case") or "(not described)"
    return [{"role": "system", "content": INVENTORY_SYS},
            {"role": "user", "content": f"**Ontology to be built:**\n{use_case}\n\n**Sources:**\n{paper_lines}\n\n"
                                        f"**Concepts:**\n{listing}\n\nConsolidate the inventory."}]

def apply_consolidation(concepts, result, doc_ids) -> tuple:
    """Uebernimmt Zusammenfuehrungen, Konflikte, Themen und Definitionen des Modells, nur fuer gueltige IDs."""
    by_id = {c["id"]: c for c in concepts}
    rep = {cid: cid for cid in by_id}
    def root(cid):
        while rep[cid] != cid:
            cid = rep[cid]
        return cid
    result = result if isinstance(result, dict) else {}
    for m in result.get("merges") or []:
        ids = [i for i in (m.get("ids") or []) if i in by_id] if isinstance(m, dict) else []
        roots = list(dict.fromkeys(root(i) for i in ids))
        if len(roots) < 2:
            continue
        target = by_id[max(roots, key=lambda r: by_id[r]["papers"])]
        for r in roots:
            if r == target["id"]:
                continue
            other = by_id[r]
            target["sources"] += other["sources"]
            target["variants"] = sorted(set(target["variants"]) | set(other["variants"]) | {other["label"]})
            rep[r] = target["id"]
        label = _plain(m.get("label"), 120)
        if label and label != target["label"]:
            target["variants"] = sorted((set(target["variants"]) | {target["label"]}) - {label})
            target["label"] = label
    kept = [c for c in concepts if root(c["id"]) == c["id"]]
    for c in kept:
        c["papers"] = len({s["doc"] for s in c["sources"]})
        c["variants"] = [v for v in c["variants"] if v != c["label"]]
    kept.sort(key=lambda c: (-c["papers"], -len(c["sources"]), c["label"].lower()))
    valid = lambda cid: isinstance(cid, str) and cid in rep

    conflicts, seen = [], set()
    for x in result.get("conflicts") or []:
        if not isinstance(x, dict) or not valid(x.get("concept")):
            continue
        cid = root(x["concept"])
        positions = [{"view": _plain(p.get("view"), 400), "docs": [d for d in (p.get("docs") or []) if d in doc_ids]}
                     for p in (x.get("positions") or []) if isinstance(p, dict) and _plain(p.get("view"))]
        if cid in seen or len(positions) < 2:
            continue
        seen.add(cid)
        by_id[cid]["conflict"] = True
        conflicts.append({"concept": cid, "label": by_id[cid]["label"], "issue": _plain(x.get("issue"), 400),
                          "positions": positions})
    themes, placed = [], set()
    for t in result.get("themes") or []:
        if not isinstance(t, dict) or not _plain(t.get("name")):
            continue
        members = []
        for cid in t.get("concepts") or []:
            if valid(cid) and root(cid) not in placed:
                placed.add(root(cid))
                members.append(root(cid))
        if members:
            themes.append({"name": _plain(t["name"], 80), "description": _plain(t.get("description"), 300),
                           "concepts": members})
    for x in result.get("definitions") or []:
        if isinstance(x, dict) and valid(x.get("concept")):
            c = by_id[root(x["concept"])]
            if not c["conflict"]:
                c["definition"] = _plain(x.get("definition"), 600)
    return kept, conflicts, themes

def build_inventory(session, llm_config) -> dict:
    corpus = _corpus(session)
    docs = [d for d in corpus["docs"] if d.get("status") == "done" and d.get("card")]
    if not docs:
        raise HTTPException(status_code=400, detail="No paper cards yet - extract the papers first")
    concepts = group_concepts(docs)
    inventory = {"built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "doc_ids": [d["id"] for d in docs], "consolidated": False, "warning": "",
                 "conflicts": [], "themes": []}
    try:
        with usage_step("Concept inventory"):
            result = llm.call_llm_json(llm_config, build_inventory_prompt(session, docs, concepts))
        # auf einer Kopie: bricht die Uebernahme mittendrin ab, bleibt die Gruppierung nach Namen unveraendert
        concepts, inventory["conflicts"], inventory["themes"] = apply_consolidation(
            copy.deepcopy(concepts), result, {d["id"] for d in docs})
        inventory["consolidated"] = True
    except HTTPException as ex:
        inventory["warning"] = f"Consolidation failed ({ex.detail}). Showing the inventory grouped by name only."
    except Exception as ex:  # auch Abbruch am Token-Limit: die Gruppierung nach Namen ist trotzdem brauchbar
        inventory["warning"] = (f"Consolidation failed ({type(ex).__name__}: {str(ex)[:200]}). "
                                "Showing the inventory grouped by name only.")
    u = usage_summary(_usage_log.get() or [])
    inventory["usage"] = {"input_tokens": u["input_tokens"], "output_tokens": u["output_tokens"]}
    inventory["concepts"] = concepts
    (inventory["relations"], inventory["taxonomies"], inventory["competency_questions"],
     inventory["vocabularies"]) = _aggregate_card_lists(docs, concepts)
    corpus["inventory"] = inventory
    return inventory

def doc_citation(doc) -> str:
    """Kurzzitat einer Quelle fuer Prompts und dct:source."""
    card = doc.get("card") or {}
    kind = source_type(doc)
    if kind == "ontology":
        return f"Ontology: {card.get('title') or doc['name']}" + (f" <{card['namespace']}>" if card.get("namespace") else "")
    if kind == "glossary":
        return f"Concept table: {card.get('title') or doc['name']}"
    authors = [a.strip() for a in re.split(r";| and |,(?=\s*[A-Z][a-z]+,)", card.get("authors") or "") if a.strip()]
    first = authors[0].split(",")[0].strip() if authors else ""
    who = (first + (" et al." if len(authors) > 1 else "")) if first else ""
    head = ", ".join(x for x in (who, card.get("year") or "") if x)
    return (head + ": " if head else "") + (card.get("title") or doc["name"])

def _inventory_parts(session):
    corpus = session.get("corpus") or {}
    inv = corpus.get("inventory")
    if not inv or not inv.get("concepts"):
        return None, None, None
    docs = {d["id"]: d for d in corpus.get("docs", [])}
    return inv, docs, {c["id"]: c for c in inv["concepts"]}

def _concept_definition(c) -> str:
    return c.get("definition") or next((s["definition"] for s in c["sources"] if s.get("definition")), "")

def _existing_terms(c, docs) -> list:
    return [(docs[s["doc"]], s) for s in c["sources"]
            if s["doc"] in docs and source_type(docs[s["doc"]]) == "ontology" and s.get("uri")]

def inventory_overview(session, max_central=40, max_cqs=0, max_conflicts=25, skip_cqs=()) -> str:
    """Kompakte Uebersicht des Begriffsinventars fuer Kontext-Entwurf, CQs und Key Notions: Themen,
    zentrale Begriffe mit Definition, Konflikte, bestehende Ontologien und ggf. CQ-Kandidaten."""
    inv, docs, by_id = _inventory_parts(session)
    if not inv:
        return ""
    from collections import Counter
    kinds = Counter(source_type(docs[i]) for i in inv["doc_ids"] if i in docs)
    names = {"paper": "papers", "ontology": "existing ontologies", "glossary": "concept tables"}
    multi = [c for c in inv["concepts"] if c["papers"] > 1]
    lines = [f"Built from {len(inv['doc_ids'])} sources (" + ", ".join(f"{n} {names[k]}" for k, n in kinds.items()) +
             f"): {len(inv['concepts'])} concepts, {len(multi)} of them defined by two or more sources."]
    if inv.get("themes"):
        lines.append("\nThemes (candidate modules):")
        for t in inv["themes"]:
            members = [by_id[i] for i in t["concepts"] if i in by_id][:12]
            lines.append(f"- {t['name']}: {t['description']} Concepts: " +
                         ", ".join(f"{c['label']} ({c['papers']})" for c in members))
    central = multi[:max_central]
    if central:
        lines.append(f"\nCentral concepts (the {len(central)} defined by most sources; number of sources in brackets):")
        for c in central:
            line = f"- {c['label']} ({c['papers']}): {_concept_definition(c)[:300]}"
            ex = _existing_terms(c, docs)
            if ex:
                line += " [in existing ontology: " + "; ".join(f"{d['card'].get('title') or d['name']} <{s['uri']}>" for d, s in ex[:2]) + "]"
            if c.get("conflict"):
                line += " [CONFLICTING DEFINITIONS - see below]"
            lines.append(line)
    if inv.get("conflicts"):
        lines.append("\nConflicting definitions between sources (the team has to decide):")
        for x in inv["conflicts"][:max_conflicts]:
            lines.append(f"- {x['label']}: {x['issue']}")
            for p in x["positions"]:
                cites = "; ".join(doc_citation(docs[d]) for d in p["docs"][:3] if d in docs)
                lines.append(f"    - {p['view']}" + (f" ({cites})" if cites else ""))
    ontologies = [d for d in docs.values() if source_type(d) == "ontology" and d.get("card")]
    if ontologies:
        lines.append("\nExisting ontologies in the corpus:")
        for d in ontologies:
            covered = sum(1 for c in inv["concepts"] if any(s["doc"] == d["id"] for s in c["sources"]))
            lines.append(f"- {doc_citation(d)}: {d['card'].get('stats', {}).get('classes', 0)} classes; "
                         f"{covered} inventory concepts")
    if max_cqs and inv.get("competency_questions"):
        lines.append("\nCompetency questions that the sources' models can answer (number of sources in brackets):")
        for q in [q for q in inv["competency_questions"] if q["question"] not in skip_cqs][:max_cqs]:
            lines.append(f"- {q['question']} ({len(q['docs'])})")
    return "\n".join(lines)
