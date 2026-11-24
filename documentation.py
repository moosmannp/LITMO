"""Dokumentation der Ontologie fuer die Expertenpruefung und die Veroeffentlichung (PLAN.md Phase 6, DECISIONS 114):
ein Dokument mit einem Kapitel je Modul - Beschreibung, Diagramm, Klassen mit Definitionen und Quellen -, als
Markdown oder HTML. Deterministisch, ohne Modellaufruf: alles steht schon in der Ontologie, im Begriffsinventar und
in den Entscheidungen."""

import html, re
from datetime import datetime

from corpus import concept_key, doc_citation
from ontology_evaluation import concept_coverage
from project import label_languages

LITERATURE_PER_CLASS = 3      # Definitionen aus der Literatur je Klasse (mit Seite und Zitat)
MERMAID_SRC = "https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"
SPECIAL_MODULES = ("UpperLayer", "CoreRelations")


# ── Inhalt (gemeinsam fuer Markdown und HTML) ──────────────────────────────────

def _literature(names, by_key, docs) -> list:
    """Die Definitionen der Inventar-Begriffe einer Klasse aus den Quellen; belegte Zitate zuerst."""
    out, seen = [], set()
    for name in names or []:
        c = by_key.get(concept_key(name))
        for s in (c or {}).get("sources") or []:
            if s.get("doc") not in docs or not s.get("definition") or (s["doc"], s["definition"]) in seen:
                continue
            seen.add((s["doc"], s["definition"]))
            out.append({"term": s.get("term") or c["label"], "definition": s["definition"],
                        "quote": s.get("quote") or "", "quote_ok": bool(s.get("quote_ok")), "page": s.get("page"),
                        "source": doc_citation(docs[s["doc"]])})
    out.sort(key=lambda x: not x["quote_ok"])
    return out[:LITERATURE_PER_CLASS]

def _mermaid_id(name) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", str(name))

def _diagram(classes, props, names_in_module) -> str:
    """Klassendiagramm eines Moduls (Mermaid): Vererbung, auch zu Oberklassen anderer Module, und die Relationen
    zwischen Klassen."""
    lines, declared = ["classDiagram", "  direction LR"], set()   # von links nach rechts: viele Geschwister untereinander
    def node(name):
        mid = _mermaid_id(name)
        if mid not in declared:
            declared.add(mid)
            outside = name not in names_in_module
            lines.append(f'  class {mid}["{name}"]' if mid != name or outside else f"  class {mid}")
            if outside:
                lines.append(f"  style {mid} fill:none,stroke-dasharray:4")   # Mermaid: nur so (kein Leerzeichen)
        return mid
    for c in classes:
        node(c["name"])
        for sup in c["superclasses"]:
            lines.append(f"  {node(sup)} <|-- {node(c['name'])}")
    for p in props:
        if p["kind"] == "ObjectProperty" and p["domain"] and p["range"]:
            lines.append(f"  {node(p['domain'])} --> {node(p['range'])} : {p['name']}")
    for c in classes:                     # Klassenrestriktionen gestrichelt: "jedes X hat ein p zu einem Y"
        for r in c.get("restrictions") or []:
            if not str(r.get("value")).startswith(("xsd:", "rdfs:", "rdf:")):
                n = f" {r['n']}" if r.get("n") is not None else ""
                lines.append(f"  {node(c['name'])} ..> {node(r['value'])} : {r['property']} {r['kind']}{n}")
    return "\n".join(lines)

def _tree(classes, names_in_module) -> list:
    """Die Klassen eines Moduls als Baum: (Tiefe, Name, Oberklasse ausserhalb des Moduls oder None)."""
    children = {}
    for c in classes:
        children.setdefault(c["parent"] if c["parent"] in names_in_module else None, []).append(c)
    out = []
    def walk(parent, depth, seen):
        for c in sorted(children.get(parent, []), key=lambda c: c["name"].lower()):
            if c["name"] in seen:
                continue
            out.append((depth, c["name"], c["parent"] if depth == 0 and c["parent"] else None))
            walk(c["name"], depth + 1, seen | {c["name"]})
    walk(None, 0, frozenset())
    return out

