"""Entschiedene Definitionen (PLAN.md Phase 1, DECISIONS 83): das Team entscheidet in Schritt 4 die widerspruechlichen
Definitionen des Begriffsinventars; Planung, Module, Pruefung und eine Reparaturaktion setzen sie durch."""

import contextvars, re
from datetime import datetime, timezone
from fastapi import HTTPException

import llm
from llm import usage_step
from project import _class_name, _context, context_block, _cq_text, decided_definitions, MOMO_METHOD
from corpus import concept_key, doc_citation, _inventory_parts, _plain

# Je Konflikt eine Entscheidung, gespeichert im Projektkontext unter dem Begriff (nicht der Inventar-ID, die sich bei
# einem Neuaufbau aendert). "parts" sind die Klassen, die den Begriff tragen: eine bei position/own, mehrere bei split.
DECISION_CHOICES = ("position", "own", "split", "open")
MAX_SPLIT_PARTS = 4
DEFINITION_CHARS = 800
RECOMMEND_BATCH = 15          # Konflikte je Empfehlungsaufruf (die Antwort schreibt je Konflikt eine Definition)
RECOMMEND_WORKERS = 4
RECOMMEND_SOURCE_DEFS = 4


def _store(session) -> dict:
    return _context(session).setdefault("definition_decisions", {})

def clean_decision(raw, n_positions) -> tuple:
    """(Entscheidung, Fehlertext): nur bekannte Wahl, gueltige Position, Klassennamen und Definitionen."""
    if not isinstance(raw, dict):
        return None, "not a decision"
    choice = raw.get("choice")
    if choice not in DECISION_CHOICES:
        return None, f"unknown choice {choice!r}"
    d = {"choice": choice, "position": None, "parts": [], "reason": _plain(raw.get("reason"), 600)}
    if choice == "open":
        return d, ""
    if choice == "position":
        pos = raw.get("position")
        if not isinstance(pos, int) or isinstance(pos, bool) or not 0 <= pos < n_positions:
            return None, "the chosen position does not exist"
        d["position"] = pos
    for p in raw.get("parts") or []:
        if not isinstance(p, dict):
            continue
        name, definition = _class_name(p.get("name")), _plain(p.get("definition"), DEFINITION_CHARS)
        if not name:
            return None, "every class needs a name"
        if not definition:
            return None, f"the class {name} needs a definition"
        if any(q["name"] == name for q in d["parts"]):
            return None, f"the class name {name} is used twice"
        d["parts"].append({"name": name, "definition": definition})
    if choice == "split" and not 2 <= len(d["parts"]) <= MAX_SPLIT_PARTS:
        return None, f"a split needs 2 to {MAX_SPLIT_PARTS} classes, each with a name and a definition"
    if choice != "split" and len(d["parts"]) != 1:
        return None, "give the class name and its definition"
    return d, ""

def conflict_list(session) -> list:
    """Die Konflikte des Inventars (die meisten Quellen zuerst) mit Positionen, Quellen, Entscheidung und Empfehlung.
    Entscheidungen zu Begriffen, die nach einem Neuaufbau des Inventars kein Konflikt mehr sind, bleiben gueltig und
    werden am Ende gelistet."""
    inv, docs, by_id = _inventory_parts(session)
    store = (session.get("context") or {}).get("definition_decisions") or {}
    out, seen = [], set()
    for x in (inv or {}).get("conflicts") or []:
        c = by_id.get(x.get("concept"))
        key = concept_key(x.get("label") or "")
        if not c or not key or key in seen:
            continue
        seen.add(key)
        entry = store.get(key) or {}
        out.append({"key": key, "concept": x["label"], "papers": c["papers"], "issue": x.get("issue", ""),
                    "positions": [{"view": p["view"], "sources": [doc_citation(docs[d]) for d in p["docs"] if d in docs]}
                                  for p in x["positions"]],
                    "definitions": [{"source": doc_citation(docs[s["doc"]]), "definition": s["definition"]}
                                    for s in c["sources"] if s.get("definition") and s["doc"] in docs][:8],
                    "decision": entry.get("decision"), "recommendation": entry.get("recommendation")})
    out.sort(key=lambda e: -e["papers"])
    for key, entry in store.items():
        if key not in seen and (entry.get("decision") or entry.get("recommendation")):
            out.append({"key": key, "concept": entry["concept"], "papers": 0, "issue": "", "positions": [],
                        "definitions": [], "decision": entry.get("decision"),
                        "recommendation": entry.get("recommendation"), "orphan": True})
    return out

def conflict_summary(conflicts) -> dict:
    decided = [c for c in conflicts if c["decision"]]
    return {"conflicts": sum(1 for c in conflicts if not c.get("orphan")), "decided": len(decided),
            "open": sum(1 for c in decided if c["decision"]["choice"] == "open"),
            "recommended": sum(1 for c in conflicts if c["recommendation"] and not c["decision"])}

