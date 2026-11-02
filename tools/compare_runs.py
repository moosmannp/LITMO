"""Vergleicht mehrere Projekte (Sessions) einer Messreihe: je Projekt die Kennzahlen aus Generierungsbericht,
Evaluation und Verbrauch, dazu Mittelwert und Standardabweichung - fuer wiederholte Generierungen derselben
Konfiguration (PLAN.md Phase 6) oder den Vergleich zweier Konfigurationen.

Aufruf (aus dem Projektordner, ohne laufenden Server noetig - die Sessions werden nur gelesen):
    python tools/compare_runs.py <session-id> [<session-id> ...]
    python tools/compare_runs.py --title "VA measurement run 3"     (alle Projekte, deren Titel so beginnt)

Ausgabe: eine Markdown-Tabelle. Sessions liegen in data/sessions oder im Ordner aus ODT_SESSION_DIR.
"""
import json
import os
import statistics
import sys
from pathlib import Path

SESSION_DIR = Path(os.environ.get("ODT_SESSION_DIR") or Path(__file__).resolve().parent.parent / "data" / "sessions")


def _get(d, *path):
    for k in path:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def _len(x):
    return len(x) if isinstance(x, list) else None


def _plan_excluded(c):
    """Zentrale Begriffe, die der Plan selbst ausschloss. Seit DECISIONS 131 geht jeder Ausschluss in die Pruefung
    (oder war eine Zuordnung, accounted_as); davor nur die geschuetzten - der Rest steht dann direkt in excluded."""
    if not c or c.get("reviewed") is None:
        return None
    if "accounted_as" in c:
        return c["reviewed"] + len(c["accounted_as"])
    kept = c.get("review_kept") if isinstance(c.get("review_kept"), list) else []
    return c["reviewed"] + len(c.get("excluded") or []) - (c.get("completion_excluded") or 0) - len(kept) \
        - (c.get("earlier_decisions") or 0)