def build_documentation(session) -> dict:
    onto = session.get("ontology") or {}
    corpus = session.get("corpus") or {}
    inv = corpus.get("inventory") or {}
    docs = {d["id"]: d for d in corpus.get("docs") or [] if isinstance(d, dict) and d.get("id")}
    by_key = {}
    for c in inv.get("concepts") or []:
        for v in [c["label"], *c.get("variants", [])]:
            by_key.setdefault(concept_key(v), c)
    langs = label_languages(session)
    extra_sup, equivalents = {}, {}
    for a in onto.get("axioms") or []:
        cls = a.get("classes") or []
        if a.get("type") == "SubClassOf" and len(cls) == 2:
            extra_sup.setdefault(cls[0], []).append(cls[1])
        elif a.get("type") == "EquivalentClasses":
            for x in cls:
                equivalents.setdefault(x, []).extend(y for y in cls if y != x)
    individuals = {}
    for i in onto.get("individuals") or []:
        if isinstance(i, dict) and i.get("name"):
            individuals.setdefault(i.get("class"), []).append(i["name"])
    references = set()

    restrictions = {}
    for r in onto.get("restrictions") or []:
        if isinstance(r, dict) and r.get("class"):
            restrictions.setdefault(r["class"], []).append(r)

    def cls_entry(c):
        sups = [s for s in [c.get("parent"), *extra_sup.get(c["name"], [])] if s]
        lit = _literature(c.get("inventory_concepts"), by_key, docs)
        references.update(c.get("sources") or [])
        references.update(x["source"] for x in lit)
        return {"name": c["name"], "labels": c.get("labels") or {}, "description": c.get("description") or "",
                "restrictions": restrictions.get(c["name"], []),
                "parent": c.get("parent"), "superclasses": list(dict.fromkeys(sups)),
                "equivalent": equivalents.get(c["name"], []), "sources": list(dict.fromkeys(c.get("sources") or [])),
                "see_also": c.get("see_also") or [], "concepts": c.get("inventory_concepts") or [],
                "literature": lit, "individuals": individuals.get(c["name"], []),
                "upper": c.get("layer") == "upper", "module": c.get("module")}

    def prop_entry(p):
        return {"name": p["name"], "kind": p.get("type") or "ObjectProperty", "labels": p.get("labels") or {},
                "description": p.get("description") or "", "domain": p.get("domain"), "range": p.get("range"),
                "super": p.get("sub_property_of"), "inverse": p.get("inverse_of"),
                "characteristics": p.get("characteristics") or [], "module": p.get("module")}

    classes = [cls_entry(c) for c in onto.get("classes") or [] if isinstance(c, dict) and c.get("name")]
    props = [prop_entry(p) for p in onto.get("properties") or [] if isinstance(p, dict) and p.get("name")]
    # Kapitel: die Module der Liste, dann Modulnamen, die nur an Klassen oder Properties stehen (geladenes Turtle),
    # zuletzt alles ohne Modul - vorher fehlten diese Klassen in der Dokumentation ganz
    listed = [m for m in onto.get("modules") or [] if isinstance(m, dict) and m.get("name")]
    known = {m["name"] for m in listed} | set(SPECIAL_MODULES)
    extra = [{"name": n} for n in dict.fromkeys(x["module"] for x in [*classes, *props]
                                                if x["module"] and x["module"] not in known and not x.get("upper"))]
    modules = []
    for m in [*(m for m in listed if m["name"] not in SPECIAL_MODULES), *extra, {"name": None}]:
        mc = [c for c in classes if (c["module"] or None) == m["name"] and not c["upper"]]
        mp = [p for p in props if (p["module"] or None) == m["name"]]
        ax = [a for a in onto.get("axioms") or [] if (a.get("module") or None) == m["name"]]
        if m not in listed and not (mc or mp or ax):
            continue
        names = {c["name"] for c in mc}
        name = m["name"] or "Without a module"
        modules.append({"name": name, "heading": f"Module {name}" if m["name"] else "Classes and properties without a module", "key_notion": m.get("key_notion") or "", "pattern": m.get("pattern") or "",
                        "documentation": m.get("documentation") or "", "classes": sorted(mc, key=lambda c: c["name"].lower()),
                        "properties": sorted(mp, key=lambda p: p["name"].lower()), "tree": _tree(mc, names),
                        "axioms": ax, "diagram": _diagram(mc, mp, names), "listed": m in listed})
    # zur Pruefung: bewusst nicht modellierte zentrale Begriffe und abgelehnte Oberbegriffe, mit Grund
    # dieselbe Einordnung wie die Bewertung: auch Entscheidungen zu einer Variante, und kein Begriff, der inzwischen
    # eine Klasse ist
    cov = concept_coverage(onto, inv, concept_key, session.get("gap_decisions")) if inv else {}
    excluded = sorted(((d["label"], d["sources"], d["as"]) for d in cov.get("decided_central") or []),
                      key=lambda x: x[0].lower())
    declined = sorted(((v or {}).get("item") or k, (v or {}).get("reason") or "")
                      for k, v in (session.get("gap_hierarchy_decisions") or {}).items())
    ev = session.get("evaluation") or {}
    levels = {q.get("question"): q.get("level") for q in (ev.get("cq") or {}).get("questions") or []}
    cqs = [(q, levels.get(q)) for q in ((c.get("question") if isinstance(c, dict) else c)
                                        for c in (session.get("momo") or {}).get("competency_questions") or []) if q]
    vocabs = [(p, v.get("name") or p) for p, v in (session.get("vocabularies") or {}).items()]
    return {
        "title": onto.get("ontology_name") or session.get("title") or "Ontology",
        "namespace": onto.get("namespace") or "", "summary": onto.get("summary") or "",
        "license": onto.get("license") or "", "languages": langs,
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "counts": {"modules": sum(m["listed"] for m in modules), "classes": len(classes),
                   "object properties": sum(p["kind"] == "ObjectProperty" for p in props),
                   "datatype properties": sum(p["kind"] == "DatatypeProperty" for p in props),
                   "individuals": len(onto.get("individuals") or []), "axioms": len(onto.get("axioms") or []),
                   **({"class restrictions": len(onto["restrictions"])} if onto.get("restrictions") else {})},
        "vocabularies": vocabs, "cqs": cqs, "evaluation": ev,
        "upper": [c for c in classes if c["upper"]],
        "core": [p for p in props if p["module"] == "CoreRelations"],
        "modules": modules, "excluded": excluded, "declined": declined,
        "references": sorted(references, key=str.lower),
    }


