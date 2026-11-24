"""Die eigene obere Schicht (DECISIONS 68, 69, 97): wenige Klassen nach der Art der Dinge, quer zu den Modulen.

Die Generierung legt sie an und haengt die obersten geplanten Klassen darunter (PLAN.md Phase 3b); die Aktion
"Group root classes" der Evaluation tut dasselbe fuer importierte oder bearbeitete Ontologien.
"""

import re
from fastapi import HTTPException
from ontology_edits import humanize
from project import _norm

# Eigene obere Schicht (DECISIONS 68, 69): wenige Klassen nach der ART der Dinge, quer zu den Modulen. Bewusst nicht
# BFO oder DOLCE - lesbar fuer Fachleute; eine Ausrichtung darauf kann spaeter als eigenes Modul nur diese Klassen
# abbilden. Die Vorgabe ist domaenenneutral; das Team kann sie im Projektkontext je Projekt anpassen.
UPPER_MODULE = "UpperLayer"
DEFAULT_UPPER_LAYER = [
    {"name": "Process", "parent": "", "disjoint": True, "labels": {"en": "process", "de": "Prozess"},
     "definition": "Something that happens or is carried out over time, such as an activity, an operation, an "
                   "interaction, a transformation or a measurement as it takes place."},
    {"name": "Agent", "parent": "", "disjoint": True, "labels": {"en": "agent", "de": "Akteur"},
     "definition": "A person, group, organization or software system that acts, including one acting in a role "
                   "such as user, customer or operator."},
    {"name": "PhysicalObject", "parent": "", "disjoint": True, "labels": {"en": "physical object", "de": "physisches Objekt"},
     "definition": "A material thing that occupies space, such as a device, a machine, an organism, a substance "
                   "or a building."},
    {"name": "InformationObject", "parent": "", "disjoint": True,
     "labels": {"en": "information object", "de": "Informationsobjekt"},
     "definition": "Content that can be stored, copied, shown or communicated independently of its carrier, such as "
                   "data, a document, a model, an image, a finding or software."},
    {"name": "Specification", "parent": "InformationObject", "disjoint": False,
     "labels": {"en": "specification", "de": "Spezifikation"},
     "definition": "An information object that describes something to be achieved or how to do it, such as a goal, "
                   "a task, a requirement, a plan, a method, a guideline or a design."},
    {"name": "Quality", "parent": "", "disjoint": True, "labels": {"en": "quality", "de": "Merkmal"},
     "definition": "A characteristic that something has and that can vary or be assessed, such as a type, a "
                   "measure, a state, a degree of uncertainty or a level of performance."},
]
MAX_UPPER_CLASSES = 12

def clean_upper_layer(entries) -> list:
    """Vom Team bearbeitete Schicht pruefen: gueltige, eindeutige Namen; Oberklasse nur innerhalb der Schicht und
    ohne Zyklen; nur Klassen ohne Oberklasse koennen disjunkt sein. Fehler -> HTTP 400 mit Begruendung."""
    if not isinstance(entries, list) or not entries:
        raise HTTPException(status_code=400, detail="The upper layer needs at least one class")
    if len(entries) > MAX_UPPER_CLASSES:
        raise HTTPException(status_code=400, detail=f"At most {MAX_UPPER_CLASSES} upper classes")
    defaults = {_norm(d["name"]): d for d in DEFAULT_UPPER_LAYER}
    out, seen = [], set()
    for e in entries:
        name = str((e or {}).get("name") or "").strip()
        if not re.match(r"^[A-Za-z][A-Za-z0-9_-]*$", name):
            raise HTTPException(status_code=400, detail=f"Invalid upper class name {name!r}: letters, digits, _ and -, "
                                                        "starting with a letter")
        if _norm(name) in seen:
            raise HTTPException(status_code=400, detail=f"Upper class {name} appears twice")
        seen.add(_norm(name))
        d = defaults.get(_norm(name))
        out.append({"name": name, "parent": str(e.get("parent") or "").strip(), "disjoint": bool(e.get("disjoint")),
                    "labels": d["labels"] if d else {}, "definition": str(e.get("definition") or "").strip()[:500]})
    names = {x["name"] for x in out}
    by = {x["name"]: x for x in out}
    for x in out:
        if x["parent"] and x["parent"] not in names:
            raise HTTPException(status_code=400, detail=f"{x['name']}: the superclass must be another upper class")
        cur, steps = x["parent"], 0
        while cur:
            if cur == x["name"] or steps > len(out):
                raise HTTPException(status_code=400, detail=f"{x['name']}: the superclasses form a cycle")
            cur, steps = by[cur]["parent"], steps + 1
        if x["parent"]:
            x["disjoint"] = False
    return out

def upper_layer_of(session) -> list:
    return (session.get("context") or {}).get("upper_layer") or DEFAULT_UPPER_LAYER

