"""LITMO (Ontologie-Entwicklungs-Tool) — FastAPI Backend: die Endpunkte. Die Logik liegt in den Modulen daneben."""

import concurrent.futures, contextvars, copy, hashlib, json, re, requests, traceback, uuid
from pathlib import Path
from typing import List
from datetime import datetime, timezone
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from ontology_edits import apply_edits
from ontology_evaluation import (concept_coverage, cq_coverage, cq_repeats, hierarchy_coverage, reasoner_check,
                                 select_holdout_cqs, structural_metrics, traceability, holdout_details,
                                 HOLDOUT_SELECTION_VERSION, evaluation_summary)

import llm
from store import save_dirty_sessions, saved_at, sessions
from llm import _run_llm_json, track_usage, _usage_log, usage_step, usage_summary, api_key_of, server_keys
from project import (apply_conventions, _context, context_block, _cq_text, declined_relations, DEFAULT_CONVENTIONS,
                     find_pattern, label_languages, MAX_CQS, _momo, named_notions, _norm, PATTERN_CATALOG,
                     session_prefixes)
from ontology_io import (generate_shacl_turtle, graph_prefixes_used, keep_from_previous, _looks_like_namespace,
                         ontology_to_turtle, rdf_graph_to_onto, validate_turtle)
from corpus import (analyze_file, build_card_prompt, build_inventory, CARD_EFFORT, clean_card, concept_key, _corpus,
                    CORPUS_DOC_LIMIT, CORPUS_EXTENSIONS, corpus_text, corpus_text_path, extract_full_text,
                    inventory_overview, _inventory_parts, migrate_concept_keys, CONCEPT_KEY_VERSION, ontology_card,
                    ONTOLOGY_EXTENSIONS, read_table,
                    source_type, _store_uploads, table_card, TABLE_EXTENSIONS, table_mapping_info)
from momo_steps import (build_context_answer_prompt, build_context_draft_prompt, build_cq_prompt,
                        build_notion_prompt, build_pattern_prompt,
                        _clean_questions, MAX_KEY_NOTIONS)
from vocabularies import (make_room_for_prefix, prefix_owner, RESERVED_PREFIXES, save_vocab_terms, vocab_terms, align_candidates, build_standards_prompt, check_external_refs, clean_standard,
                          fetch_vocabulary, known_prefixes, _parse_rdf, store_vocabulary, turtle_for_reasoning,
                          VOCAB_MAX_BYTES)
from editing import edit_error, edit_ontology, run_oops_and_fix, validate_and_fix_turtle
from testing import test_competency_questions
from generation import generate_modular
from documentation import build_documentation, to_html, to_markdown
from improvements import (build_gap_batches, restriction_candidates, build_property_vocab_prompt, clean_property_vocab, clean_upper_layer,
                          core_relation_ops, DECISION_KEYS, decision_store, decisions_report, DEFAULT_UPPER_LAYER,
                          ensure_core_module, ensure_upper_layer, GAP_KINDS, link_new_classes, _property_regression,
                          _reasoner_guard, remove_unused_upper, _unsatisfiable, upper_candidates, upper_layer_of)
from relations import approved_vocab, build_core_vocab_prompt, core_usage, relation_classes
from definitions import (accept_recommendations, check_definitions, conflict_list, conflict_summary, definition_ops,
                         enforce_definitions, recommend, set_decision)

class SafeJSONResponse(JSONResponse):
    """Wie JSONResponse; Text mit einzelnen Surrogaten (aus kaputten PDFs) geht als Unicode-Escape hinaus, statt dass
    die Projektliste oder das Projekt mit 500 nicht mehr laedt (wie beim Speichern in store.py)."""
    def render(self, content) -> bytes:
        try:
            return super().render(content)
        except UnicodeEncodeError:
            return json.dumps(content, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("ascii")

app = FastAPI(title="LITMO", default_response_class=SafeJSONResponse)
# gespeicherte Entscheidungen auf den neuen Begriffsschluessel umschluesseln, einmal je Projekt (DECISIONS 121)
for _s in sessions.values():
    migrate_concept_keys(_s)
# kein CORS: die Seite spricht nur mit ihrem eigenen Server; mit "*" konnte jede Webseite im selben Browser Projekte
# lesen und ueberschreiben (Code-Review 2026-10-29, DECISIONS 117)
# das JavaScript der Oberflaeche, eine Datei je Schritt (PLAN.md Phase 4, DECISIONS 116)
BASE_DIR = Path(__file__).resolve().parent   # Seiten und Skripte auch, wenn der Server woanders gestartet wird (F20)
app.mount("/js", StaticFiles(directory=BASE_DIR / "js"), name="js")
app.mount("/assets", StaticFiles(directory=BASE_DIR / "assets"), name="assets")   # Logo und Favicon (DECISIONS 129)

@app.middleware("http")
async def fresh_ui(request: Request, call_next):
    """Seite und Skripte immer neu pruefen (ETag macht das zu einem 304): sonst liefe nach einem Update eine alte
    Schritt-Datei gegen das neue Markup (F21)."""
    response = await call_next(request)
    p = request.url.path
    if p in ("/", "/app") or p.startswith("/js/"):
        response.headers["Cache-Control"] = "no-cache"
    return response

@app.middleware("http")
async def persist_sessions(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/") and request.method != "GET":
        try:
            await run_in_threadpool(save_dirty_sessions)
        except OSError as ex:
            print(f"WARNUNG: Sessions konnten nicht gespeichert werden: {ex}")
    return response

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    print(f"UNHANDLED ERROR:\n{traceback.format_exc()}")
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})

# ── Models ─────────────────────────────────────────────────────────────────────
class LLMConfig(BaseModel):
    provider: str
    api_key: str = ""     # leer: der Schluessel des Servers, falls er einen hat (DECISIONS 139)
    model: str
    base_url: str = ""

class SuggestStandardsRequest(BaseModel):
    session_id: str
    domain_description: str
    llm_config: LLMConfig

class GenerateRequest(BaseModel):
    session_id: str
    domain_description: str
    selected_standards: list = []
    llm_config: LLMConfig

class FeedbackRequest(BaseModel):
    session_id: str
    feedback: str
    llm_config: LLMConfig

class ExportRequest(BaseModel):
    session_id: str

class ShaclConstraint(BaseModel):
    property_name: str
    target_class: str
    min_count: int = None
    max_count: int = None
    datatype: str = ""      # z.B. "xsd:string", "xsd:integer", ""
    node_kind: str = ""     # "sh:IRI", "sh:Literal", ""

class GenerateShaclRequest(BaseModel):
    session_id: str
    constraints: list
    adjust_ontology: bool = False
    llm_config: LLMConfig | None = None

# ── MOMo (Modular Ontology Modeling) ──────────────────────────────────────────
class MomoContextRequest(BaseModel):
    """Generischer Request fuer die MOMo-Schritte 2-4."""
    session_id: str
    llm_config: LLMConfig

class SaveMomoRequest(BaseModel):
    """Speichert den konzeptuellen Stand (MOMo-Schritte 1-4) in der Session."""
    session_id: str
    use_case: str = ""
    data_sources: str = ""
    competency_questions: list = []
    key_notions: list = []
    patterns: list = []

# ── Endpoints ──────────────────────────────────────────────────────────────────
@app.get("/")
async def root():
    """Landing Page: beschreibt das Tool und die MOMo-Methodik."""
    return FileResponse(BASE_DIR / "landing.html")

@app.get("/app")
async def tool():
    """Das eigentliche Tool."""
    return FileResponse(BASE_DIR / "index.html")

@app.post("/api/session/create")
async def create_session():
    sid = str(uuid.uuid4())
    # cqs_shown_to_model: leer statt fehlend - nur Sessions von vor der Aufzeichnung bekommen den vorsichtigen
    # Ausschluss in _evaluate
    sessions[sid] = {"data_preview": "", "ontology": None, "feedback_log": [], "iterations": 0, "custom_prefixes": {},
                     "cqs_shown_to_model": [], "concept_key_version": CONCEPT_KEY_VERSION,
                     "momo": {"use_case": "", "data_sources": "", "competency_questions": [],
                              "key_notions": [], "patterns": []}}
    return {"session_id": sid}

PROJECT_FORMAT = "ontology-development-tool/project"

class SaveUiRequest(BaseModel):
    session_id: str
    ui: dict

# ── Projektauswahl ─────────────────────────────────────────────────────────────
# Der Browser merkt sich nur das offene Projekt; die Liste macht alle gespeicherten Projekte erreichbar. Ein eigener
# Titel unterscheidet Kopien desselben Projekts (der Ontologiename ist bei ihnen gleich).
def _project_title(s) -> str:
    title = (s.get("title") or "").strip()
    if title:
        return title
    name = ((s.get("ontology") or {}).get("ontology_name") or "").strip()
    if name:
        return name
    use_case = re.sub(r"\s+", " ", (s.get("momo") or {}).get("use_case") or "").strip()
    if len(use_case) > 60:
        return use_case[:60].rsplit(" ", 1)[0] + " …"
    return use_case or "Untitled project"

def _has_content(s) -> bool:
    momo = s.get("momo") or {}
    return bool(s.get("ontology") or momo.get("use_case") or momo.get("competency_questions")
                or (s.get("corpus") or {}).get("docs") or s.get("data_files"))

@app.get("/api/sessions")
def list_projects(current: str = ""):
    """Die gespeicherten Projekte, zuletzt geaenderte zuerst. Leere Projekte nur, wenn sie gerade offen sind."""
    out = []
    for sid, s in list(sessions.items()):
        if sid != current and not _has_content(s):
            continue
        onto, t = s.get("ontology") or {}, saved_at(sid)
        out.append({"session_id": sid, "title": _project_title(s), "named": bool((s.get("title") or "").strip()),
                    "use_case": re.sub(r"\s+", " ", (s.get("momo") or {}).get("use_case") or "").strip()[:200],
                    "iteration": s.get("iterations") or 0, "classes": len(onto.get("classes") or []),
                    "modules": len(onto.get("modules") or []),
                    "papers": len((s.get("corpus") or {}).get("docs") or []),
                    "updated": datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds") if t else None,
                    "current": sid == current})
    out.sort(key=lambda p: p["updated"] or "~", reverse=True)   # noch nicht gespeicherte zuerst
    return {"projects": out}

class RenameProjectRequest(BaseModel):
    session_id: str
    title: str = ""

@app.post("/api/session/rename")
def rename_project(req: RenameProjectRequest):
    """Eigener Titel des Projekts; leer: wieder Ontologiename bzw. Use Case."""
    s = _session(req.session_id)
    s["title"] = re.sub(r"\s+", " ", req.title).strip()[:120]
    return {"title": _project_title(s)}