def _eval_lines(ev) -> list:
    if not ev:
        return []
    out = []
    cov, hi, cq, ho = ev.get("coverage") or {}, ev.get("hierarchy") or {}, ev.get("cq") or {}, ev.get("holdout") or {}
    if cov.get("available"):
        out.append(f"Central concepts of the literature as a class: {cov.get('central_covered_pct')} % "
                   f"({cov.get('central_covered')} of {cov.get('central_concepts')}); represented in some form: "
                   f"{cov.get('central_represented_pct')} %")
    if hi.get("available") and hi.get("relations"):
        out.append(f"Broader/narrower relations of the literature realized: {hi.get('realized')} of {hi.get('relations')}"
                   + (f"; declined with a reason: {hi.get('declined_count')}" if hi.get("declined_count") is not None else ""))
    if cq.get("total"):
        out.append(f"Competency questions: {cq.get('full')} answered in full, {cq.get('partial')} partly, "
                   f"{cq.get('none')} not (of {cq.get('total')})")
    if ho.get("total"):
        out.append(f"Hold-out questions from the literature: {ho.get('full')} in full, {ho.get('partial')} partly, "
                   f"{ho.get('none')} not (of {ho.get('total')})")
    r = (ev.get("reasoner") or {}).get("ontology") or {}
    if r.get("consistent") is not None:
        out.append("Reasoner (HermiT): " + ("consistent" if r["consistent"] else "inconsistent") +
                   (f", {len(r.get('unsatisfiable') or [])} unsatisfiable classes" if r.get("unsatisfiable") else ""))
    return out