# (Zeile, Funktion Session -> Wert); None = nicht vorhanden
ROWS = [
    ("Planned classes", lambda s: _get(s, "generation_report", "modular_report", "planned_classes")),
    ("Central concepts excluded (plan + completion)",
     lambda s: _len(_get(s, "generation_report", "modular_report", "central", "excluded"))),
    ("Central concepts the plan excluded",
     lambda s: _plan_excluded(_get(s, "generation_report", "modular_report", "central"))),
    ("... given a second look by the completion",
     lambda s: _get(s, "generation_report", "modular_report", "central", "reviewed")),
    ("... excluded again after the second look",
     lambda s: _len(_get(s, "generation_report", "modular_report", "central", "review_kept"))),
    ("... named a planned class (accounted for as)",
     lambda s: _len(_get(s, "generation_report", "modular_report", "central", "accounted_as"))),
    ("Central concepts missing after the modules (DECISIONS 136)",
     lambda s: _len(_get(s, "generation_report", "modular_report", "central_after_modules", "missing"))),
    ("... added by the generation",
     lambda s: _len(_get(s, "generation_report", "modular_report", "central_after_modules", "added"))),
    ("Central concepts added by the completion",
     lambda s: _get(s, "generation_report", "modular_report", "central", "completion_assigned")),
    ("Vocabulary links after planning (+ terms used)",
     lambda s: (lambda r: None if r is None else len(r.get("links") or []) + len(r.get("terms") or []))(
         _get(s, "generation_report", "modular_report", "reuse"))),
    ("Vocabulary links after the modules",
     lambda s: _len(_get(s, "generation_report", "modular_report", "reuse", "after_modules", "links"))),
    ("Classes", lambda s: _get(s, "evaluation", "metrics", "classes")),
    ("Object properties", lambda s: _get(s, "evaluation", "metrics", "object_properties")),
    ("Axioms", lambda s: _get(s, "evaluation", "metrics", "axioms")),
    ("Root classes", lambda s: _get(s, "evaluation", "metrics", "root_classes")),
    ("Top-level relations", lambda s: _get(s, "evaluation", "metrics", "top_level_relations")),
    ("Top-level relations per class", lambda s: (lambda m: None if not m or m.get("top_level_relations") is None
        or not m.get("classes") else round(m["top_level_relations"] / m["classes"], 2))(_get(s, "evaluation", "metrics"))),
    ("Links to reused vocabularies", lambda s: _get(s, "evaluation", "metrics", "external_links")),
    ("Sibling groups with disjointness", lambda s: _get(s, "evaluation", "metrics", "sibling_groups_with_disjointness")),
    ("Central concepts as a class (%)", lambda s: _get(s, "evaluation", "coverage", "central_covered_pct")),
    ("Central concepts represented (%)", lambda s: _get(s, "evaluation", "coverage", "central_represented_pct")),
    ("Broader/narrower relations realized (%)", lambda s: _get(s, "evaluation", "hierarchy", "realized_pct")),
    ("Classes linked to the inventory (%)", lambda s: _get(s, "evaluation", "traceability", "linked_to_inventory_pct")),
    ("Competency questions full", lambda s: _get(s, "evaluation", "cq", "full")),
    ("Competency questions partial", lambda s: _get(s, "evaluation", "cq", "partial")),
    ("Hold-out questions full", lambda s: _get(s, "evaluation", "holdout", "full")),
    ("Hold-out questions partial", lambda s: _get(s, "evaluation", "holdout", "partial")),
    # nur nach "Evaluate 3x" (DECISIONS 124): Mittel und Streuung der drei Laeufe je Ontologie
    ("Competency questions full, mean of the repeated tests", lambda s: _get(s, "evaluation", "cq_repeats", "full", "mean")),
    ("... spread (sd) within the repeated tests", lambda s: _get(s, "evaluation", "cq_repeats", "full", "sd")),
    ("Hold-out questions full, mean of the repeated tests",
     lambda s: _get(s, "evaluation", "holdout_repeats", "full", "mean")),
    ("... spread (sd) within the repeated tests", lambda s: _get(s, "evaluation", "holdout_repeats", "full", "sd")),
    ("Reasoner consistent", lambda s: _get(s, "evaluation", "reasoner", "ontology", "consistent")),
    ("Input tokens of the last run (k)",
     lambda s: (lambda u: round(sum(x.get("input_tokens", 0) for x in u) / 1000) if u else None)(_get(s, "ui", "usageRun"))),
    ("Output tokens of the last run (k)",
     lambda s: (lambda u: round(sum(x.get("output_tokens", 0) for x in u) / 1000) if u else None)(_get(s, "ui", "usageRun"))),
]


def load(ids=(), title=None):
    out = []
    files = [SESSION_DIR / f"{i}.json" for i in ids] if ids else sorted(SESSION_DIR.glob("*.json"))
    for f in files:
        s = json.loads(f.read_text(encoding="utf-8"))
        if title and not (s.get("title") or "").startswith(title):
            continue
        out.append((s.get("title") or f.stem, s))
    return sorted(out, key=lambda x: x[0]) if title else out


def _fmt(v):
    if v is None:
        return "-"
    if isinstance(v, bool):
        return "yes" if v else "no"
    return f"{v:g}" if isinstance(v, float) else str(v)


def table(runs) -> str:
    head = "| | " + " | ".join(t for t, _ in runs) + (" | mean | spread (sd) |" if len(runs) > 1 else " |")
    lines = [head, "|---" * (len(runs) + (3 if len(runs) > 1 else 1)) + "|"]
    for name, fn in ROWS:
        vals = [fn(s) for _, s in runs]
        nums = [v for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)]
        row = f"| {name} | " + " | ".join(_fmt(v) for v in vals)
        if len(runs) > 1:
            mean = f"{statistics.mean(nums):.1f}" if nums else "-"
            sd = f"{statistics.stdev(nums):.1f}" if len(nums) > 1 else "-"
            row += f" | {mean} | {sd}"
        lines.append(row + " |")
    return "\n".join(lines)


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    runs = load(title=args[1]) if args[0] == "--title" else load(ids=args)
    if not runs:
        sys.exit("No matching projects.")
    print(table(runs))