def _upper_disjoint(layer) -> list:
    return [x["name"] for x in layer if x["disjoint"] and not x["parent"]]

def _disjoint_text(names) -> str:
    """Klartext eines Disjunktheits-Axioms: 'Nothing is at the same time a process, an agent and a quality.'"""
    words = [humanize(n).lower() for n in names]
    words = [("an " if w[:1] in "aeiou" else "a ") + w for w in words]
    return "Nothing is at the same time " + (", ".join(words[:-1]) + " and " + words[-1] if len(words) > 1 else "".join(words)) + "."

def ensure_upper_layer(onto, langs, layer=None) -> dict:
    """Legt die obere Schicht an, soweit sie fehlt. Gibt es schon eine Klasse gleichen Namens (z.B. Agent aus einem
    Provenienz-Modul), wird sie uebernommen und nicht veraendert - sie ist dann die obere Klasse."""
    layer = layer or DEFAULT_UPPER_LAYER
    by = {_norm(c.get("name")): c for c in onto.get("classes") or [] if isinstance(c, dict)}
    if not any(m.get("name") == UPPER_MODULE for m in onto.get("modules") or []):
        onto.setdefault("modules", []).append({
            "name": UPPER_MODULE, "key_notion": None, "pattern": None,
            "documentation": "A small upper layer that groups the classes of all modules by the kind of thing they "
                             "are: " + ", ".join(humanize(x["name"]).lower() for x in layer) + "."})
    created, reused = [], []
    for x in layer:
        cls = by.get(_norm(x["name"]))
        if cls:
            cls["layer"] = "upper"
            reused.append(cls["name"])
            continue
        labels = {l: x["labels"][l] for l in langs if l in (x.get("labels") or {})} or {langs[0]: humanize(x["name"]).lower()}
        onto["classes"].append({"name": x["name"], "labels": labels, "description": x["definition"],
                                "parent": x["parent"] or None, "module": UPPER_MODULE, "layer": "upper"})
        created.append(x["name"])
    names = [by[_norm(n)]["name"] if _norm(n) in by else n for n in _upper_disjoint(layer)]
    if len(names) > 1 and not any(a.get("type") == "DisjointClasses" and set(a.get("classes") or []) == set(names)
                                  for a in onto.get("axioms") or []):
        onto.setdefault("axioms", []).append({
            "type": "DisjointClasses", "classes": names, "scoped": False, "module": UPPER_MODULE,
            "natural_language": _disjoint_text(names)})
    return {"created": created, "reused": reused}

def remove_unused_upper(onto, names) -> list:
    """Am Ende eines Laufs: von der Aktion angelegte obere Klassen, die nichts tragen (keine Unterklasse, kein
    SubClassOf-Ziel, keine Domain/Range, kein Individuum), wieder entfernen - eine Domaene ohne physische Dinge soll
    kein leeres PhysicalObject behalten. Eine Klasse, die noch in einem Axiom vorkommt, bleibt. Wiederholt, damit auch eine nur noch leere Oberklasse verschwindet."""
    removed, names = [], set(names)
    while True:
        classes = onto.get("classes") or []
        used = {c.get("parent") for c in classes if isinstance(c, dict)}
        # jede Klasse, auf die ein Axiom verweist - ausser der Disjunktheit der oberen Schicht selbst, die unten
        # mitschrumpft (vorher nur SubClassOf-Ziele: andere Axiome verwiesen danach ins Leere)
        used |= {n for a in onto.get("axioms") or []
                 if not (a.get("type") == "DisjointClasses" and a.get("module") == UPPER_MODULE)
                 for n in a.get("classes") or []}
        used |= {p.get(k) for p in onto.get("properties") or [] for k in ("domain", "range")}
        used |= {i.get("class") for i in onto.get("individuals") or [] if isinstance(i, dict)}
        gone = [c["name"] for c in classes if c.get("name") in names and c.get("layer") == "upper" and c["name"] not in used]
        if not gone:
            break
        onto["classes"] = [c for c in classes if c.get("name") not in gone]
        removed += gone
    if removed:
        axioms = []
        for a in onto.get("axioms") or []:
            if a.get("type") == "DisjointClasses" and a.get("module") == UPPER_MODULE:
                kept = [n for n in a["classes"] if n not in removed]
                a = {**a, "classes": kept, "natural_language": _disjoint_text(kept)}
                if len(a["classes"]) < 2:
                    continue
            axioms.append(a)
        onto["axioms"] = axioms
        if not any(c.get("module") == UPPER_MODULE for c in onto.get("classes") or []):
            onto["modules"] = [m for m in onto.get("modules") or [] if m.get("name") != UPPER_MODULE]
    return removed

def use_upper_layer(session) -> bool:
    """Ob die Generierung die obere Schicht verwendet - voreingestellt ja (PLAN.md, beschlossene Fragen)."""
    return (session.get("context") or {}).get("use_upper_layer", True) is not False