_LEVEL = {"full": "answered", "partial": "partly answered", "none": "not answered"}


# ── Markdown ───────────────────────────────────────────────────────────────────

def _md(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).replace("|", "\\|").strip()

def _restriction(r) -> str:
    n = f" {r['n']}" if r.get("kind") in ("min", "max", "exactly") else ""
    return f"{r.get('property')} {r.get('kind')}{n} {r.get('value')}"

def _md_class(c, lang) -> list:
    label = c["labels"].get(lang) or next(iter(c["labels"].values()), "")
    out = [f"#### {c['name']}" + (f" - {_md(label)}" if label and label != c["name"] else ""), ""]
    if c["description"]:
        out += [_md(c["description"]), ""]
    others = {l: v for l, v in c["labels"].items() if l != lang}
    facts = []
    if c["superclasses"]:
        facts.append("Superclass: " + ", ".join(f"`{s}`" for s in c["superclasses"]))
    if c["equivalent"]:
        facts.append("Same meaning as: " + ", ".join(f"`{s}`" for s in c["equivalent"]))
    if c["restrictions"]:
        facts.append("Restrictions: " + "; ".join(_md(r.get("natural_language") or "") + f" (`{_md(_restriction(r))}`)"
                                                  for r in c["restrictions"]))
    if others:
        facts.append("Labels: " + "; ".join(f"{_md(v)} ({l})" for l, v in others.items()))
    if c["individuals"]:
        facts.append("Individuals: " + ", ".join(f"`{i}`" for i in c["individuals"]))
    if c["concepts"]:
        facts.append("Concepts of the literature: " + ", ".join(_md(x) for x in c["concepts"]))
    if c["sources"]:
        facts.append("Sources: " + "; ".join(_md(s) for s in c["sources"]))
    if c["see_also"]:
        facts.append("See also: " + ", ".join(f"<{u}>" for u in c["see_also"]))
    out += [f"- {f}" for f in facts]
    if c["literature"]:
        out += ["", "Definitions in the literature:", ""]
        for x in c["literature"]:
            quote = f' - "{_md(x["quote"])}"' if x["quote"] and x["quote_ok"] else ""
            page = f", p. {x['page']}" if x["page"] else ""
            out.append(f"> **{_md(x['term'])}**: {_md(x['definition'])}{quote} ({_md(x['source'])}{page})")
            out.append(">")
        out.pop()
    return out + [""]

def _md_props(props) -> list:
    if not props:
        return []
    out = ["| Property | Kind | Domain -> Range | Below | Description |", "|---|---|---|---|---|"]
    for p in props:
        extra = ", ".join(x for x in [f"inverse `{p['inverse']}`" if p["inverse"] else "",
                                      ", ".join(p["characteristics"])] if x)
        out.append(f"| `{p['name']}` | {'object' if p['kind'] == 'ObjectProperty' else 'datatype'} | "
                   f"{p['domain'] or '(any)'} -> {p['range'] or '(any)'} | {p['super'] or ''} | "
                   f"{_md(p['description'])}{' (' + extra + ')' if extra else ''} |")
    return out + [""]