@app.get("/api/session/{session_id}")
def get_project(session_id: str):
    """Vollstaendiger Projektstand, damit das Frontend nach Neuladen/Neustart weiterarbeiten kann."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Project not found")
    s = sessions[session_id]
    turtle = ""
    if s.get("ontology"):
        try:
            turtle = ontology_to_turtle(s["ontology"], s.get("_standards", []), session_prefixes(s))
        except Exception as ex:  # ein kaputtes Ontologie-Dict soll das Wiederherstellen nicht verhindern
            print(f"WARNUNG: Turtle fuer Session {session_id} nicht erzeugbar: {ex}")
    # den Kontext so, wie ihn die Kontext-Endpunkte liefern (mit Standardwerten, z.B. der oberen Schicht)
    return {"session_id": session_id, "turtle": turtle,
            "project": {**s, "context": _context_response(_context(s)), "suggested_standards": _standards(s),
                        "vocabularies": None}}     # die Termlisten bleiben auf dem Server (gross, nur dort gebraucht)

@app.post("/api/session/ui")
def save_ui(req: SaveUiRequest):
    """Speichert den reinen Oberflaechenzustand (aktueller Schritt, Turtle-Ansicht, Berichte …).
    Ein API-Key wird verworfen, falls das Frontend doch einen mitschickt."""
    if req.session_id not in sessions:
        raise HTTPException(status_code=404, detail="Project not found")
    ui = dict(req.ui)
    if isinstance(ui.get("llm"), dict):
        ui["llm"] = {k: v for k, v in ui["llm"].items() if k != "api_key"}
    sessions[req.session_id]["ui"] = ui
    return {"status": "ok"}

@app.get("/api/session/{session_id}/export")
def export_project(session_id: str):
    """Gesamter Projektzustand als Datei — zum Teilen oder Archivieren."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Project not found")
    project = sessions[session_id]
    name = ((project.get("ontology") or {}).get("ontology_name") or "ontology-project")
    fname = re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-") or "ontology-project"
    payload = {"format": PROJECT_FORMAT, "version": 1,
               "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "project": project}
    texts = {}
    for d in (project.get("corpus") or {}).get("docs", []):
        path = corpus_text_path(session_id, d["id"])
        if path.is_file():
            texts[d["id"]] = path.read_text(encoding="utf-8")
    if texts:
        payload["corpus_texts"] = texts  # Volltexte liegen nicht in der Session, gehoeren aber zum Projekt
    terms = {p: vocab_terms(v) for p, v in (project.get("vocabularies") or {}).items() if v.get("terms_file")}
    if terms:
        payload["vocabulary_terms"] = terms   # ebenso die Termlisten geladener Vokabulare (DECISIONS 100)
    return JSONResponse(payload, headers={"Content-Disposition": f'attachment; filename="{fname}.project.json"'})

@app.get("/api/session/{session_id}/documentation")
def export_documentation(session_id: str, format: str = "html"):
    """Dokumentation der Ontologie fuer die Expertenpruefung: ein Kapitel je Modul (DECISIONS 114)."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Project not found")
    session = sessions[session_id]
    if not (session.get("ontology") or {}).get("classes"):
        raise HTTPException(status_code=400, detail="Generate an ontology first")
    doc = build_documentation(session)
    fname = re.sub(r"[^A-Za-z0-9_-]+", "-", doc["title"]).strip("-") or "ontology"
    if format == "md":
        text, media, ext = to_markdown(doc), "text/markdown; charset=utf-8", "md"
    else:
        text, media, ext = to_html(doc), "text/html; charset=utf-8", "html"
    return Response(text, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{fname}-documentation.{ext}"'})

@app.get("/api/properties/usage")
def property_usage(session_id: str):
    """Rueckmeldung zum freigegebenen Kernvokabular nach einer Generierung (DECISIONS 119) - ohne Modellaufruf."""
    session = _session(session_id)
    vocab, onto = approved_vocab(session), session.get("ontology")
    if not vocab or not (onto or {}).get("properties"):
        return {"available": False}
    return {"available": True, "iteration": session.get("iterations"), **core_usage(onto, vocab)}

@app.post("/api/session/import")
async def import_project(file: UploadFile = File(...)):
    """Legt aus einer exportierten Projektdatei eine neue Session an."""
    try:
        payload = json.loads((await file.read()).decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as ex:
        raise HTTPException(status_code=400, detail=f"Not a valid project file: {ex}")
    if not isinstance(payload, dict) or payload.get("format") != PROJECT_FORMAT \
            or not isinstance(payload.get("project"), dict):
        raise HTTPException(status_code=400, detail="Not a project file of this tool (the field 'format' is missing or does not match)")
    project = payload["project"]
    project.pop("history", None)
    project.setdefault("momo", {"use_case": "", "data_sources": "", "competency_questions": [],
                                "key_notions": [], "patterns": []})
    sid = str(uuid.uuid4())
    if isinstance(project.get("corpus"), dict):  # Dokument-IDs werden zu Dateinamen - nur die eigene Form zulassen
        project["corpus"]["docs"] = [d for d in project["corpus"].get("docs") or []
                                     if isinstance(d, dict) and re.fullmatch(r"d[0-9a-f]{10}", str(d.get("id")))]
    known_docs = {d.get("id") for d in (project.get("corpus") or {}).get("docs", []) if isinstance(d, dict)}
    for doc_id, text in (payload.get("corpus_texts") or {}).items():
        if doc_id in known_docs and re.fullmatch(r"d[0-9a-f]{10}", str(doc_id)) and isinstance(text, str):
            path = corpus_text_path(sid, doc_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    vocabularies = project.get("vocabularies") if isinstance(project.get("vocabularies"), dict) else {}
    for pfx, voc in list(vocabularies.items()):
        terms = (payload.get("vocabulary_terms") or {}).get(pfx)
        if not voc.get("terms_file"):
            continue                                  # aeltere Exporte: Terme stehen im Eintrag selbst
        if isinstance(terms, dict) and isinstance(terms.get("classes"), list):
            voc["terms_file"] = save_vocab_terms(sid, pfx, terms)
        else:
            vocabularies.pop(pfx)                     # ohne Termliste nicht verwendbar - neu laden
    migrate_concept_keys(project)            # ein Export von vor DECISIONS 121
    sessions[sid] = project
    return {"session_id": sid}

@app.get("/api/resolve-prefix")
def resolve_prefix(prefix: str):
    """Schlägt einen Prefix via prefix.cc nach und gibt die Namespace-URI zurück."""
    prefix = prefix.strip().lower()
    if not prefix or not re.match(r'^[a-zA-Z][a-zA-Z0-9_\-]*$', prefix):
        raise HTTPException(status_code=400, detail="Invalid prefix")
    try:
        resp = requests.get(f"https://prefix.cc/{prefix}.file.json", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            uri = data.get(prefix)
            if uri:
                return {"prefix": prefix, "uri": uri}
        raise HTTPException(status_code=404, detail=f"Prefix '{prefix}' not found")
    except requests.Timeout:
        raise HTTPException(status_code=504, detail="prefix.cc cannot be reached (timeout)")
    except HTTPException:
        raise
    except Exception as ex:
        raise HTTPException(status_code=500, detail=str(ex))

class CustomPrefixRequest(BaseModel):
    session_id: str
    prefix: str
    uri: str

@app.post("/api/session/add-prefix")
async def add_custom_prefix(req: CustomPrefixRequest):
    if req.session_id not in sessions:
        raise HTTPException(status_code=404, detail="Project not found")
    prefix = req.prefix.strip().lower()
    uri = req.uri.strip()
    if not prefix or not uri:
        raise HTTPException(status_code=400, detail="Prefix und URI erforderlich")
    session = sessions[req.session_id]
    owner = prefix_owner(session, prefix, uri)
    if owner:
        raise HTTPException(status_code=400, detail=f"The prefix {prefix} is already used by {owner} for another namespace")
    session.setdefault("custom_prefixes", {})[prefix] = uri
    change = make_room_for_prefix(session, prefix)     # ein fremder Prefix bleibt, das Projekt weicht aus (DECISIONS 99)
    return {"status": "ok", "prefix": prefix, "uri": uri, "prefix_change": change,
            "conventions": _context(session)["conventions"]}

@app.delete("/api/session/remove-prefix")
async def remove_custom_prefix(session_id: str, prefix: str):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Project not found")
    sessions[session_id].get("custom_prefixes", {}).pop(prefix, None)
    return {"status": "ok"}

@app.post("/api/upload")
async def upload_data(files: List[UploadFile] = File(...), session_id: str = ""):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Project not found")
    analyzed = []
    for f in files:
        content = await f.read()
        fname = f.filename or "unbekannt"
        info = await run_in_threadpool(analyze_file, content, fname)
        analyzed.append({"name": fname, **info})
    session = sessions[session_id]
    _store_uploads(session, analyzed, append=False)
    combined = session["data_preview"]
    return {"status": "ok", "preview": combined[:1500] + ("..." if len(combined) > 1500 else ""),
            "files": [{"name": f["name"], "kind": f["kind"],
                       "chars": len(f["full_text"]) if f["kind"] == "text" else None} for f in analyzed]}

@app.post("/api/upload-feedback-files")
async def upload_feedback_files(files: List[UploadFile] = File(...), session_id: str = ""):
    """Haengt zusaetzliche Dateien an die bestehende Datenvorschau an."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Project not found")
    analyzed = []
    for f in files:
        content = await f.read()
        fname = f.filename or "unbekannt"
        info = await run_in_threadpool(analyze_file, content, fname)
        analyzed.append({"name": fname, "suffix": " (feedback attachment)", **info})
    _store_uploads(sessions[session_id], analyzed, append=True)
    return {"status": "ok", "files": [f["name"] for f in analyzed]}

