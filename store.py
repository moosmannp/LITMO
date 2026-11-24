"""Sessions im Speicher und ihre Ablage als JSON-Dateien."""

import json, os, re, threading
from pathlib import Path

sessions: dict = {}

# ── Persistenz ─────────────────────────────────────────────────────────────────
# Jede Session liegt als JSON-Datei in data/sessions/, damit ein Serverneustart keine Arbeit vernichtet.
# Statt jeden Endpunkt einzeln anzupassen, schreibt eine Middleware nach jeder aendernden API-Anfrage alle
# Sessions, deren Inhalt sich seit dem letzten Speichern geaendert hat. API-Keys stehen nie in einer
# Session (sie kommen mit jeder Anfrage aus dem Browser) und landen daher weder auf der Platte noch im Export.
SESSION_DIR = Path(os.environ.get("ODT_SESSION_DIR") or Path(__file__).with_name("data") / "sessions")
_SID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_saved_snapshots: dict = {}
_save_lock = threading.Lock()

def _is_empty_session(s: dict) -> bool:
    momo = s.get("momo") or {}
    return not (s.get("ontology") or s.get("data_preview") or s.get("ui") or momo.get("use_case")
                or momo.get("competency_questions") or momo.get("key_notions")
                or (s.get("corpus") or {}).get("docs"))

def save_dirty_sessions():
    with _save_lock:
        SESSION_DIR.mkdir(parents=True, exist_ok=True)
        for sid, s in list(sessions.items()):
            try:
                text = json.dumps(s, ensure_ascii=False)
            except (TypeError, ValueError) as ex:
                print(f"WARNUNG: Session {sid} nicht speicherbar: {ex}")
                continue
            except RuntimeError:
                continue  # parallele Anfrage aendert die Session gerade — die naechste Anfrage speichert sie
            if _saved_snapshots.get(sid) == text:
                continue
            if sid not in _saved_snapshots and _is_empty_session(s):
                continue  # jeder Seitenaufruf legt eine Session an — leere nicht auf die Platte schreiben
            try:
                data = text.encode("utf-8")
            except UnicodeEncodeError:
                # ein einzelnes Surrogat (z.B. aus PDF-Text) laesst sich nicht als UTF-8 schreiben; als ASCII-Escape
                # schon, und json liest es unveraendert zurueck - sonst scheiterte jede spaetere Speicherung
                data = json.dumps(s).encode("ascii")
            tmp = SESSION_DIR / (sid + ".json.tmp")
            try:
                tmp.write_bytes(data)
                tmp.replace(SESSION_DIR / (sid + ".json"))  # atomar: nie eine halb geschriebene Datei
            except OSError as ex:
                print(f"WARNUNG: Session {sid} nicht gespeichert: {ex}")
                continue
            _saved_snapshots[sid] = text

def saved_at(sid):
    """Zeitpunkt der letzten Speicherung (Zeit der Datei), None fuer eine noch nicht gespeicherte Session."""
    try:
        return (SESSION_DIR / (sid + ".json")).stat().st_mtime
    except OSError:
        return None

def load_sessions():
    if not SESSION_DIR.is_dir():
        return
    for f in SESSION_DIR.glob("*.json"):
        if not _SID_RE.match(f.stem):
            continue
        try:
            text = f.read_text(encoding="utf-8")
            sessions[f.stem] = json.loads(text)
            sessions[f.stem].pop("history", None)  # Altlast: voller Gespraechsverlauf samt Ontologie-JSON
            _saved_snapshots[f.stem] = text
        except (OSError, ValueError) as ex:
            print(f"WARNUNG: {f.name} konnte nicht geladen werden: {ex}")
    print(f"{len(sessions)} gespeicherte Session(s) geladen aus {SESSION_DIR}")

load_sessions()