def to_markdown(doc) -> str:
    lang = doc["languages"][0]
    out = [f"# {doc['title']}", "", f"*Documentation generated on {doc['generated']} by LITMO.*",
           ""]
    if doc["summary"]:
        out += [_md(doc["summary"]), ""]
    facts = [f"- Namespace: `{doc['namespace']}`" if doc["namespace"] else "",
             f"- License: {doc['license']}" if doc["license"] else "",
             "- " + ", ".join(f"{v} {k}" for k, v in doc["counts"].items()),
             "- Label languages: " + ", ".join(doc["languages"]),
             ("- Reused vocabularies: " + ", ".join(f"`{p}` ({_md(n)})" for p, n in doc["vocabularies"]))
             if doc["vocabularies"] else ""]
    out += [x for x in facts if x] + [""]
    out += ["## Contents", ""] + [f"{k}. {m['name']}" for k, m in enumerate(doc["modules"], 1)] + [""]
    if doc["cqs"]:
        out += ["## Competency questions", ""]
        out += [f"{k}. {_md(q)}" + (f" - *{_LEVEL.get(lvl, lvl)}*" if lvl else "") for k, (q, lvl) in enumerate(doc["cqs"], 1)]
        out.append("")
    ev = _eval_lines(doc["evaluation"])
    if ev:
        it = doc["evaluation"]
        out += ["## Evaluation", "", f"Evaluated on {str(it.get('evaluated_at') or '')[:10]} (iteration {it.get('iteration')}):",
                ""] + [f"- {x}" for x in ev] + [""]
    if doc["upper"]:
        out += ["## Upper layer", "", "Every top class of the modules lies below one of these classes.", ""]
        for c in doc["upper"]:
            out.append(f"- `{c['name']}`: {_md(c['description'])}")
        out.append("")
    if doc["core"]:
        out += ["## Core relations", "", "General relations approved for the whole ontology; module relations are "
                "placed below them where they share their meaning.", ""] + _md_props(doc["core"])
    for k, m in enumerate(doc["modules"], 1):
        out += [f"## {k}. {m['heading']}", ""]
        if m["documentation"]:
            out += [_md(m["documentation"]), ""]
        meta = [f"Key notion: {m['key_notion']}" if m["key_notion"] and m["key_notion"] != m["name"] else "",
                f"Pattern: {m['pattern']}" if m["pattern"] else "",
                f"{len(m['classes'])} classes, {len(m['properties'])} properties"]
        out += ["*" + " · ".join(x for x in meta if x) + "*", ""]
        if m["classes"]:
            out += ["### Diagram", "", "```mermaid", m["diagram"], "```", "",
                    "### Class hierarchy", ""]
            out += [f"{'  ' * d}- `{n}`" + (f" (below `{p}`)" if p else "") for d, n, p in m["tree"]] + [""]
            out += ["### Classes", ""]
            for c in m["classes"]:
                out += _md_class(c, lang)
        if m["properties"]:
            out += ["### Properties", ""] + _md_props(m["properties"])
        if m["axioms"]:
            out += ["### Axioms", ""] + [f"- {a.get('type')}({', '.join(a.get('classes') or [])})" +
                                         (f": {_md(a['natural_language'])}" if a.get("natural_language") else "")
                                         for a in m["axioms"]] + [""]
    if doc["excluded"] or doc["declined"]:
        out += ["## For the review: decisions with reasons", ""]
        if doc["excluded"]:
            out += ["### Central concepts deliberately not modelled", "", "| Concept | Sources | Reason |", "|---|---|---|"]
            out += [f"| {_md(l)} | {n} | {_md(r)} |" for l, n, r in doc["excluded"]] + [""]
        if doc["declined"]:
            out += ["### Broader terms of the literature not adopted", "", "| Relation | Reason |", "|---|---|"]
            out += [f"| {_md(i)} | {_md(r)} |" for i, r in doc["declined"]] + [""]
    if doc["references"]:
        out += ["## References", ""] + [f"- {_md(r)}" for r in doc["references"]] + [""]
    return "\n".join(out)


# ── HTML ───────────────────────────────────────────────────────────────────────

def _h(text) -> str:
    return html.escape(str(text or ""))