def _names_elsewhere(session, key) -> dict:
    return {p["name"]: e["concept"] for k, e in _store(session).items() if k != key
            for p in (e.get("decision") or {}).get("parts") or []}

def set_decision(session, key, raw, accepted=False) -> dict:
    """Speichert (raw) oder loescht (raw None) die Entscheidung zu einem Konflikt."""
    conflict = next((c for c in conflict_list(session) if c["key"] == key), None)
    if not conflict:
        raise HTTPException(status_code=404, detail="Unknown conflict")
    store = _store(session)
    entry = store.setdefault(key, {"concept": conflict["concept"], "decision": None, "recommendation": None})
    if raw is None:
        entry["decision"] = None
        if not entry.get("recommendation"):
            store.pop(key)
        return conflict
    d, error = clean_decision(raw, len(conflict["positions"]))
    if error:
        raise HTTPException(status_code=400, detail=f"{conflict['concept']}: {error}")
    taken = _names_elsewhere(session, key)
    clash = next((p["name"] for p in d["parts"] if p["name"] in taken), None)
    if clash:
        raise HTTPException(status_code=400, detail=f"{conflict['concept']}: the class name {clash} is already "
                                                    f"used by the decision on {taken[clash]}")
    d["decided_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if accepted:
        d["accepted_recommendation"] = True
    entry["decision"] = d
    return conflict

def accept_recommendations(session, keys=None) -> dict:
    """Uebernimmt die Empfehlungen der noch nicht entschiedenen Konflikte (alle oder die genannten)."""
    accepted, skipped = 0, []
    for c in conflict_list(session):
        if c["decision"] or not c["recommendation"] or (keys is not None and c["key"] not in keys):
            continue
        try:
            set_decision(session, c["key"], c["recommendation"], accepted=True)
            accepted += 1
        except HTTPException as ex:
            skipped.append(str(ex.detail))
    return {"accepted": accepted, "skipped": skipped}

# ── Empfehlung (optional, ein Modellaufruf je Paket) ───────────────────────────
RECOMMEND_SYS = (MOMO_METHOD + "\nThe sources of an ontology project define some concepts in conflicting ways. The "
                 "team decides each conflict; you recommend a decision for each conflict below, given the use case, "
                 "the competency questions and the project context (its glossary may already settle a conflict - then "
                 "follow it). Choices:\n"
                 "- position: one of the listed positions is right for this ontology. Give its number and write the "
                 "class definition based on it.\n"
                 "- own: no position fits as it stands; write a definition that suits this ontology.\n"
                 "- split: the positions denote different things that this ontology needs as SEPARATE classes (for "
                 "example an artifact and the process that produces it). Give 2-" + str(MAX_SPLIT_PARTS) + " classes; "
                 "the first keeps the concept's own name where that is sensible.\n"
                 "- open: the conflict does not matter for this ontology's use case and questions.\n"
                 "Definitions: 1-2 sentences, genus and differentia, in the language of the descriptions (see the "
                 "conventions). Class names UpperCamelCase and singular. Give a one-sentence reason for each "
                 "recommendation.\n"
                 'Answer ONLY as JSON: {"recommendations":[{"conflict":"k1","choice":"position|own|split|open",'
                 '"position":1,"parts":[{"name":"ClassName","definition":"..."}],"reason":"..."}]} - "position" only '
                 'for the choice position (the number of the position), "parts" empty for open.')

def build_recommend_prompt(session, batch) -> list:
    momo = session.get("momo") or {}
    cqs = "\n".join("- " + _cq_text(c) for c in momo.get("competency_questions") or [] if _cq_text(c)) or "(none)"
    blocks = []
    for i, c in enumerate(batch, 1):
        lines = [f"k{i} | {c['concept']} ({c['papers']} sources)", f"  issue: {c['issue']}"]
        for j, p in enumerate(c["positions"], 1):
            lines.append(f"  {j}. {p['view']}" + (f" ({'; '.join(p['sources'][:3])})" if p["sources"] else ""))
        for s in c["definitions"][:RECOMMEND_SOURCE_DEFS]:
            lines.append(f"  - definition in {s['source']}: {s['definition'][:250]}")
        blocks.append("\n".join(lines))
    return [{"role": "system", "content": RECOMMEND_SYS},
            {"role": "user", "content": "**Use case:**\n" + (momo.get("use_case") or "(none)") + "\n\n" +
             context_block(session) + "\n\n**Competency questions:**\n" + cqs +
             "\n\n**Conflicts:**\n" + "\n\n".join(blocks) + "\n\nRecommend a decision for every conflict."}]

def _clean_recommendations(result, batch) -> tuple:
    out, invalid = {}, 0
    for r in (result.get("recommendations") if isinstance(result, dict) else None) or []:
        m = re.fullmatch(r"k(\d+)", str((r or {}).get("conflict") or "").strip()) if isinstance(r, dict) else None
        if not m or not 1 <= int(m.group(1)) <= len(batch):
            invalid += 1
            continue
        c = batch[int(m.group(1)) - 1]
        raw = dict(r)
        if raw.get("choice") == "position" and isinstance(raw.get("position"), int):
            raw["position"] -= 1                       # im Prompt ab 1 gezaehlt
        if raw.get("choice") == "open":
            raw["parts"] = []
        d, error = clean_decision(raw, len(c["positions"]))
        if error:
            invalid += 1
            continue
        d["recommended_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        out[c["key"]] = d
    return out, invalid

def recommend(session, llm_config, keys=None) -> dict:
    """Empfehlungen fuer die noch nicht entschiedenen Konflikte (oder die genannten), in Paketen parallel."""
    import concurrent.futures
    todo = [c for c in conflict_list(session) if not c.get("orphan")
            and (c["key"] in keys if keys is not None else not c["decision"])]
    if not todo:
        raise HTTPException(status_code=400, detail="No undecided conflicts to recommend a decision for")
    batches = [todo[i:i + RECOMMEND_BATCH] for i in range(0, len(todo), RECOMMEND_BATCH)]
    def run(batch):
        with usage_step("Recommend definitions"):
            return llm.call_llm_json(llm_config, build_recommend_prompt(session, batch))
    results, errors = [], []
    with concurrent.futures.ThreadPoolExecutor(max_workers=RECOMMEND_WORKERS) as pool:
        futures = {pool.submit(contextvars.copy_context().run, run, b): b for b in batches}
        for f in concurrent.futures.as_completed(futures):
            try:
                results.append((futures[f], f.result()))
            except HTTPException as ex:
                errors.append(ex)
            except Exception as ex:
                errors.append(HTTPException(status_code=500, detail=f"{type(ex).__name__}: {str(ex)[:200]}"))
    if not results:
        raise errors[0]
    store, recommended, invalid = _store(session), 0, 0
    for batch, result in results:
        recs, bad = _clean_recommendations(result, batch)
        invalid += bad
        for c in batch:
            if c["key"] in recs:
                store.setdefault(c["key"], {"concept": c["concept"], "decision": None})["recommendation"] = recs[c["key"]]
                recommended += 1
    return {"recommended": recommended, "invalid": invalid, "asked": len(todo),
            "failed_batches": len(errors), "error": str(errors[0].detail) if errors else ""}

# ── Durchsetzen: Planung, Module, nach der Generierung, Pruefung, Reparatur ───
def _concept_ids(inv, concept) -> list:
    key = concept_key(concept)
    return [c["id"] for c in inv["concepts"] if key in {concept_key(t) for t in [c["label"], *c.get("variants", [])]}]

def apply_to_plan(plan, session) -> dict:
    """Die Planung legt die entschiedenen Klassen an: die Klasse des Begriffs traegt den entschiedenen Namen, die
    weiteren Klassen einer Aufteilung kommen in dasselbe Modul. Alle tragen den Begriff (Abdeckung, Rueckverfolgung)."""
    report = {"classes": [], "added": [], "renamed": []}
    inv, _, _ = _inventory_parts(session)
    decided = decided_definitions(session)
    if not inv or not decided or not plan["modules"]:
        return report
    theme = {cid: t["name"] for t in inv.get("themes") or [] for cid in t["concepts"]}
    where = {cl["name"]: (m, cl) for m in plan["modules"] for cl in m["classes"]}
    for concept, d in decided:
        ids = _concept_ids(inv, concept)
        names = [p["name"] for p in d["parts"]]
        holder = next(((m, cl) for m in plan["modules"] for cl in m["classes"] if set(cl["concepts"]) & set(ids)), None)
        if holder and holder[1]["name"] not in names and names[0] not in where:
            old = holder[1]["name"]
            holder[1]["name"] = names[0]
            where[names[0]] = where.pop(old)
            for m2 in plan["modules"]:            # Unterklassen der umbenannten Klasse zeigen auf den neuen Namen
                for c2 in m2["classes"]:
                    if c2.get("parent") == old:
                        c2["parent"] = names[0]
            report["renamed"].append([old, names[0]])
        module = holder[0] if holder else next((where[n][0] for n in names if n in where), None)
        if module is None:   # nicht geplant: in das Modul, dessen Klassen am meisten Begriffe desselben Themas tragen
            themes = {theme[i] for i in ids if i in theme}
            module = max(plan["modules"], key=lambda m: sum(1 for cl in m["classes"] for i in cl["concepts"]
                                                            if theme.get(i) in themes)) if themes else plan["modules"][0]
        for n in names:
            if n in where:
                cl = where[n][1]
                cl["concepts"] += [i for i in ids if i not in cl["concepts"]]
            else:
                cl = {"name": n, "concepts": list(ids)}
                module["classes"].append(cl)
                where[n] = (module, cl)
                report["added"].append(n)
        report["classes"] += names
    return report

def decided_classes(session) -> dict:
    """Klassenname -> (Begriff, Definition, alle Klassen der Entscheidung) fuer das Modul-Prompt."""
    return {p["name"]: (concept, p["definition"], [q["name"] for q in d["parts"]])
            for concept, d in decided_definitions(session) for p in d["parts"]}

def _same(a, b) -> bool:
    norm = lambda s: re.sub(r"\s+", " ", str(s or "")).strip().rstrip(".").casefold()
    return norm(a) == norm(b)

def _matches(onto, concept, d) -> list:
    """[(Teil, Klasse oder None)]: zuerst nach dem entschiedenen Namen; die erste Klasse auch ueber die Verknuepfung
    mit dem Inventarbegriff oder den Namen des Begriffs (eine Ontologie von vor der Entscheidung)."""
    by_name = {c["name"]: c for c in onto.get("classes") or [] if isinstance(c, dict) and c.get("name")}
    key, names = concept_key(concept), {p["name"] for p in d["parts"]}
    out, used = [], set()
    for i, p in enumerate(d["parts"]):
        cls = by_name.get(p["name"])
        if cls is None and i == 0:
            cls = next((c for c in by_name.values() if c["name"] not in names and
                        any(concept_key(x) == key for x in c.get("inventory_concepts") or [])), None) \
                or (by_name.get(_class_name(concept)) if _class_name(concept) not in names else None)
        if cls is not None and cls["name"] in used:
            cls = None
        if cls is not None:
            used.add(cls["name"])
        out.append((p, cls))
    return out

def enforce_definitions(onto, session):
    """Nach der Generierung: die entschiedenen Definitionen stehen woertlich in den Beschreibungen. Meldet, wo das
    Modell abgewichen ist und welche entschiedene Klasse fehlt."""
    decided = decided_definitions(session)
    if not decided:
        return None
    report = {"classes": 0, "deviated": [], "missing": []}
    for concept, d in decided:
        for p, cls in _matches(onto, concept, d):
            report["classes"] += 1
            if cls is None:
                report["missing"].append(p["name"])
                continue
            if not _same(cls.get("description"), p["definition"]):
                report["deviated"].append(cls["name"])
                cls["description"] = p["definition"]
            links = cls.setdefault("inventory_concepts", [])
            if concept_key(concept) not in {concept_key(x) for x in links}:
                links.append(concept)
    return report

def check_definitions(onto, session) -> dict:
    """Fuer die Evaluation, ohne Modell: stimmt jede entschiedene Klasse mit ihrer Definition ueberein?"""
    conflicts = conflict_list(session)
    summary = conflict_summary(conflicts)
    rows = []
    for concept, d in decided_definitions(session):
        for p, cls in _matches(onto, concept, d):
            rows.append({"concept": concept, "class": p["name"], "found": cls["name"] if cls else None,
                         "status": "missing" if cls is None else "ok" if _same(cls.get("description"), p["definition"])
                         else "deviating", "expected": p["definition"],
                         "actual": (cls or {}).get("description", "")})
    return {"available": bool(summary["conflicts"] or rows), **summary,
            "undecided": summary["conflicts"] - sum(1 for c in conflicts if c["decision"] and not c.get("orphan")),
            "classes": len(rows), "ok": sum(1 for r in rows if r["status"] == "ok"),
            "deviating": [r for r in rows if r["status"] == "deviating"],
            "missing": [r for r in rows if r["status"] == "missing"]}

def definition_ops(onto, session) -> list:
    """Edit-Operationen der Aktion "Apply decided definitions": abweichende Beschreibungen ersetzen, fehlende Klassen
    einer Entscheidung anlegen (neben der Klasse, die den Begriff schon traegt)."""
    ops = []
    for concept, d in decided_definitions(session):
        matches = _matches(onto, concept, d)
        sibling = next((cls for _, cls in matches if cls), None) or {}
        for p, cls in matches:
            if cls is None:
                ops.append({"op": "add_class", "name": p["name"], "description": p["definition"],
                            "parent": sibling.get("parent"), "module": sibling.get("module"),
                            "inventory_concepts": [concept]})
            elif not _same(cls.get("description"), p["definition"]):
                ops.append({"op": "update_class", "name": cls["name"], "description": p["definition"]})
    return ops