@app.post("/api/load-ontology")
async def load_ontology(file: UploadFile = File(...), session_id: str = ""):
    """Laedt eine bestehende Ontologie (TTL/RDF/OWL/JSON-LD) und bereitet die Session fuer Feedback vor."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Project not found")
    content = await file.read()
    fname = (file.filename or "").lower()
    try:
        from rdflib import Graph
        g = Graph(bind_namespaces="core")
        if fname.endswith((".ttl", ".turtle")):
            g.parse(data=content.decode("utf-8", errors="replace"), format="turtle")
        elif fname.endswith(".jsonld"):
            g.parse(data=content.decode("utf-8", errors="replace"), format="json-ld")
        else:
            g.parse(data=content.decode("utf-8", errors="replace"), format="xml")
        turtle = g.serialize(format="turtle")
        onto = rdf_graph_to_onto(g, turtle)
        import_report = onto.pop("import_report", None)
    except Exception as ex:
        raise HTTPException(status_code=400, detail="The file could not be parsed: " + str(ex))

    session = sessions[session_id]
    _adopt_prefixes(session, graph_prefixes_used(g, onto))
    session["ontology"] = onto
    session["iterations"] = 0
    session["feedback_log"] = []
    for k in ("cq_test_report", "holdout_test_report", "evaluation", "evaluation_previous"):   # vorige Ontologie (T12)
        session.pop(k, None)
    turtle = ontology_to_turtle(onto, session.get("_standards", []), session_prefixes(session))
    return {"ontology": onto, "turtle": turtle, "import_report": import_report}

@app.get("/api/config")
def server_config():
    """Was die Seite ueber den Server wissen muss: fuer welche Anbieter er einen Schluessel hat (nur ja/nein)."""
    return {"server_keys": server_keys()}

@app.post("/api/models")
def list_models(cfg: LLMConfig):
    """Verfuegbare Modelle eines OpenAI-kompatiblen Anbieters (GET /v1/models). Bei KI:connect sind das die
    Deployment-Namen, die chat/completions als "model" erwartet."""
    if cfg.provider != "rwthgpt":
        raise HTTPException(status_code=400, detail="Model listing is only supported for RWTHgpt / KI:connect")
    from openai import OpenAI
    try:
        client = OpenAI(api_key=api_key_of(cfg), base_url=cfg.base_url or "https://chat.kiconnect.nrw/api/v1")
        return {"models": sorted({m.id for m in client.models.list()})}
    except Exception as ex:
        raise HTTPException(status_code=502, detail=type(ex).__name__ + ": " + str(ex)[:200])

@app.post("/api/suggest-standards")
def suggest_standards(req: SuggestStandardsRequest):
    if req.session_id not in sessions:
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        result = llm.call_llm_json(req.llm_config, build_standards_prompt(req.domain_description,
                                                                       context_block(sessions[req.session_id])))
        standards = [clean_standard(s) for s in result.get("standards", []) if isinstance(s, dict)]
    except HTTPException:
        raise
    except Exception as ex:
        raise HTTPException(status_code=500, detail=type(ex).__name__ + ": " + str(ex))
    session = sessions[req.session_id]
    # bereits geladene Vokabulare gleicher Praefixe bleiben gueltig
    for s in standards:
        voc = (session.get("vocabularies") or {}).get(s.get("prefix"))
        if voc and voc.get("namespace") == s.get("namespace"):
            counts = voc.get("counts") or {k: len(voc.get(k) or []) for k in ("classes", "properties")}
            s["vocabulary"] = {**counts, "source": voc["source"], "truncated": voc.get("truncated", False)}
    session["suggested_standards"] = standards
    return {"standards": standards}

class StandardUpdateRequest(BaseModel):
    session_id: str
    index: int = -1          # -1: neuen Standard anlegen
    fields: dict = {}
    remove: bool = False

def _standards(session) -> list:
    session["suggested_standards"] = [clean_standard(s) for s in session.get("suggested_standards") or []]
    return session["suggested_standards"]

@app.post("/api/standards/update")
def update_standard(req: StandardUpdateRequest):
    """Das Team korrigiert Namespace, Praefix, Download-URL oder Entscheidung, legt einen Standard an oder entfernt ihn."""
    session = _session(req.session_id)
    standards = _standards(session)
    if req.index >= len(standards):
        raise HTTPException(status_code=400, detail="Unknown standard")
    if req.remove:
        if req.index >= 0:
            gone = standards.pop(req.index)
            if not any(s.get("prefix") == gone.get("prefix") for s in standards):
                (session.get("vocabularies") or {}).pop(gone.get("prefix"), None)
        return {"standards": standards}
    allowed = {k: v for k, v in (req.fields or {}).items()
               if k in ("name", "namespace", "prefix", "documentation_url", "download_url", "decision", "reuse_hint")}
    if allowed.get("namespace") and not _looks_like_namespace(allowed["namespace"]):
        raise HTTPException(status_code=400, detail="That is not a namespace: it must end in # or / (on a host for "
                                                    "persistent namespaces); specification and documentation pages are "
                                                    "not namespaces - use the download URL for a file")
    if "prefix" in allowed and allowed["prefix"] and not re.match(r"^[a-z][\w-]*$", str(allowed["prefix"])):
        raise HTTPException(status_code=400, detail="A prefix starts with a lowercase letter: letters, digits, _ and -")
    if allowed.get("prefix"):
        current = standards[req.index] if req.index >= 0 else {}
        owner = prefix_owner(session, allowed["prefix"], allowed.get("namespace") or current.get("namespace") or "",
                             exclude=current)
        if owner:
            raise HTTPException(status_code=400, detail=f"The prefix {allowed['prefix']} is already used by {owner} "
                                                        "for another namespace")
    base = standards[req.index] if req.index >= 0 else {}
    old_ns = base.get("namespace")
    merged = clean_standard({**base, **allowed})
    if allowed.get("prefix"):
        merged["prefix"] = allowed["prefix"]
    if merged.get("namespace") != old_ns:
        merged.pop("vocabulary", None)           # anderer Namespace: das geladene Vokabular gilt nicht mehr
    if req.index >= 0:
        standards[req.index] = merged
    else:
        standards.append(merged)
    change = make_room_for_prefix(session, merged["prefix"]) if allowed.get("prefix") else {}
    return {"standards": standards, "prefix_change": change, "conventions": _context(session)["conventions"]}

class StandardLoadRequest(BaseModel):
    session_id: str
    index: int

@app.post("/api/standards/load")
def load_standard(req: StandardLoadRequest):
    """Laedt das Vokabular eines Standards aus dem Netz (Download-URL, bekannte Quelle, Namespace)."""
    session = _session(req.session_id)
    standards = _standards(session)
    if not 0 <= req.index < len(standards):
        raise HTTPException(status_code=400, detail="Unknown standard")
    s = standards[req.index]
    try:
        g, source = fetch_vocabulary(s)
        store_vocabulary(session, s, g, source, req.session_id)
    except ValueError as ex:
        s["load_error"] = str(ex)[:500]
        raise HTTPException(status_code=422, detail=f"{s['name']} could not be loaded: {ex}. Upload the file "
                                                    "instead, or enter a download URL.")
    return {"standards": standards, "prefix_change": s.pop("prefix_change", {}),
            "conventions": _context(session)["conventions"]}

@app.post("/api/standards/upload")
async def upload_standard(file: UploadFile = File(...), session_id: str = "", index: int = -1):
    """Ein Vokabular als Datei (Turtle, RDF/XML, JSON-LD); index -1 legt einen neuen Standard an."""
    session = _session(session_id)
    standards = _standards(session)
    content = await file.read()
    if len(content) > VOCAB_MAX_BYTES:
        raise HTTPException(status_code=400, detail=f"The file is larger than {VOCAB_MAX_BYTES // 1_000_000} MB")
    try:
        g = _parse_rdf(content.decode("utf-8", errors="replace"), "", file.filename or "")
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=f"{file.filename}: {ex}")
    if 0 <= index < len(standards):
        s = standards[index]
    else:
        from rdflib import URIRef
        from rdflib.namespace import RDF, OWL, RDFS
        onto_node = next(g.subjects(RDF.type, OWL.Ontology), None)
        title = (onto_node is not None and (g.value(onto_node, RDFS.label) or
                                            g.value(onto_node, URIRef("http://purl.org/dc/terms/title")))) or file.filename
        s = clean_standard({"name": str(title), "decision": "align"})
        standards.append(s)
    try:
        store_vocabulary(session, s, g, f"uploaded file {file.filename}", session_id)
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))
    return {"standards": standards, "prefix_change": s.pop("prefix_change", {}),
            "conventions": _context(session)["conventions"]}

# ── MOMo Endpoints ─────────────────────────────────────────────────────────────
def _session(session_id):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Project not found")
    return sessions[session_id]

@app.post("/api/momo/save")
def save_momo(req: SaveMomoRequest):
    """MOMo Schritte 1-4: konzeptuellen Stand speichern."""
    session = _session(req.session_id)
    session["momo"] = {
        "use_case": req.use_case,
        "data_sources": req.data_sources,
        "competency_questions": [c for c in req.competency_questions if _cq_text(c)],
        "key_notions": named_notions(req.key_notions),   # leere Formularzeilen sind keine Key Notions
        "patterns": req.patterns,
    }
    return {"status": "ok", "momo": session["momo"]}

# ── Literatur-Endpunkte ────────────────────────────────────────────────────────
# Das Frontend schickt jedes Paper einzeln (mehrere parallel) an /extract. So braucht der Server keinen
# Hintergrundjob, der API-Key bleibt im Browser, der Fortschritt ist sichtbar und ein abgebrochener Lauf
# setzt einfach bei den noch offenen Papern wieder an.
class CorpusDocRequest(BaseModel):
    session_id: str
    doc_id: str

class CorpusExtractRequest(BaseModel):
    session_id: str
    doc_id: str
    llm_config: LLMConfig

@app.post("/api/corpus/upload")
async def upload_corpus(files: List[UploadFile] = File(...), session_id: str = ""):
    """Haengt Quellen an den Korpus an; dieselbe Datei (gleicher Inhalt) wird nur einmal aufgenommen.
    Paper warten auf die LLM-Extraktion, bestehende Ontologien werden sofort zur Card, Begriffstabellen
    warten auf die Zuordnung ihrer Spalten."""
    session = _session(session_id)
    corpus = _corpus(session)
    by_hash = {d["sha1"]: d for d in corpus["docs"]}
    added, skipped = [], []
    for f in files:
        name = f.filename or "paper"
        content = await f.read()
        fn = name.lower()
        kind = ("paper" if fn.endswith(CORPUS_EXTENSIONS) else "ontology" if fn.endswith(ONTOLOGY_EXTENSIONS)
                else "glossary" if fn.endswith(TABLE_EXTENSIONS) else None)
        if not kind:
            skipped.append({"name": name, "reason": "unsupported file type"})
            continue
        digest = hashlib.sha1(content).hexdigest()
        known = by_hash.get(digest)
        path = corpus_text_path(session_id, known["id"] if known else "d" + digest[:10])
        if known and (kind == "ontology" or path.is_file()):
            skipped.append({"name": name, "reason": "already in the corpus" +
                            (f" as {known['name']}" if known["name"] != name else "")})
            continue
        if kind != "paper":
            try:
                if kind == "ontology":
                    card = await run_in_threadpool(ontology_card, content, name)
                    stored = None
                else:
                    table = await run_in_threadpool(read_table, content, name)
                    stored = json.dumps(table, ensure_ascii=False)
            except Exception as ex:
                skipped.append({"name": name, "reason": f"could not be read: {str(ex)[:200] or type(ex).__name__}"})
                continue
            if stored is not None:  # Tabelle als Datei, damit die Spalten spaeter neu zugeordnet werden koennen
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(stored, encoding="utf-8")
            if known:
                continue
            doc = {"id": path.stem, "name": name, "sha1": digest, "source_type": kind, "chars": len(content),
                   "pages": None, "truncated": False, "error": "", "extracted_at": "", "usage": None,
                   "status": "done" if kind == "ontology" else "mapping",
                   "card": card if kind == "ontology" else None,
                   "mapping": None if kind == "ontology" else {"sheets": table_mapping_info(table)}}
            if kind == "ontology":
                doc["extracted_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            corpus["docs"].append(doc)
            by_hash[digest] = doc
            added.append(doc["id"])
            continue
        try:
            text, pages = await run_in_threadpool(corpus_text, content, name)
        except Exception as ex:
            skipped.append({"name": name, "reason": f"could not be read ({type(ex).__name__})"})
            continue
        if len(re.sub(r"\[page \d+\]|\s", "", text)) < 500:
            skipped.append({"name": name, "reason": "no extractable text - scanned PDF without OCR?"})
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        if known:  # z.B. nach dem Import eines Projekts ohne Volltexte: nur den Text wiederherstellen
            continue
        doc = {"id": path.stem, "name": name, "sha1": digest, "source_type": "paper", "chars": len(text),
               "pages": pages, "truncated": len(text) > CORPUS_DOC_LIMIT, "status": "pending", "error": "",
               "card": None, "extracted_at": "", "usage": None, "mapping": None}
        corpus["docs"].append(doc)
        by_hash[digest] = doc
        added.append(doc["id"])
    return {"docs": corpus["docs"], "added": added, "skipped": skipped}

@app.post("/api/corpus/extract")
def extract_paper(req: CorpusExtractRequest):
    return _with_usage(lambda: _extract_paper(req))

def _extract_paper(req: CorpusExtractRequest):
    session = _session(req.session_id)
    doc = next((d for d in _corpus(session)["docs"] if d["id"] == req.doc_id), None)
    if not doc:
        raise HTTPException(status_code=404, detail="Paper not found in the corpus")
    if source_type(doc) != "paper":
        raise HTTPException(status_code=400, detail="Only papers are extracted by the model")
    path = corpus_text_path(req.session_id, doc["id"])
    if not path.is_file():
        raise HTTPException(status_code=409, detail="The full text of this paper is missing on the server - "
                                                    "upload the file again")
    text = path.read_text(encoding="utf-8")
    try:
        with usage_step("Paper card"):
            card = clean_card(llm.call_llm_json(req.llm_config, build_card_prompt(session, doc, text),
                                                effort=CARD_EFFORT), text)
    except Exception as ex:
        msg = ex.detail if isinstance(ex, HTTPException) else f"{type(ex).__name__}: {str(ex)[:300]}"
        doc["status"], doc["error"] = "error", str(msg)
        if isinstance(ex, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=str(msg))
    log = _usage_log.get() or []
    u = usage_summary(log)
    # Nur vorhandene Schluessel ersetzen: eine parallele Speicherung iteriert womoeglich gerade ueber das Dict
    doc["card"] = card
    doc["usage"] = {"input_tokens": u["input_tokens"], "output_tokens": u["output_tokens"]}
    doc["extracted_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    doc["status"], doc["error"] = "done", ""
    return {"doc": doc}

class CorpusMappingRequest(BaseModel):
    session_id: str
    doc_id: str
    sheet: str
    columns: dict   # {"term": 0, "definition": 2, "broader": null, "synonyms": null, "uri": null}

@app.post("/api/corpus/map-columns")
def map_table_columns(req: CorpusMappingRequest):
    """Wendet die bestaetigte Spaltenzuordnung einer Begriffstabelle an."""
    session = _session(req.session_id)
    doc = next((d for d in _corpus(session)["docs"] if d["id"] == req.doc_id), None)
    if not doc or source_type(doc) != "glossary":
        raise HTTPException(status_code=404, detail="Concept table not found in the corpus")
    path = corpus_text_path(req.session_id, doc["id"])
    if not path.is_file():
        raise HTTPException(status_code=409, detail="The table is missing on the server - upload the file again")
    table = json.loads(path.read_text(encoding="utf-8"))
    card = table_card(table, req.sheet, req.columns, doc["name"])
    if not card["concepts"]:
        raise HTTPException(status_code=400, detail="The chosen term column is empty")
    doc["card"] = card
    doc["mapping"] = {**(doc.get("mapping") or {}), "chosen": {"sheet": req.sheet, "columns": req.columns}}
    doc["extracted_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    doc["status"], doc["error"] = "done", ""
    return {"doc": doc}

@app.post("/api/corpus/remove")
def remove_corpus_doc(req: CorpusDocRequest):
    session = _session(req.session_id)
    corpus = _corpus(session)
    if not any(d["id"] == req.doc_id for d in corpus["docs"]):
        raise HTTPException(status_code=404, detail="Paper not found in the corpus")
    corpus["docs"] = [d for d in corpus["docs"] if d["id"] != req.doc_id]
    try:
        corpus_text_path(req.session_id, req.doc_id).unlink(missing_ok=True)
    except OSError:
        pass
    return {"docs": corpus["docs"]}

@app.post("/api/corpus/inventory")
def corpus_inventory(req: MomoContextRequest):
    """Fuehrt alle Paper Cards zum Begriffsinventar zusammen."""
    return _with_usage(lambda: {"inventory": build_inventory(_session(req.session_id), req.llm_config)})

# ── Projektkontext-Endpunkte ───────────────────────────────────────────────────
class ContextDraftRequest(BaseModel):
    session_id: str
    llm_config: LLMConfig
    extra_requirements: str = ""

class ContextAnswerRequest(BaseModel):
    session_id: str
    llm_config: LLMConfig
    answers: list = []   # [{"question": "...", "answer": "..."}]

class ContextSaveRequest(BaseModel):
    session_id: str
    markdown: str = None
    conventions: dict = None
    questions: list = None
    clear_source: bool = False
    upper_layer: list = None          # die vom Team angepasste obere Schicht
    use_upper_layer: bool = None      # die Generierung haengt die obersten Klassen darunter (DECISIONS 97)
    reset_upper_layer: bool = False   # zurueck zur Vorgabe

def _context_response(ctx):
    return {"markdown": ctx["markdown"], "questions": ctx["questions"], "conventions": ctx["conventions"],
            "source_name": ctx["source_name"], "source_chars": len(ctx["source_text"]),
            "upper_layer": ctx.get("upper_layer") or DEFAULT_UPPER_LAYER, "upper_layer_default": not ctx.get("upper_layer"),
            "use_upper_layer": ctx.get("use_upper_layer", True) is not False}

@app.post("/api/context/upload")
async def upload_context_file(file: UploadFile = File(...), session_id: str = ""):
    """Bestehende Kontextdatei des Teams als Quelle fuer den Entwurf (im Volltext, nicht als Datenvorschau)."""
    ctx = _context(_session(session_id))
    content = await file.read()
    ctx["source_text"] = await run_in_threadpool(extract_full_text, content, file.filename or "context.txt")
    ctx["source_name"] = file.filename or "context"
    return _context_response(ctx)

@app.post("/api/context/draft")
def draft_context(req: ContextDraftRequest):
    """Entwurf des Projektkontexts aus Use Case, Daten und ggf. Kontextdatei, plus gezielte Rueckfragen."""
    session = _session(req.session_id)
    ctx = _context(session)
    result = _run_llm_json(req.llm_config, build_context_draft_prompt(session, req.extra_requirements))
    ctx["markdown"] = str(result.get("markdown") or "").strip()
    ctx["questions"] = _clean_questions(result.get("questions"))
    return _context_response(ctx)

@app.post("/api/context/answer")
def answer_context_questions(req: ContextAnswerRequest):
    """Arbeitet die Antworten des Teams in das Dokument ein."""
    session = _session(req.session_id)
    ctx = _context(session)
    answers = [a for a in req.answers if isinstance(a, dict) and str(a.get("answer") or "").strip()]
    if not answers:
        raise HTTPException(status_code=400, detail="No answers given")
    result = _run_llm_json(req.llm_config, build_context_answer_prompt(ctx["markdown"], answers))
    if str(result.get("markdown") or "").strip():
        ctx["markdown"] = str(result["markdown"]).strip()
    answered = {a.get("question") for a in answers}
    remaining = [q for q in ctx["questions"] if q["question"] not in answered]
    ctx["questions"] = _clean_questions(remaining + list(result.get("questions") or []))
    return _context_response(ctx)

@app.post("/api/context/save")
def save_context(req: ContextSaveRequest):
    """Speichert Bearbeitungen am Dokument, das Konventionen-Formular und verworfene Fragen."""
    ctx = _context(_session(req.session_id))
    if req.markdown is not None:
        ctx["markdown"] = req.markdown
    if req.conventions is not None:
        conv = {**DEFAULT_CONVENTIONS, **{k: str(v) for k, v in req.conventions.items() if k in DEFAULT_CONVENTIONS}}
        own = conv["prefix"].strip().lower()
        session = _session(req.session_id)
        used = {s.get("prefix"): s.get("name") for s in session.get("suggested_standards") or [] if isinstance(s, dict)}
        used.update({p: v.get("name") for p, v in (session.get("vocabularies") or {}).items()})
        used.update({p: f"the additional prefix {p}" for p in session.get("custom_prefixes") or {}})
        used.update({p: f"the built-in namespace {ns}" for p, ns in RESERVED_PREFIXES.items()})
        if own and own in used:   # die Prefixe der Vokabulare bleiben (DECISIONS 99)
            raise HTTPException(status_code=400, detail=f"The prefix {own} belongs to {used[own] or own}; choose "
                                                        "another prefix for your ontology")
        ctx["conventions"] = conv
    if req.questions is not None:
        ctx["questions"] = _clean_questions(req.questions)
    if req.reset_upper_layer:
        ctx.pop("upper_layer", None)
    elif req.upper_layer is not None:
        ctx["upper_layer"] = clean_upper_layer(req.upper_layer)
    if req.use_upper_layer is not None:
        ctx["use_upper_layer"] = bool(req.use_upper_layer)
    if req.clear_source:
        ctx["source_name"], ctx["source_text"] = "", ""
    return _context_response(ctx)

# ── Entschiedene Definitionen (PLAN.md Phase 1, DECISIONS 83) ───────────────────
class DefinitionDecisionRequest(BaseModel):
    session_id: str
    key: str
    decision: dict | None = None    # None: Entscheidung zuruecknehmen

class DefinitionKeysRequest(BaseModel):
    session_id: str
    keys: list[str] | None = None   # None: alle noch nicht entschiedenen
    llm_config: LLMConfig | None = None

def _definitions_response(session, **extra):
    conflicts = conflict_list(session)
    return {"conflicts": conflicts, "summary": conflict_summary(conflicts), **extra}

@app.get("/api/definitions")
def get_definitions(session_id: str):
    return _definitions_response(_session(session_id))

@app.post("/api/definitions/decide")
def decide_definition(req: DefinitionDecisionRequest):
    session = _session(req.session_id)
    set_decision(session, req.key, req.decision)
    return _definitions_response(session)

@app.post("/api/definitions/accept")
def accept_definitions(req: DefinitionKeysRequest):
    session = _session(req.session_id)
    return _definitions_response(session, result=accept_recommendations(session, req.keys))

@app.post("/api/definitions/recommend")
def recommend_definitions(req: DefinitionKeysRequest):
    session = _session(req.session_id)
    if not req.llm_config:
        raise HTTPException(status_code=400, detail="Configure the LLM first")
    return _with_usage(lambda: _definitions_response(session, result=recommend(session, req.llm_config, req.keys)))

@app.post("/api/definitions/apply")
def apply_definitions(req: DefinitionKeysRequest):
    """Reparaturaktion fuer eine bestehende Ontologie: abweichende Beschreibungen ersetzen, fehlende Klassen einer
    Entscheidung anlegen. Ohne Modell - die Texte hat das Team entschieden."""
    session = _session(req.session_id)
    onto = session.get("ontology")
    if not onto:
        raise HTTPException(status_code=400, detail="Generate an ontology first")
    ops = definition_ops(onto, session)
    if not ops:
        raise HTTPException(status_code=400, detail="Every decided definition is already in the ontology")
    new, rep = apply_edits(onto, ops, label_languages(session)[0], known_prefixes(session))
    if not rep["applied"]:
        raise HTTPException(status_code=400, detail="No change could be applied: " +
                            "; ".join(r["reason"] for r in rep["rejected"][:5]))
    turtle = ontology_to_turtle(new, session.get("_standards", []), session_prefixes(session, new))
    session["ontology"] = new
    session["feedback_log"] = ((session.get("feedback_log") or []) +
                               [{"feedback": "Apply the team's decided definitions",
                                 "summary": "; ".join(a["summary"] for a in rep["applied"])[:600]}])[-30:]
    session["iterations"] = session.get("iterations", 1) + 1
    return {"ontology": new, "turtle": turtle, "iteration": session["iterations"],
            "summary": {"applied": [a["summary"] for a in rep["applied"]],
                        "rejected": [f"{r['op'].get('name')}: {r['reason']}" for r in rep["rejected"]]}}

@app.get("/api/momo/state")
def get_momo(session_id: str):
    return {"momo": _momo(_session(session_id))}

SUGGEST_CQS_SHOWN = 40   # so viele Literatur-CQs sieht der CQ-Vorschlag

@app.post("/api/momo/suggest-cqs")
def suggest_cqs(req: MomoContextRequest):
    """MOMo Schritt 2: Competency Questions vorschlagen."""
    session = _session(req.session_id)
    momo = _momo(session)
    existing = [c for c in momo.get("competency_questions", []) if _cq_text(c)]
    if len(existing) >= MAX_CQS:
        return {"competency_questions": [], "limit_reached": True}
    # die Hold-out-Fragen zuerst waehlen und dem Vorschlag nicht zeigen (DECISIONS 137): bei 37 Literatur-CQs sah er
    # vorher alle, und fuer den Hold-out-Test blieb keine (Wein-Durchlauf v0.2)
    held, _ = holdout_set(session)
    result = _run_llm_json(req.llm_config, build_cq_prompt(
        momo.get("use_case", ""), momo.get("data_sources", ""), session.get("data_preview", ""), existing,
        context_block(session), inventory_overview(session, max_central=25, max_cqs=SUGGEST_CQS_SHOWN, max_conflicts=0,
                                                   skip_cqs=set(held))))
    # Diese Literatur-CQs hat das Modell gesehen - sie taugen nicht mehr als Hold-out (siehe _evaluate)
    inv = (session.get("corpus") or {}).get("inventory") or {}
    shown = [q["question"] for q in inv.get("competency_questions") or [] if q["question"] not in held][:SUGGEST_CQS_SHOWN]
    session["cqs_shown_to_model"] = list(dict.fromkeys((session.get("cqs_shown_to_model") or []) + shown))
    taken = {_norm(_cq_text(c)) for c in existing}
    fresh = [c for c in result.get("competency_questions", [])
             if isinstance(c, dict) and _cq_text(c) and _norm(_cq_text(c)) not in taken]
    return {"competency_questions": fresh[:MAX_CQS - len(existing)]}

@app.post("/api/momo/suggest-notions")
def suggest_notions(req: MomoContextRequest):
    """MOMo Schritt 3: Key Notions (spaetere Module) identifizieren."""
    session = _session(req.session_id)
    momo = _momo(session)
    existing = named_notions(momo.get("key_notions"))
    result = _run_llm_json(req.llm_config, build_notion_prompt(
        momo.get("use_case", ""), momo.get("data_sources", ""), momo.get("competency_questions", []), existing,
        context_block(session), inventory_overview(session, max_central=40, max_conflicts=0)))
    # Nur Vorschlaege, die noch fehlen — und nicht mehr, als insgesamt sinnvoll ist.
    taken = {_norm(n["name"]) for n in existing}
    fresh = [n for n in result.get("key_notions", [])
             if isinstance(n, dict) and n.get("name") and _norm(n["name"]) not in taken]
    return {"key_notions": fresh[:max(0, MAX_KEY_NOTIONS - len(existing))]}

class PatternSuggestRequest(MomoContextRequest):
    only: list = []   # nur fuer diese Key Notions (neu hinzugekommene); leer = fuer alle

@app.post("/api/momo/suggest-patterns")
def suggest_patterns(req: PatternSuggestRequest):
    """MOMo Schritt 4: Ontology Design Patterns je Key Notion vorschlagen."""
    session = _session(req.session_id)
    momo = _momo(session)
    notions = named_notions(momo.get("key_notions"))
    if req.only:
        wanted = {_norm(n) for n in req.only if isinstance(n, str)}
        notions = [n for n in notions if _norm(n["name"]) in wanted]
    if not notions:   # sonst erfindet das Modell die Key Notions selbst
        raise HTTPException(status_code=400, detail="There are no named key notions yet (MOMo step 3)")
    result = _run_llm_json(req.llm_config, build_pattern_prompt(
        momo.get("use_case", ""), notions, momo.get("competency_questions", []),
        context_block(session)))
    names = {_norm(n["name"]): n["name"] for n in notions}
    # nur Vorschlaege fuer die angefragten Key Notions, mit deren Schreibweise
    choices = [p for p in result.get("patterns", []) if isinstance(p, dict) and _norm(p.get("notion")) in names]
    for p in choices:
        p["notion"] = names[_norm(p["notion"])]
    return {"patterns": [_validate_pattern_choice(p) for p in choices]}

def _validate_pattern_choice(choice: dict) -> dict:
    """Bindet die LLM-Wahl an den Katalog: unbekannte Patterns werden verworfen statt uebernommen."""
    pat = find_pattern(choice.get("pattern"))
    if choice.get("pattern") and not pat:
        choice["rationale"] = ("(Suggested \"" + str(choice["pattern"]) + "\" is not in the ODPA repository - "
                               "build from scratch or choose one manually.) " + (choice.get("rationale") or "")).strip()
    choice["pattern"] = pat["id"] if pat else None
    choice["alternatives"] = [a["id"] for a in map(find_pattern, choice.get("alternatives") or []) if a]
    fit = str(choice.get("fit") or "").strip().lower()
    if not pat:
        fit = "none"
    elif fit not in ("strong", "partial"):
        fit = "partial"  # ohne Bewertung nicht als starken Treffer behandeln
    choice["fit"] = fit
    # Nur starke Treffer gehen automatisch als Template in die Generierung; Teiltreffer waehlt das Team bewusst.
    choice["selected"] = fit == "strong"
    return choice

@app.get("/api/patterns")
def list_patterns():
    """ODPA-Katalog fuer die Pattern-Auswahl im Frontend."""
    return {
        "source": PATTERN_CATALOG.get("source", ""),
        "commit": PATTERN_CATALOG.get("commit", ""),
        "patterns": [{**{k: p.get(k, "") for k in ("id", "name", "intent", "domains", "url", "owl_url", "diagram_url")},
                      "classes": [c["name"] for c in p.get("classes", [])],
                      "properties": [x["name"] for x in p.get("object_properties", []) + p.get("datatype_properties", [])]}
                     for p in PATTERN_CATALOG["patterns"]],
    }

class CQTestRequest(BaseModel):
    session_id: str
    llm_config: LLMConfig
    fresh: bool = False   # gespeicherte Beispieldaten und Abfragen verwerfen, alles neu schreiben lassen

@app.post("/api/momo/test-cqs")
def test_cqs(req: CQTestRequest):
    """MOMo: Competency Questions als SPARQL-Testfaelle gegen die Ontologie ausfuehren."""
    session = _session(req.session_id)
    onto = session.get("ontology")
    if not onto:
        raise HTTPException(status_code=400, detail="Generate an ontology first")
    cqs = [_cq_text(c) for c in _momo(session).get("competency_questions", []) if _cq_text(c)]
    if not cqs:
        raise HTTPException(status_code=400, detail="There are no competency questions yet")
    turtle = ontology_to_turtle(onto, session.get("_standards", []), session_prefixes(session))
    def run():
        try:
            result = test_competency_questions(turtle, cqs, req.llm_config, context_block(session),
                                               previous=None if req.fresh else (session.get("cq_test_report") or {}).get("result"))
        except HTTPException:
            raise
        except Exception as ex:
            raise HTTPException(status_code=500, detail=type(ex).__name__ + ": " + str(ex))
        # auch serverseitig merken: die Evaluation baut darauf auf (gilt nur fuer diese Iteration)
        session["cq_test_report"] = {"iteration": session.get("iterations"), "result": result}
        return result
    return _with_usage(run)

# ── Evaluation (Stufe A aus EVALUATION.md) ─────────────────────────────────────
# Nur deterministische Masse - kein Modell als Gutachter (die Literatur zeigt, dass LLM-Urteile ueber Ontologien
# nur maessig mit Experten uebereinstimmen). Modellaufrufe gibt es nur, um CQs in SPARQL zu uebersetzen; ob sie
# abgedeckt sind, entscheidet rdflib.
class EvaluateRequest(BaseModel):
    session_id: str
    llm_config: LLMConfig | None = None
    holdout: bool = True
    fresh: bool = False   # CQ-Tests ohne gespeicherte Beispieldaten und Abfragen (DECISIONS 71)
    repeats: int = 1      # mehrere unabhaengige CQ-Tests, Mittel und Streuung (DECISIONS 124)

HOLDOUT_CQS = 10
EVAL_REPEATS = 3          # "Evaluate 3x" (PLAN.md Phase 6)

def _holdout_shown(session, inv, team_cqs):
    """Die Literatur-CQs, die der CQ-Vorschlag gesehen hat, und ein Hinweis, wenn das nicht aufgezeichnet ist."""
    shown = session.get("cqs_shown_to_model")
    if shown is None and inv and team_cqs:
        shown = [q["question"] for q in (inv.get("competency_questions") or [])[:SUGGEST_CQS_SHOWN]]
        return shown, ("Hold-out: it is not recorded which literature questions the competency-question suggestions "
                       f"saw, so the first {len(shown)} were excluded to be safe.")
    return shown or [], None

def holdout_set(session) -> tuple:
    """Die Hold-out-Fragen des Projekts (DECISIONS 133): einmal ausgewaehlt und gespeichert, damit jede Evaluation
    dieselben testet; was nicht mehr in Frage kommt (eine eigene Frage wurde ihr aehnlich, das Team hat sie
    entfernt), wird durch den naechsten Kandidaten ersetzt. Liefert (Fragen, Hinweis oder None)."""
    inv = (session.get("corpus") or {}).get("inventory")
    if not inv:
        return [], None
    team_cqs = [_cq_text(c) for c in _momo(session).get("competency_questions", []) if _cq_text(c)]
    shown, note = _holdout_shown(session, inv, team_cqs)
    stored = session.get("holdout") or {}
    removed = stored.get("removed") or []
    # eine Auswahl nach aelteren Regeln wird einmal neu getroffen; was das Team entfernt hat, bleibt entfernt
    keep = stored.get("questions") or [] if stored.get("version") == HOLDOUT_SELECTION_VERSION else []
    # hoechstens die Haelfte der Literatur-CQs: der Rest bleibt dem Vorschlag in Schritt 5 (DECISIONS 137)
    limit = min(HOLDOUT_CQS, len(inv.get("competency_questions") or []) // 2)
    qs = select_holdout_cqs(inv, team_cqs, limit, list(shown) + removed, keep, concept_key)
    session["holdout"] = {"questions": qs, "removed": removed, "version": HOLDOUT_SELECTION_VERSION}
    return qs, note

class HoldoutRequest(BaseModel):
    session_id: str
    question: str = ""

def _holdout_response(session):
    qs, note = holdout_set(session)
    inv = (session.get("corpus") or {}).get("inventory") or {}
    return {"questions": holdout_details(inv, qs, concept_key),
            "removed": (session.get("holdout") or {}).get("removed") or [], "note": note,
            "pool": len(inv.get("competency_questions") or []), "shown": len(session.get("cqs_shown_to_model") or [])}

@app.post("/api/holdout")
def holdout_questions(req: HoldoutRequest):
    """Die Hold-out-Fragen mit ihren zentralen Begriffen, zur Durchsicht durch das Team (keine Modellaufrufe)."""
    return _holdout_response(_session(req.session_id))

@app.post("/api/holdout/remove")
def holdout_remove(req: HoldoutRequest):
    """Das Team nimmt eine Frage aus dem Hold-out-Satz; der naechste Kandidat tritt an ihre Stelle."""
    session = _session(req.session_id)
    holdout_set(session)                       # erst die Auswahl nach den aktuellen Regeln
    stored = session["holdout"]
    if req.question and req.question not in stored.setdefault("removed", []):
        stored["removed"].append(req.question)
    stored["questions"] = [q for q in stored.get("questions") or [] if q != req.question]
    return _holdout_response(session)

@app.post("/api/holdout/reset")
def holdout_reset(req: HoldoutRequest):
    """Neu auswaehlen: entfernte Fragen kommen wieder in Frage."""
    session = _session(req.session_id)
    session["holdout"] = {"questions": [], "removed": []}
    return _holdout_response(session)

def _fresh_cq_report(session):
    """CQ-Testergebnis der aktuellen Iteration, falls vorhanden und schon mit den genutzten Termen."""
    cached = session.get("cq_test_report") or {}
    result = cached.get("result")
    if cached.get("iteration") != session.get("iterations") or not result:
        return None
    if any("terms" not in t for t in result.get("tests") or [] if t.get("status") != "not_answerable"):
        return None   # Ergebnis aus einer aelteren Version ohne Termliste
    return result

@app.post("/api/evaluate")
def evaluate_ontology(req: EvaluateRequest):
    return _with_usage(lambda: _evaluate(req))

def _evaluate(req: EvaluateRequest):
    session = _session(req.session_id)
    onto = session.get("ontology")
    if not onto:
        raise HTTPException(status_code=400, detail="Generate an ontology first")
    turtle = ontology_to_turtle(onto, session.get("_standards", []), session_prefixes(session))
    inv = (session.get("corpus") or {}).get("inventory")
    team_cqs = [_cq_text(c) for c in _momo(session).get("competency_questions", []) if _cq_text(c)]
    context = context_block(session)
    notes, rerun = [], None
    repeats = max(1, min(req.repeats, EVAL_REPEATS))
    fresh = req.fresh or repeats > 1     # unabhaengige Laeufe: keiner baut auf gespeicherten Daten und Abfragen auf

    # 1. Die CQs des Teams: Ergebnis dieser Iteration wiederverwenden, sonst neu testen
    cq_report = None if fresh else _fresh_cq_report(session)
    if cq_report is None and team_cqs:
        if req.llm_config:
            try:
                cq_report = test_competency_questions(turtle, team_cqs, req.llm_config, context,
                                                      previous=None if fresh else (session.get("cq_test_report") or {}).get("result"))
                session["cq_test_report"] = {"iteration": session.get("iterations"), "result": cq_report}
                rerun = cq_report
            except Exception as ex:
                notes.append(f"The competency questions could not be tested: {getattr(ex, 'detail', ex)}")
        else:
            notes.append("The competency questions were not tested (no LLM configured).")

    # 2. Hold-out: Fragen aus der Literatur, die der Generierung nicht vorlagen
    #    ohne die Literatur-CQs, die der CQ-Vorschlag schon gesehen hat. Sessions von vor dieser Aufzeichnung wissen
    #    das nicht; dort werden vorsichtshalber die ersten SUGGEST_CQS_SHOWN ausgeschlossen.
    #    Die Auswahl bleibt gespeichert und kann vom Team durchgesehen werden (DECISIONS 133)
    shown, _ = _holdout_shown(session, inv, team_cqs)
    holdout_qs, note = holdout_set(session)
    if note:
        notes.append(note)
    holdout_report = None
    if not inv:
        notes.append("No hold-out test: there is no concept inventory (step 3) to take questions from.")
    elif not holdout_qs:
        notes.append("No hold-out test: the inventory has no candidate questions that differ from yours "
                     "and were not already shown to the competency-question suggestions.")
    elif req.holdout and req.llm_config:
        try:
            holdout_report = test_competency_questions(turtle, holdout_qs, req.llm_config, context, "Hold-out CQ tests",
                                                       previous=None if fresh else session.get("holdout_test_report"))
            session["holdout_test_report"] = holdout_report
        except Exception as ex:
            notes.append(f"The hold-out questions could not be tested: {getattr(ex, 'detail', ex)}")

    # 2b. Evaluate 3x: weitere Laeufe von vorn, parallel; gespeichert bleibt der erste (Traceability, Reasoner und die
    #     naechste Iteration bauen auf ihm auf), die weiteren gehen nur in Mittel und Streuung ein
    cq_runs = [cq_report] if rerun else []
    holdout_runs = [holdout_report] if holdout_report else []
    if repeats > 1 and req.llm_config:
        def one(i):
            out, errors = {}, []
            for kind, qs, step, done in (("cq", team_cqs, "CQ tests", cq_runs), ("holdout", holdout_qs, "Hold-out CQ tests", holdout_runs)):
                if not done:            # schon der erste Lauf fehlte oder scheiterte
                    continue
                try:
                    out[kind] = test_competency_questions(turtle, qs, req.llm_config, context, f"{step} (run {i} of {repeats})")
                except Exception as ex:
                    errors.append(f"{step}, run {i} of {repeats}: {getattr(ex, 'detail', ex)}")
            return out, errors
        with concurrent.futures.ThreadPoolExecutor(max_workers=repeats - 1) as pool:
            # copy_context hier, nicht im Thread: die Threads schreiben ihren Verbrauch in das Log dieser Anfrage
            futures = [pool.submit(contextvars.copy_context().run, one, i) for i in range(2, repeats + 1)]
            results = [f.result() for f in futures]
        for out, errors in results:
            cq_runs += [out["cq"]] if "cq" in out else []
            holdout_runs += [out["holdout"]] if "holdout" in out else []
            notes += [f"Not counted in the mean: {e}" for e in errors]

    # 3. Deterministische Masse und Reasoner
    report = {
        "iteration": session.get("iterations"),
        "evaluated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "metrics": structural_metrics(onto, label_languages(session)),
        "coverage": concept_coverage(onto, inv, concept_key, session.get("gap_decisions")),
        "hierarchy": hierarchy_coverage(onto, inv, concept_key, session.get("gap_decisions"),
                                        declined_relations(session)),
        "traceability": traceability(onto, [cq_report, holdout_report], inv, concept_key),
        "cq": cq_coverage(cq_report) if cq_report else None,
        "holdout": cq_coverage(holdout_report) if holdout_report else None,
        "cq_repeats": cq_repeats(cq_runs) if len(cq_runs) > 1 else None,
        "holdout_repeats": cq_repeats(holdout_runs) if len(holdout_runs) > 1 else None,
        "holdout_excluded": len(shown or []),
        "upper_candidates": len(upper_candidates(session)),
        "align_candidates": len(align_candidates(session)),
        "restriction_candidates": len(restriction_candidates(session)),
        "decisions": decisions_report(session),
        "definitions": check_definitions(onto, session),
        "reasoner": reasoner_check(turtle_for_reasoning(session, turtle), (cq_report or {}).get("sample_data", "")),
        "notes": notes,
    }
    # die vorige Evaluation einer anderen Iteration bleibt als Vergleich (DECISIONS 136): Evaluate - Reparatur -
    # Evaluate zeigt, was die Reparatur geaendert hat; eine erneute Evaluation derselben Iteration ersetzt nur sich
    prev = session.get("evaluation")
    if prev and prev.get("iteration") != report["iteration"]:
        session["evaluation_previous"] = evaluation_summary(prev)
    before = session.get("evaluation_previous")
    report["previous"] = before if before and before.get("iteration") != report["iteration"] else None
    session["evaluation"] = report
    return {**report, "cq_tests": rerun}

class PropertyVocabRequest(BaseModel):
    session_id: str
    llm_config: LLMConfig
    before_generation: bool = False   # Schritt 7: aus Fragen, Key Notions und Literatur statt aus fertigen Properties

class PropertyVocabSaveRequest(BaseModel):
    session_id: str
    relations: list = None
    approve: bool = False
    discard: bool = False
    off: bool = False                 # Kernrelationen fuer dieses Projekt abschalten (Schritt 7)

@app.post("/api/properties/propose")
def propose_property_vocab(req: PropertyVocabRequest):
    return _with_usage(lambda: _propose_property_vocab(req))

def _propose_property_vocab(req):
    session = _session(req.session_id)
    onto = session.get("ontology")
    classes = None
    if req.before_generation:       # DECISIONS 89: Domain und Range nur aus Klassen, die die Planung sicher anlegt
        momo = _momo(session)
        if not (named_notions(momo.get("key_notions")) or any(_cq_text(c) for c in momo.get("competency_questions") or [])):
            raise HTTPException(status_code=400, detail="Add competency questions or key notions first")
        classes = relation_classes(session)
    elif not onto:
        raise HTTPException(status_code=400, detail="Generate an ontology first")
    with usage_step("Core relations"):
        result = _run_llm_json(req.llm_config, build_core_vocab_prompt(session) if req.before_generation
                               else build_property_vocab_prompt(session))
    # Was das Modell falsch schreibt (unbekannte Klasse, doppelter Name), wird einzeln verworfen statt den
    # ganzen Vorschlag abzulehnen; der Rest geht zur Pruefung ans Team.
    kept, dropped = [], []
    for r in result.get("relations") or []:
        try:
            kept += clean_property_vocab(kept + [r], onto or {}, classes)[len(kept):]
        except HTTPException as ex:
            dropped.append(str(ex.detail))
    if not kept:
        raise HTTPException(status_code=502, detail="The model proposed no usable core relation" +
                                                    (f": {dropped[0]}" if dropped else ""))
    session["property_vocab"] = {"relations": kept, "status": "proposed", "summary": str(result.get("summary") or ""),
                                 "dropped": dropped[:20], "iteration": session.get("iterations"),
                                 "basis": "plan" if req.before_generation else "ontology", "classes": classes}
    return {"property_vocab": session["property_vocab"]}

@app.post("/api/properties/vocab")
def save_property_vocab(req: PropertyVocabSaveRequest):
    """Bearbeitungen und Freigabe des Kernvokabulars durch das Team."""
    session = _session(req.session_id)
    if req.discard:
        session.pop("property_vocab", None)
        return {"property_vocab": None}
    if req.off:   # bewusst ohne Kernrelationen: Schritt 7 schlaegt dann keine mehr von selbst vor
        session["property_vocab"] = {"relations": [], "status": "off", "basis": "plan"}
        return {"property_vocab": session["property_vocab"]}
    vocab = session.get("property_vocab")
    if not vocab or vocab.get("status") == "off":
        raise HTTPException(status_code=400, detail="There is no core vocabulary yet - propose one first")
    if req.relations is not None:
        classes = None
        if vocab.get("basis") == "plan":       # die Key Notions koennen sich seit dem Vorschlag geaendert haben
            classes = vocab["classes"] = relation_classes(session)
        vocab["relations"] = clean_property_vocab(req.relations, session.get("ontology") or {}, classes)
        if vocab.get("status") == "approved":
            vocab["status"] = "proposed"     # eine Aenderung nach der Freigabe muss neu freigegeben werden
    if req.approve:
        vocab["status"] = "approved"
    return {"property_vocab": vocab}

class GapStartRequest(BaseModel):
    session_id: str
    kind: str
    dry_run: bool = False   # nur zaehlen (fuer die Rueckfrage im Browser), nichts starten

class GapStepRequest(BaseModel):
    session_id: str
    llm_config: LLMConfig
    index: int

class GapFinishRequest(BaseModel):
    session_id: str
    llm_config: LLMConfig | None = None

@app.post("/api/gaps/start")
def gaps_start(req: GapStartRequest):
    session = _session(req.session_id)
    if not session.get("ontology"):
        raise HTTPException(status_code=400, detail="Generate an ontology first")
    if req.kind not in GAP_KINDS:
        raise HTTPException(status_code=400, detail="kind must be one of: " + ", ".join(GAP_KINDS))
    if req.kind in ("concepts", "hierarchy") and not _inventory_parts(session)[0]:
        raise HTTPException(status_code=400, detail="This needs a concept inventory (step 3)")
    vocab = session.get("property_vocab") or {}
    if req.kind == "properties" and vocab.get("status") not in ("approved", "applied"):
        raise HTTPException(status_code=400, detail="Review and approve the core relations first")
    if req.kind == "align" and not session.get("vocabularies"):
        raise HTTPException(status_code=400, detail="Load at least one vocabulary in step 7 first")
    batches = build_gap_batches(session, req.kind)
    if req.dry_run or (not batches and req.kind != "properties"):
        return {"kind": req.kind, "batches": len(batches), "items": sum(len(b["items"]) for b in batches),
                "iteration": session.get("iterations")}
    onto = session["ontology"]
    upper = core = None
    if req.kind == "upper":   # die Schicht selbst legt der Server an, nicht das Modell: gleiche Klassen in jedem Projekt
        onto = session["ontology"] = copy.deepcopy(onto)
        upper = ensure_upper_layer(onto, label_languages(session), upper_layer_of(session))
    if req.kind == "properties":   # das freigegebene Vokabular legt ebenfalls der Server an, deterministisch
        props_before = structural_metrics(onto)
        onto = copy.deepcopy(onto)
        ensure_core_module(onto)
        langs = label_languages(session)
        onto, rep = apply_edits(onto, core_relation_ops(vocab["relations"], onto, langs), langs[0], known_prefixes(session))
        session["ontology"] = onto
        core = {"created": [a["summary"] for a in rep["applied"]],
                "rejected": [f"{r['op'].get('name')}: {r['reason']}" for r in rep["rejected"]],
                "before": {k: props_before[k] for k in ("object_properties", "relations", "top_level_relations")}}
        batches = build_gap_batches(session, req.kind)
    # Ausgangslage fuer die Reasoner-Pruefung je Paket: welche Klassen sind schon vorher unerfuellbar?
    baseline = _unsatisfiable(ontology_to_turtle(onto, session.get("_standards", []), session_prefixes(session, onto)),
                              session)
    session["gap_run"] = {"kind": req.kind, "batches": batches, "applied": 0, "rejected": 0, "skipped": [],
                          "summaries": [], "reverted": [], "upper": upper, "core": core,
                          "unsat_baseline": sorted(baseline) if baseline is not None else None}
    # eine Aktion = eine Iteration: Evaluation und CQ-Tests gelten danach als veraltet
    session["iterations"] = session.get("iterations", 1) + 1
    return {"kind": req.kind, "batches": len(batches), "items": sum(len(b["items"]) for b in batches),
            "iteration": session["iterations"], "upper": upper, "core": core}

@app.post("/api/gaps/step")
def gaps_step(req: GapStepRequest):
    return _with_usage(lambda: _gap_step(req))

def _gap_step(req: GapStepRequest):
    session = _session(req.session_id)
    run = session.get("gap_run")
    if not run:
        raise HTTPException(status_code=409, detail="No gap-filling run in progress - start it again")
    if not 0 <= req.index < len(run["batches"]):
        raise HTTPException(status_code=400, detail="Unknown batch")
    batch = run["batches"][req.index]
    label = f"{GAP_KINDS[run['kind']]} {req.index + 1}/{len(run['batches'])}"
    before = session["ontology"]
    standards = session.get("_standards", [])
    try:
        onto, edit = edit_ontology(session, req.llm_config, before, batch["request"], label, focus_text=batch["focus"])
        apply_conventions(onto, session)
        prefixes = session_prefixes(session, onto)
        turtle = ontology_to_turtle(onto, standards, prefixes)
        onto, turtle, validation = validate_and_fix_turtle(turtle, onto, session, req.llm_config, standards, prefixes)
        # Reasoner-Waechter: eine neue Oberklasse kann mit einer Disjunktheit kollidieren und Klassen unerfuellbar
        # machen. Dann bekommt das Modell eine Korrekturrunde; hilft sie nicht, wird das Paket zurueckgenommen.
        onto, turtle, edit["reasoner"] = _reasoner_guard(session, req.llm_config, run, before, onto, turtle,
                                                         label, standards)
    except HTTPException:
        raise
    except Exception as ex:
        print(f"ERROR in {label}:")          # the reason also in the server log, not only in the browser
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=type(ex).__name__ + ": " + str(ex))
    if run["kind"] == "concepts" and not edit["reasoner"].get("reverted"):
        edit["auto_linked"] = link_new_classes(before, onto, batch["items"], _inventory_parts(session)[0])
    if run["kind"] == "properties" and not edit["reasoner"].get("reverted"):
        run.setdefault("merged", {}).update(edit.get("merged") or {})   # fuer die Uebersetzung der CQ-Tests am Ende
    session["ontology"] = onto
    # bewusste Nicht-Modellierungen merken, damit sie beim naechsten Durchlauf nicht wieder vorgelegt werden
    if run["kind"] == "concepts":
        decisions = session.setdefault("gap_decisions", {})
        for s in edit["skipped"]:
            if concept_key(s["item"]):
                decisions[concept_key(s["item"])] = s["reason"] or "not modeled"
    elif run["kind"] in ("upper", "properties", "align", "restrictions"):
        decided = decision_store(session, run["kind"])
        for x in edit["skipped"]:
            if x["item"] in batch["items"]:
                decided[x["item"]] = {"item": x["item"], "reason": x["reason"] or "not applied"}
    else:
        decided = decision_store(session, "hierarchy")
        for x in edit["skipped"]:
            if x["item"]:
                key = _norm(x["item"].replace("Taxonomy ", "").strip("'")) if x["item"].startswith("Taxonomy")                     else _norm(x["item"])
                decided[key] = {"item": x["item"], "reason": x["reason"] or "not applied"}
    if edit["reasoner"].get("reverted"):
        run["reverted"].append({"package": req.index + 1, "unsatisfiable": edit["reasoner"]["new_unsatisfiable"]})
        edit["applied"] = []
    run["applied"] += len(edit["applied"])
    run["rejected"] += len(edit["rejected"])
    run["skipped"] += edit["skipped"]
    if edit["summary"]:
        run["summaries"].append(edit["summary"])
    return {"index": req.index, "edit_report": edit, "ontology": onto, "turtle": turtle, "validation": validation}

@app.post("/api/gaps/finish")
def gaps_finish(req: GapFinishRequest):
    return _with_usage(lambda: _gap_finish(req))

def _gap_finish(req: GapFinishRequest):
    session = _session(req.session_id)
    run = session.pop("gap_run", None) or {"kind": "concepts", "applied": 0, "rejected": 0, "skipped": [], "summaries": []}
    if run["kind"] == "upper" and run.get("upper"):
        session["ontology"] = copy.deepcopy(session["ontology"])
        run["upper"]["removed"] = remove_unused_upper(session["ontology"], run["upper"]["created"])
    onto = session["ontology"]
    standards = session.get("_standards", [])
    prefixes = session_prefixes(session, onto)
    turtle = ontology_to_turtle(onto, standards, prefixes)
    report = None
    if req.llm_config:
        onto_fixed, turtle, report = run_oops_and_fix(turtle, onto, session, req.llm_config, standards, prefixes)
        if onto_fixed:
            onto = session["ontology"] = onto_fixed
        report["validation"] = {"valid": validate_turtle(turtle)[0], "error": "", "fixed": False}
    if run["applied"]:
        request = {"concepts": "Add the central concepts of the literature that were missing",
                   "hierarchy": "Arrange the classes by the broader/narrower relations and taxonomies of the literature",
                   "upper": "Group the root classes under the upper layer",
                   "properties": "Consolidate the object properties into the approved core relations",
                   "align": "Link classes and properties to the loaded vocabularies",
                   "restrictions": "Add class restrictions for class pairs the ontology connects only loosely"}[run["kind"]]
        session["feedback_log"] = ((session.get("feedback_log") or []) +
                                   [{"feedback": request, "summary": " ".join(run["summaries"])[:600]}])[-30:]
    cq = None
    if run["kind"] == "properties":
        if session.get("property_vocab"):
            session["property_vocab"]["status"] = "applied"
        cq = _property_regression(session, req.llm_config, turtle, run)
        if run.get("core"):
            after = structural_metrics(onto)
            run["core"]["after"] = {k: after[k] for k in ("object_properties", "relations", "top_level_relations",
                                                          "properties_with_superproperty",
                                                          "properties_with_characteristics")}
    return {"ontology": onto, "turtle": turtle, "iteration": session.get("iterations"), "oops_report": report,
            "cq_tests": (cq or {}).get("result"),
            "summary": {"kind": run["kind"], "applied": run["applied"], "rejected": run["rejected"],
                        "skipped": run["skipped"][:200], "reverted": run.get("reverted", []),
                        "summaries": run["summaries"], "upper": run.get("upper"), "core": run.get("core"),
                        "cq": {k: v for k, v in (cq or {}).items() if k != "result"} or None,
                        "reasoner_checked": run.get("unsat_baseline") is not None}}

class GapReconsiderRequest(BaseModel):
    session_id: str
    kind: str = "concepts"   # oder eine der Aktionen in DECISION_KEYS
    labels: list[str] = []   # concepts: Begriffe (wie in der Evaluation angezeigt)
    keys: list[str] = []     # andere Aktionen: Schluessel aus dem Bericht ("decisions")
    all: bool = False

@app.post("/api/gaps/reconsider")
def gaps_reconsider(req: GapReconsiderRequest):
    """Nimmt Nicht-Modellierungs-Entscheidungen zurueck: die Begriffe gelten wieder als fehlend und werden beim
    naechsten 'Add missing central concepts' wieder vorgelegt. Die Abdeckung im gespeicherten Evaluationsbericht
    wird gleich neu berechnet (deterministisch, ohne Modell); die CQ-Ergebnisse bleiben, wie sie sind."""
    session = _session(req.session_id)
    if req.kind in DECISION_KEYS:          # obere Schicht, Hierarchie, Properties, Ausrichtung (DECISIONS 76)
        store = decision_store(session, req.kind)
        if req.all:
            removed = len(store)
            store.clear()
        else:
            removed = sum(1 for k in req.keys if store.pop(k, None) is not None)
        rep = session.get("evaluation")
        if rep and session.get("ontology"):
            rep["decisions"] = decisions_report(session)
            rep["upper_candidates"] = len(upper_candidates(session))
            rep["align_candidates"] = len(align_candidates(session))
            rep["restriction_candidates"] = len(restriction_candidates(session))
            inv = (session.get("corpus") or {}).get("inventory")
            if inv:
                rep["hierarchy"] = hierarchy_coverage(session["ontology"], inv, concept_key, session.get("gap_decisions"),
                                                      declined_relations(session))
        return {"removed": removed, "remaining": len(store), "evaluation": rep}
    if req.kind != "concepts":
        raise HTTPException(status_code=400, detail="kind must be concepts or one of: " + ", ".join(DECISION_KEYS))
    decisions = session.get("gap_decisions") or {}
    if req.all:
        removed = len(decisions)
        decisions.clear()
    else:
        inv = (session.get("corpus") or {}).get("inventory") or {}
        by_key = {concept_key(c["label"]): c for c in inv.get("concepts") or []}
        keys = set()
        for label in req.labels:
            c = by_key.get(concept_key(label))
            keys |= {concept_key(v) for v in ([c["label"], *c.get("variants", [])] if c else [label])}
        removed = sum(1 for k in keys if decisions.pop(k, None) is not None)
    session["gap_decisions"] = decisions
    rep = session.get("evaluation")
    inv = (session.get("corpus") or {}).get("inventory")
    if rep and inv and session.get("ontology"):
        rep["coverage"] = concept_coverage(session["ontology"], inv, concept_key, decisions)
        rep["hierarchy"] = hierarchy_coverage(session["ontology"], inv, concept_key, decisions,
                                              declined_relations(session))
    return {"removed": removed, "remaining": len(decisions), "evaluation": rep}

def _with_usage(fn):
    """Fuehrt fn aus und haengt den Token-Verbrauch aller LLM-Aufrufe an die Antwort. Auch ein
    fehlgeschlagener Lauf hat Tokens gekostet — dann steht der Verbrauch in der Fehlermeldung."""
    with track_usage() as log:
        try:
            result = fn()
        except HTTPException as ex:
            if log:
                u = usage_summary(log)
                ex.detail = (f"{ex.detail} (Tokens used before the error: {u['input_tokens']:,} input, "
                             f"{u['output_tokens']:,} output in {len(log)} LLM call(s))")
            raise
    result["usage"] = usage_summary(log)
    return result

@app.post("/api/generate")
def generate_ontology(req: GenerateRequest):
    return _with_usage(lambda: _generate(req))

def _generate(req: GenerateRequest):
    if req.session_id not in sessions:
        raise HTTPException(status_code=404, detail="Project not found")
    session = sessions[req.session_id]
    try:
        context = context_block(session)
        session["_context_used"] = context
        # ein Weg fuer alle Projekte (DECISIONS 84): Plan, dann Modul fuer Modul - mit Literatur aus dem Inventar,
        # ohne aus Use Case, Kompetenzfragen, Key Notions und Daten
        onto, modular_report = generate_modular(session, req.llm_config, req.selected_standards, context,
                                                req.domain_description)
    except HTTPException:
        raise
    except Exception as ex:
        raise HTTPException(status_code=500, detail=type(ex).__name__ + ": " + str(ex))
    # die entschiedenen Definitionen stehen woertlich in den Beschreibungen (DECISIONS 83)
    definitions_report = enforce_definitions(onto, session)
    # Verweise auf geladene Vokabulare pruefen (Teil B, DECISIONS 77)
    onto, dropped_external = check_external_refs(session, onto)
    session["_standards"] = req.selected_standards  # fuer spaetere Turtle-Generierung speichern
    standards = req.selected_standards
    apply_conventions(onto, session)
    custom_prefixes = session_prefixes(session, onto)
    turtle = ontology_to_turtle(onto, standards, custom_prefixes)
    onto, turtle, val_report = validate_and_fix_turtle(turtle, onto, session, req.llm_config, standards, custom_prefixes)
    onto_fixed, turtle, report = run_oops_and_fix(turtle, onto, session, req.llm_config, standards, custom_prefixes)
    if onto_fixed:
        onto = onto_fixed
    report["validation"] = val_report
    session["ontology"] = onto
    session["feedback_log"] = []      # eine neue Generierung beginnt ohne fruehere Aenderungswuensche
    session.pop("history", None)      # Altlast: frueher der komplette Gespraechsverlauf samt Ontologie-JSON
    session["iterations"] = 1
    # eine neue Ontologie beginnt mit neuen CQ-Tests: alte Beispieldaten trugen sonst Individuen frueherer Ontologien
    # weiter (Wein-Lauf 7), und weil die Iteration wieder bei 1 beginnt, hielte die Evaluation alte Ergebnisse fuer
    # aktuell (DECISIONS 96). Zwischen Iterationen derselben Generierung bleiben sie (DECISIONS 67).
    session.pop("cq_test_report", None)
    session.pop("evaluation", None)       # die alte Evaluation gehoerte zu einer anderen Ontologie (Iteration wieder 1)
    session.pop("evaluation_previous", None)
    session.pop("holdout_test_report", None)
    reports = {"modular_report": modular_report, "definitions_report": definitions_report,
               "reuse_report": {"links": structural_metrics(onto).get("external_links", 0),
                                "dropped": dropped_external[:30]} if session.get("vocabularies") else None}
    # im Projekt behalten: der Bericht zeigt, was der Plan vorgab und die Module anders machten - nach einem
    # Neuladen der Seite sonst verloren (Wein-Lauf 5)
    session["generation_report"] = {**reports, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    return {"ontology": onto, "turtle": turtle, "iteration": 1, "oops_report": report, **reports}

@app.post("/api/feedback")
def apply_feedback(req: FeedbackRequest):
    return _with_usage(lambda: _feedback(req))

def _feedback(req: FeedbackRequest):
    if req.session_id not in sessions:
        raise HTTPException(status_code=404, detail="Project not found")
    session = sessions[req.session_id]
    old = session.get("ontology")
    if not old:
        raise HTTPException(status_code=400, detail="Generate an ontology first")
    # In Schritt 7 angehaengte Dateien gehen einmal mit in die Anfrage ein (frueher kamen sie nie beim Modell an)
    attachments = [f for f in session.get("data_files") or []
                   if f.get("suffix") == " (feedback attachment)" and not f.get("used")]
    request = req.feedback
    for f in attachments:
        material = (f.get("full_text") or "")[:30_000] if f.get("kind") == "text" else f.get("summary", "")
        request += f"\n\n**Attached file {f['name']}:**\n{material}"
    try:
        onto, edit = edit_ontology(session, req.llm_config, old, request, "Refinement", focus_text=req.feedback)
    except HTTPException:
        raise
    except Exception as ex:
        raise HTTPException(status_code=500, detail=type(ex).__name__ + ": " + str(ex))
    if edit["operations"] and not edit["applied"]:
        raise edit_error(edit)
    apply_conventions(onto, session)
    standards = session.get("_standards", [])
    custom_prefixes = session_prefixes(session, onto)
    turtle = ontology_to_turtle(onto, standards, custom_prefixes)
    onto, turtle, val_report = validate_and_fix_turtle(turtle, onto, session, req.llm_config, standards, custom_prefixes)
    onto_fixed, turtle, report = run_oops_and_fix(turtle, onto, session, req.llm_config, standards, custom_prefixes)
    if onto_fixed:
        onto = onto_fixed
    report["validation"] = val_report
    session["ontology"] = onto
    session.pop("history", None)
    for f in attachments:   # erst nach Erfolg: bei einem Fehler gehen sie mit der naechsten Runde erneut mit
        f["used"] = True
    if edit["applied"]:     # nur echte Aenderungen sind "bereits umgesetzte Wuensche" fuer spaetere Runden
        session["feedback_log"] = ((session.get("feedback_log") or []) +
                                   [{"feedback": req.feedback.strip()[:600], "summary": edit["summary"]}])[-30:]
    session["iterations"] = session.get("iterations", 1) + 1
    return {"ontology": onto, "turtle": turtle, "iteration": session["iterations"], "oops_report": report,
            "edit_report": edit}

@app.post("/api/export")
def export_owl(req: ExportRequest):
    if req.session_id not in sessions:
        raise HTTPException(status_code=404, detail="Project not found")
    onto = sessions[req.session_id].get("ontology")
    if not onto:
        raise HTTPException(status_code=400, detail="Generate an ontology first")
    standards = sessions[req.session_id].get("_standards", [])
    custom_prefixes = session_prefixes(sessions[req.session_id])
    return {"turtle": ontology_to_turtle(onto, standards, custom_prefixes), "ontology_name": onto.get("ontology_name", "ontologie")}

@app.post("/api/generate-shacl")
def generate_shacl_endpoint(req: GenerateShaclRequest):
    if req.session_id not in sessions:
        raise HTTPException(status_code=404, detail="Project not found")
    session = sessions[req.session_id]
    onto = session.get("ontology")
    if not onto:
        raise HTTPException(status_code=400, detail="Generate an ontology first")
    try:
        shacl = generate_shacl_turtle(onto, req.constraints)
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))
    valid, error = validate_turtle(shacl)
    if not valid:
        raise HTTPException(status_code=500, detail="The generated SHACL is not valid Turtle: " + error[:200])
    result = {"shacl": shacl, "ontology_adjusted": False, "ontology": None, "turtle": None}
    if req.adjust_ontology and req.llm_config:
        summary = "\n".join(
            "- " + c.get("property_name","") + " auf " + c.get("target_class","") +
            ": minCount=" + str(c.get("min_count","–")) +
            ", maxCount=" + str(c.get("max_count","–")) +
            ", datatype=" + str(c.get("datatype","–"))
            for c in req.constraints if c.get("property_name")
        )
        request = ("SHACL constraints were defined for the ontology:\n\n" + summary +
                   "\n\nAdjust the ontology so that it agrees with them (correct ranges, missing properties).")
        try:
            onto_adj, edit = edit_ontology(session, req.llm_config, onto, request, "SHACL adjustment")
            apply_conventions(onto_adj, session)
            turtle_adj = ontology_to_turtle(onto_adj, session.get("_standards", []), session_prefixes(session, onto_adj))
            session["ontology"] = onto_adj
            if edit["applied"]:       # eine Aenderung ist eine Iteration - sonst galten alte CQ-Ergebnisse (T12)
                session["iterations"] = session.get("iterations", 0) + 1
            result["iteration"] = session.get("iterations")
            result["edit_report"] = edit
            result["ontology_adjusted"] = bool(edit["applied"])
            result["ontology"] = onto_adj
            result["turtle"] = turtle_adj
        except Exception as ex:
            result["adjust_error"] = str(ex)
    return result


@app.post("/api/update-turtle")
async def update_turtle(request: Request):
    body = await request.json()
    session_id = body.get("session_id", "")
    turtle_str = body.get("turtle", "")
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Project not found")
    # Validieren
    valid, error = validate_turtle(turtle_str)
    if not valid:
        raise HTTPException(status_code=400, detail="Turtle-Syntaxfehler: " + error)
    # Parsen -> onto dict; was Turtle nicht traegt, aus der bisherigen Fassung (Code-Review T1)
    session = sessions[session_id]
    old_onto = session.get("ontology") or {}
    try:
        from rdflib import Graph
        g = Graph(bind_namespaces="core")      # sonst benennt rdflib eigene Prefixe wie geo oder schema um
        g.parse(data=turtle_str, format="turtle")
        prefer = {c.get("name"): c.get("parent") for c in old_onto.get("classes") or [] if isinstance(c, dict)}
        onto = rdf_graph_to_onto(g, turtle_str, prefer)
        onto.pop("import_report", None)
        onto = keep_from_previous(onto, old_onto)
    except Exception as ex:
        raise HTTPException(status_code=400, detail="Parse error: " + str(ex))
    _adopt_prefixes(session, graph_prefixes_used(g, onto))
    session["ontology"] = onto
    session["iterations"] = session.get("iterations", 0) + 1
    # die eigene Ausgabe zurueck, nicht den Text des Editors: die Seite zeigt, was gespeichert ist
    turtle = ontology_to_turtle(onto, session.get("_standards", []), session_prefixes(session))
    return {"ontology": onto, "turtle": turtle, "iteration": session["iterations"]}

def _adopt_prefixes(session, prefixes):
    """Prefixe einer geladenen oder bearbeiteten Datei, die das Projekt noch nicht kennt, als eigene Prefixe
    uebernehmen - sonst schriebe der Turtle-Export die externen Verweise ohne Deklaration."""
    known = session_prefixes(session)
    for pfx, ns in prefixes.items():
        if pfx not in known and pfx not in ("owl", "rdf", "rdfs", "xsd", "xml"):
            session.setdefault("custom_prefixes", {})[pfx] = ns


@app.post("/api/fix-turtle")
async def fix_turtle_endpoint(request: Request):
    body = await request.json()
    session_id = body.get("session_id", "")
    broken_turtle = body.get("turtle", "")
    error_msg = body.get("error", "")
    llm_config_data = body.get("llm_config")
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Project not found")
    if not llm_config_data:
        raise HTTPException(status_code=400, detail="The LLM configuration is missing")
    llm_cfg = LLMConfig(**llm_config_data)
    messages = [
        {"role": "user", "content":
            "The following Turtle ontology contains a syntax error.\n\n"
            "Error: " + error_msg + "\n\n"
            "Turtle with the error:\n```turtle\n" + broken_turtle + "\n```\n\n"
            "Fix ONLY the syntax error and return the complete, corrected Turtle code (only the code, no Markdown, "
            "no explanation)."
        }
    ]
    try:
        raw = await run_in_threadpool(llm.call_llm, llm_cfg, messages)   # nicht auf der Ereignisschleife (F19)
        # Turtle aus Antwort extrahieren
        fixed = raw.strip()
        # Markdown-Bloecke entfernen
        import re as _re
        fixed = _re.sub(r"```(?:turtle|ttl)?\s*", "", fixed).strip().rstrip("`").strip()
        # Validieren
        valid, err = validate_turtle(fixed)
        if not valid:
            raise HTTPException(status_code=400,
                detail="The LLM could not fix the error. New error: " + err)
        return {"turtle": fixed, "valid": True}
    except HTTPException:
        raise
    except Exception as ex:
        raise HTTPException(status_code=500, detail=type(ex).__name__ + ": " + str(ex))

if __name__ == "__main__":
    import subprocess, sys
    subprocess.run([sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "8000"])