def _anchor(prefix, name) -> str:
    return prefix + "-" + re.sub(r"[^A-Za-z0-9_-]", "_", str(name))

CSS = """
:root { --text: #1d2433; --muted: #5b6475; --line: #dde2ea; --accent: #2457a6; --bg: #ffffff; --soft: #f5f7fa; }
@media (prefers-color-scheme: dark) { :root { --text: #e6e9ef; --muted: #a2abbb; --line: #384152; --accent: #8ab4f8;
  --bg: #161a21; --soft: #1e2430; } }
body { font: 15px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; color: var(--text); background: var(--bg);
  max-width: 980px; margin: 0 auto; padding: 24px 16px 80px; }
h1 { font-size: 1.9rem; margin-bottom: 4px; } h2 { margin-top: 2.4em; border-bottom: 2px solid var(--line);
  padding-bottom: 4px; } h3 { margin-top: 1.6em; } h4 { margin: 1.4em 0 .3em; }
a { color: var(--accent); } code { font-size: .9em; background: var(--soft); padding: 1px 4px; border-radius: 3px; }
.muted { color: var(--muted); } .meta { color: var(--muted); font-size: .9em; }
table { border-collapse: collapse; width: 100%; font-size: .9em; margin: .6em 0; display: block; overflow-x: auto; }
th, td { border: 1px solid var(--line); padding: 4px 8px; text-align: left; vertical-align: top; }
th { background: var(--soft); }
blockquote { margin: .4em 0; padding: 4px 12px; border-left: 3px solid var(--line); color: var(--muted); }
.class { border-top: 1px solid var(--line); padding-top: 2px; }
ul.tree { list-style: none; padding-left: 1.2em; } ul.tree ul { list-style: none; padding-left: 1.2em; }
pre.mermaid { background: var(--soft); padding: 8px; overflow-x: auto; font-size: .8em; }
nav ol { columns: 2; } @media (max-width: 640px) { nav ol { columns: 1; } }
"""

def _html_cls_link(name, known) -> str:
    return f'<a href="#{_anchor("c", name)}"><code>{_h(name)}</code></a>' if name in known else f"<code>{_h(name)}</code>"

def _html_props(props, known) -> str:
    if not props:
        return ""
    rows = []
    for p in props:
        extra = ", ".join(x for x in [f"inverse <code>{_h(p['inverse'])}</code>" if p["inverse"] else "",
                                      _h(", ".join(p["characteristics"]))] if x)
        below = f"<code>{_h(p['super'])}</code>" if p["super"] else ""
        rows.append(f"<tr><td id=\"{_anchor('p', p['name'])}\"><code>{_h(p['name'])}</code></td>"
                    f"<td>{'object' if p['kind'] == 'ObjectProperty' else 'datatype'}</td>"
                    f"<td>{_html_cls_link(p['domain'], known) if p['domain'] else '(any)'} &rarr; "
                    f"{_html_cls_link(p['range'], known) if p['range'] else '(any)'}</td>"
                    f"<td>{below}</td><td>{_h(p['description'])}{' (' + extra + ')' if extra else ''}</td></tr>")
    return ("<table><tr><th>Property</th><th>Kind</th><th>Domain &rarr; Range</th><th>Below</th><th>Description</th></tr>"
            + "".join(rows) + "</table>")

def _html_tree(tree, known) -> str:
    out, depth = [], -1
    for d, name, outside in tree:
        if d > depth:
            out.append('<ul class="tree">' * (d - depth))
        elif d < depth:
            out.append("</li></ul>" * (depth - d) + "</li>")
        else:
            out.append("</li>")
        out.append(f"<li>{_html_cls_link(name, known)}" +
                   (f' <span class="muted">(below {_html_cls_link(outside, known)})</span>' if outside else ""))
        depth = d
    if depth >= 0:
        out.append("</li></ul>" * (depth + 1))
    return "".join(out)

