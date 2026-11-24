"""Messung zu PLAN.md Phase 5 (DECISIONS 125): die Klassenpaare, die eine Property-Konsolidierung aufgegeben hat.

Eine Konsolidierung fuehrt spezifische Properties (depictsMultidimensionalData: ParallelCoordinatesPlot ->
MultidimensionalData) in allgemeine zusammen; ihr Domain-Range-Paar geht dabei verloren. Seit DECISIONS 125 merkt sich
die Zusammenfuehrung dieses Paar. Fuer ein Projekt, das vorher konsolidiert wurde, rekonstruiert dieses Werkzeug die
Paare aus einem Stand vor und einem nach der Konsolidierung.

Aufruf (aus dem Projektordner; die Sessions und Dateien werden nur gelesen):
    python tools/lost_pairs.py count  <vorher> <nachher>
    python tools/lost_pairs.py seed   <vorher> <projekt.project.json> <kopie.project.json>
    python tools/lost_pairs.py measure <vorher> <session>

<vorher>, <nachher>, <session>: eine Session-ID (oder ihr Anfang) aus data/sessions bzw. ODT_SESSION_DIR, oder eine
exportierte Projektdatei. "seed" schreibt eine Kopie der exportierten Projektdatei mit den verlorenen Paaren als
aufgezeichnete Zusammenfuehrungen; sie wird im Tool importiert (ein neues Projekt, das Original bleibt). Danach
schlaegt die Reparatur "Add class restrictions" diese Paare vor. "measure" zaehlt danach, wie viele Paare wieder eine
Restriktion haben, und zeigt Reasoner und Kompetenzfragen aus der letzten Evaluation.
"""
import json
import os
import sys
from pathlib import Path

SESSION_DIR = Path(os.environ.get("ODT_SESSION_DIR") or Path(__file__).resolve().parent.parent / "data" / "sessions")
PROJECT_FORMAT = "ontology-development-tool/project"


def load(ref) -> tuple:
    """(Projekt, Export-Payload oder None) aus einer Projektdatei oder einer Session."""
    path = Path(ref)
    if path.suffix == ".json" and path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("format") == PROJECT_FORMAT:
            return data["project"], data
        return data, None
    hits = sorted(SESSION_DIR.glob(f"{ref}*.json"))
    if len(hits) != 1:
        sys.exit(f"{ref}: {'no' if not hits else 'more than one'} session in {SESSION_DIR}")
    return json.loads(hits[0].read_text(encoding="utf-8")), None


def lost_pairs(before, after) -> list:
    """Object Properties von vorher, die nachher fehlen und deren Domain und Range nachher noch Klassen sind - im Format
    der aufgezeichneten Zusammenfuehrungen (wohin sie gingen, ist nicht mehr bekannt)."""
    b, a = before.get("ontology") or {}, after.get("ontology") or {}
    classes = {c.get("name") for c in a.get("classes") or [] if isinstance(c, dict)}
    props = {p.get("name") for p in a.get("properties") or [] if isinstance(p, dict)}
    return [{"property": p["name"], "into": None, "type": "ObjectProperty", "domain": p["domain"], "range": p["range"]}
            for p in b.get("properties") or []
            if isinstance(p, dict) and p.get("type") == "ObjectProperty" and p.get("name") not in props
            and p.get("domain") in classes and p.get("range") in classes]


def pairs(records) -> set:
    return {(r["domain"], r["range"]) for r in records}


def main(args):
    if len(args) < 3 or args[0] not in ("count", "seed", "measure"):
        sys.exit(__doc__)
    before, _ = load(args[1])
    if args[0] == "count":
        after, _ = load(args[2])
        lost = lost_pairs(before, after)
        print(f"{len(lost)} properties lost, {len(pairs(lost))} distinct class pairs")
    elif args[0] == "seed":
        if len(args) != 4:
            sys.exit(__doc__)
        project, payload = load(args[2])
        if payload is None:
            sys.exit(f"{args[2]} is no exported project file (Export project in the tool)")
        lost = lost_pairs(before, project)
        project["merge_records"] = (project.get("merge_records") or []) + lost
        project["title"] = (project.get("title") or "Project") + " (class restrictions)"
        Path(args[3]).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        print(f"{len(lost)} lost properties ({len(pairs(lost))} class pairs) recorded in {args[3]} - import it in the tool")
    else:
        session, _ = load(args[2])
        lost = pairs(lost_pairs(before, session))
        onto = session.get("ontology") or {}
        res = [r for r in onto.get("restrictions") or [] if isinstance(r, dict)]
        back = lost & {(r.get("class"), r.get("value")) for r in res}
        declined = [k for k in session.get("gap_restriction_decisions") or {} if tuple(k.split(" -> ")) in lost]
        ev = session.get("evaluation") or {}
        rs = (ev.get("reasoner") or {}).get("ontology") or {}
        kinds = {}
        for r in res:
            kinds[r.get("kind")] = kinds.get(r.get("kind"), 0) + 1
        print(f"Lost class pairs: {len(lost)}")
        print(f"... with a restriction again: {len(back)} ({round(100 * len(back) / len(lost), 1) if lost else 0} %)")
        print(f"... declined with a reason: {len(declined)}")
        print(f"Restrictions in the ontology: {len(res)} {kinds}")
        print(f"Reasoner (last evaluation, iteration {ev.get('iteration')}): consistent={rs.get('consistent')}, "
              f"unsatisfiable={len(rs.get('unsatisfiable') or [])}")
        cq, ho = ev.get("cq") or {}, ev.get("holdout") or {}
        print(f"Competency questions full: {cq.get('full')}/{cq.get('total')}, hold-out {ho.get('full')}/{ho.get('total')}")


if __name__ == "__main__":
    main(sys.argv[1:])