def _html_class(c, lang, known) -> str:
    label = c["labels"].get(lang) or next(iter(c["labels"].values()), "")
    out = [f'<div class="class"><h4 id="{_anchor("c", c["name"])}"><code>{_h(c["name"])}</code>' +
           (f' <span class="muted">{_h(label)}</span>' if label and label != c["name"] else "") + "</h4>"]
    if c["description"]:
        out.append(f"<p>{_h(c['description'])}</p>")
    facts = []
    if c["superclasses"]:
        facts.append("Superclass: " + ", ".join(_html_cls_link(s, known) for s in c["superclasses"]))
    if c["equivalent"]:
        facts.append("Same meaning as: " + ", ".join(_html_cls_link(s, known) for s in c["equivalent"]))
    if c["restrictions"]:
        facts.append("Restrictions: " + "; ".join(f"{_h(r.get('natural_language') or '')} (<code>{_h(_restriction(r))}</code>)"
                                                  for r in c["restrictions"]))
    others = {l: v for l, v in c["labels"].items() if l != lang}
    if others:
        facts.append("Labels: " + "; ".join(f"{_h(v)} ({_h(l)})" for l, v in others.items()))
    if c["individuals"]:
        facts.append("Individuals: " + ", ".join(f"<code>{_h(i)}</code>" for i in c["individuals"]))
    if c["concepts"]:
        facts.append("Concepts of the literature: " + _h(", ".join(c["concepts"])))
    if c["sources"]:
        facts.append("Sources: " + _h("; ".join(c["sources"])))
    if c["see_also"]:
        facts.append("See also: " + ", ".join(f'<a href="{_h(u)}">{_h(u)}</a>' for u in c["see_also"]))
    if facts:
        out.append('<ul class="meta">' + "".join(f"<li>{f}</li>" for f in facts) + "</ul>")
    for x in c["literature"]:
        quote = f' &ndash; &ldquo;{_h(x["quote"])}&rdquo;' if x["quote"] and x["quote_ok"] else ""
        page = f", p. {_h(x['page'])}" if x["page"] else ""
        out.append(f"<blockquote><strong>{_h(x['term'])}</strong>: {_h(x['definition'])}{quote} "
                   f"({_h(x['source'])}{page})</blockquote>")
    return "".join(out) + "</div>"

def to_html(doc) -> str:
    lang = doc["languages"][0]
    known = {c["name"] for m in doc["modules"] for c in m["classes"]} | {c["name"] for c in doc["upper"]}
    body = [f"<h1>{_h(doc['title'])}</h1>",
            f'<p class="meta">Documentation generated on {_h(doc["generated"])} by LITMO.</p>']
    if doc["summary"]:
        body.append(f"<p>{_h(doc['summary'])}</p>")
    facts = [f"Namespace: <code>{_h(doc['namespace'])}</code>" if doc["namespace"] else "",
             f"License: {_h(doc['license'])}" if doc["license"] else "",
             _h(", ".join(f"{v} {k}" for k, v in doc["counts"].items())),
             "Label languages: " + _h(", ".join(doc["languages"])),
             ("Reused vocabularies: " + ", ".join(f"<code>{_h(p)}</code> ({_h(n)})" for p, n in doc["vocabularies"]))
             if doc["vocabularies"] else ""]
    body.append("<ul>" + "".join(f"<li>{f}</li>" for f in facts if f) + "</ul>")
    body.append("<nav><h2>Contents</h2><ol>" + "".join(f'<li><a href="#{_anchor("m", m["name"])}">{_h(m["name"])}</a></li>'
                                                     for m in doc["modules"]) + "</ol></nav>")
    if doc["cqs"]:
        body.append("<h2>Competency questions</h2><ol>" + "".join(
            f"<li>{_h(q)}" + (f' <span class="muted">&ndash; {_h(_LEVEL.get(l, l))}</span>' if l else "") + "</li>"
            for q, l in doc["cqs"]) + "</ol>")
    ev = _eval_lines(doc["evaluation"])
    if ev:
        it = doc["evaluation"]
        body.append(f"<h2>Evaluation</h2><p class=\"meta\">Evaluated on {_h(str(it.get('evaluated_at') or '')[:10])} "
                    f"(iteration {_h(it.get('iteration'))}).</p><ul>" + "".join(f"<li>{_h(x)}</li>" for x in ev) + "</ul>")
    if doc["upper"]:
        body.append("<h2>Upper layer</h2><p>Every top class of the modules lies below one of these classes.</p><ul>" +
                    "".join(f'<li id="{_anchor("c", c["name"])}"><code>{_h(c["name"])}</code>: {_h(c["description"])}</li>'
                            for c in doc["upper"]) + "</ul>")
    if doc["core"]:
        body.append("<h2>Core relations</h2><p>General relations approved for the whole ontology; module relations are "
                    "placed below them where they share their meaning.</p>" + _html_props(doc["core"], known))
    for k, m in enumerate(doc["modules"], 1):
        body.append(f'<h2 id="{_anchor("m", m["name"])}">{k}. {_h(m["heading"])}</h2>')
        if m["documentation"]:
            body.append(f"<p>{_h(m['documentation'])}</p>")
        meta = [f"Key notion: {_h(m['key_notion'])}" if m["key_notion"] and m["key_notion"] != m["name"] else "",
                f"Pattern: {_h(m['pattern'])}" if m["pattern"] else "",
                f"{len(m['classes'])} classes, {len(m['properties'])} properties"]
        body.append('<p class="meta">' + " &middot; ".join(x for x in meta if x) + "</p>")
        if m["classes"]:
            body.append(f'<h3>Diagram</h3><pre class="mermaid">{_h(m["diagram"])}</pre>')
            body.append("<h3>Class hierarchy</h3>" + _html_tree(m["tree"], known))
            body.append("<h3>Classes</h3>" + "".join(_html_class(c, lang, known) for c in m["classes"]))
        if m["properties"]:
            body.append("<h3>Properties</h3>" + _html_props(m["properties"], known))
        if m["axioms"]:
            body.append("<h3>Axioms</h3><ul>" + "".join(
                f"<li>{_h(a.get('type'))}({_h(', '.join(a.get('classes') or []))})" +
                (f": {_h(a['natural_language'])}" if a.get("natural_language") else "") + "</li>" for a in m["axioms"]) + "</ul>")
    if doc["excluded"] or doc["declined"]:
        body.append("<h2>For the review: decisions with reasons</h2>")
        if doc["excluded"]:
            body.append("<h3>Central concepts deliberately not modelled</h3><table><tr><th>Concept</th><th>Sources</th>"
                        "<th>Reason</th></tr>" + "".join(f"<tr><td>{_h(l)}</td><td>{n}</td><td>{_h(r)}</td></tr>"
                                                         for l, n, r in doc["excluded"]) + "</table>")
        if doc["declined"]:
            body.append("<h3>Broader terms of the literature not adopted</h3><table><tr><th>Relation</th><th>Reason</th></tr>"
                        + "".join(f"<tr><td>{_h(i)}</td><td>{_h(r)}</td></tr>" for i, r in doc["declined"]) + "</table>")
    if doc["references"]:
        body.append("<h2>References</h2><ul>" + "".join(f"<li>{_h(r)}</li>" for r in doc["references"]) + "</ul>")
    return (f'<!doctype html><html lang="{_h(lang)}"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1"><title>{_h(doc["title"])}</title>'
            f"<style>{CSS}</style></head><body>" + "\n".join(body) +
            f'<script src="{MERMAID_SRC}"></script><script>if (window.mermaid) mermaid.initialize({{startOnLoad: true, '
            f"maxTextSize: 200000, class: {{useMaxWidth: false}}, theme: matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'default'}});"
            "</script></body></html>")
