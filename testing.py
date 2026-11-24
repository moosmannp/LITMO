"""Competency Questions als Testfaelle: SPARQL gegen Beispieldaten."""

import copy, re
from decimal import Decimal

from rdflib import Literal

from llm import _run_llm_json, usage_step
from project import _ctx, MOMO_METHOD, _norm, nth
from ontology_io import KNOWN_PREFIXES

# rdflib wertet EXISTS nur in FILTER aus; im SELECT, in BIND oder IF scheitert die Abfrage beim Lesen der Zeilen
# (VA 5c, Bruecken: mehrfach bei Ja/Nein-Fragen; DECISIONS 135, 136)
EXISTS_RULE = ("Use EXISTS and NOT EXISTS only inside FILTER - never in the SELECT list, in BIND or in IF, which the "
               "query engine cannot evaluate; for a yes/no value per result use OPTIONAL and BOUND(?x).")

CQ_TEST_SYS = (MOMO_METHOD + "\nMOMo treats competency questions as TEST CASES for the ontology. For each CQ, write "
               "ONE SPARQL 1.1 SELECT or ASK query that answers it against the given ontology, and write a small set "
               "of example instance data on which these queries return a meaningful answer.\n"
               "Rules:\n"
               "1. Use ONLY classes and properties declared in the ontology, spelled exactly as declared. Never invent "
               "a term. If the ontology lacks what a CQ needs, set \"sparql\" to null and say in \"missing\" which "
               "classes or properties are missing — that is a legitimate and useful result.\n"
               "2. The prefixes of the ontology are predeclared for both the queries and the instance data, "
               "including the empty prefix ':' for the ontology namespace. Do not write @prefix or PREFIX lines. "
               + EXISTS_RULE + "\n"
               "3. Instance data: Turtle triples only, with new individuals in the ontology namespace (e.g. "
               ":exampleRecipe1), typed with ontology classes and linked only via ontology properties. The "
               "ontology's own individuals may be used and described as well. Do not declare or change classes or "
               "properties. Keep it small (about 5-25 individuals) but make sure every "
               "query has data to answer it.\n"
               "4. Queries must answer the question from the instance data, not by listing schema terms. SELECT "
               "what the question asks for, at the level it asks: a question about kinds (\"which characteristics "
               "...\") returns the kinds, DISTINCT, not every individual with its context; add a variable only "
               "where the question names it. \"expected\" describes that answer on your sample data.\n"
               "5. A query must answer the WHOLE question, with individuals of the classes the question means. If the "
               "ontology allows only part of it, still write the query for that part, and say in \"leaves_out\" which "
               "INFORMATION the question asks for that the query cannot return - a ranking or choice of one where "
               "the ontology records nothing to rank by, a comparison, a change over time, a class or relation that "
               "is not modelled. Never answer an easier question silently.\n"
               "   \"leaves_out\" is NOT for judgements the person asking makes from the returned facts: which of "
               "the listed things they should consider, whether a returned value counts as good or high enough, "
               "how much something matters when the question only asks whether or which. If the query returns the "
               "facts needed to make that judgement (e.g. the characteristics, or a quality value to sort by), "
               "\"leaves_out\" is null.\n"
               'Answer ONLY as JSON: {"sample_data":"Turtle triples","tests":[{"cq":1,"sparql":"SELECT ... or null",'
               '"expected":"what a correct answer on the sample data looks like","missing":"null or what is missing",'
               '"leaves_out":"null or the information the question asks for that the query cannot return"}]}')

# Pruefung der Teilantworten (DECISIONS 107): die Regel "leaves_out ist keine Bewertung" haelt das Modell, das die
# Abfrage schreibt, nicht ein (VA-Laeufe 3a-3c: 8, 4 und 2 volle Antworten, die meisten Teilantworten bewerteten).
# Ein eigener kurzer Aufruf sieht nur Frage, Abfrage, Ergebniszeilen und die genannte Luecke - nicht die eigene Arbeit.
CQ_CHECK_SYS = (
    "You review competency-question tests that their author marked as answering only PART of the question. Each item "
    "gives the question, the SPARQL query, the first rows it returned on sample data, and the gap the author stated. "
    "Decide for each item whether the gap is:\n"
    "- \"missing\": information the question itself asks for - it names it, or it is what the question's which/what/"
    "how asks for - and the returned rows do not contain it: a ranking or comparison the question asks for, an "
    "attribute or relation the question names, a kind of thing that is not modelled;\n"
    "- \"beyond\": not something the question asks the ontology to return: a judgement about the returned facts "
    "(whether something is good, sufficient, effective, justified, or really caused something), a proof or certainty "
    "the question does not ask for, more detail than the question asks, or information the answer contains in "
    "another form (e.g. through the returned individuals' types).\n"
    "Decide by the question's wording, not by what would be nice to know. When in doubt, \"missing\".\n"
    'Answer ONLY as JSON: {"checks":[{"item":1,"verdict":"missing|beyond","reason":"one sentence"}]}')
CQ_CHECK_ROWS = 5

def check_partial_answers(entries, llm_config, step) -> str:
    """Laesst die Teilantworten pruefen; eine Luecke, die ueber die Frage hinausgeht, macht die Antwort voll (die
    Anmerkung bleibt). Liefert eine Fehlermeldung, wenn der Aufruf scheitert - dann bleibt alles, wie es war."""
    partial = [e for e in entries if e.get("status") == "partial"]
    if not partial:
        return ""
    items = "\n\n".join(
        f"Item {k}. Question: {e['question']}\nQuery: {e['sparql']}\nRows ({e.get('row_count', 0)} in total): " +
        "; ".join(", ".join(f"{a}={b}" for a, b in r.items()) for r in (e.get("rows") or [])[:CQ_CHECK_ROWS]) +
        f"\nStated gap: {e['leaves_out']}" for k, e in enumerate(partial, 1))
    try:
        with usage_step(step + " (check of partial answers)"):
            result = _run_llm_json(llm_config, [{"role": "system", "content": CQ_CHECK_SYS},
                                                {"role": "user", "content": items}])
    except Exception as ex:               # die Pruefung ist ein Zusatz: ohne sie bleiben die Teilantworten
        return f"The check of partial answers failed ({str(getattr(ex, 'detail', ex))[:150]}); they stay partial."
    for x in (result or {}).get("checks") or []:
        try:
            e = nth(partial, x.get("item"))
        except (TypeError, ValueError, IndexError):
            continue
        if e is None:
            continue
        verdict = str(x.get("verdict") or "").strip()
        if verdict not in ("missing", "beyond"):
            continue
        e["gap_check"] = {"verdict": verdict, "reason": str(x.get("reason") or "").strip()[:300]}
        if verdict == "beyond":
            e.update(status="passed", error="")
    return ""

# Korrektur von Abfragen ohne Ergebnis (DECISIONS 109): VA-Laeufe 3b/3c - eine lange Kette von Verknuepfungen, zu
# der die eigenen Beispieldaten nicht passen, ergibt "No result on the sample data", obwohl der Ontologie nichts fehlt.
NO_RESULT = ("No result on the sample data.", "ASK returned false on the sample data.")
CQ_FIX_SYS = (
    "Some competency-question tests returned NO result on their own sample data, although every term they use is "
    "declared in the ontology. For each item you get the question, the query, the ontology terms the query uses (with "
    "domain and range), and the current sample data. Usually triples are missing for one link of the query's chain, "
    "or the data use another property than the query. Fix each test:\n"
    "- add the sample triples the query needs (Turtle triples only, no @prefix lines; the ontology's prefixes, "
    "including ':', are predeclared; new individuals in the ontology namespace, typed with ontology classes, linked "
    "only via ontology properties within their domain and range; never declare classes or properties);\n"
    "- and/or correct the query, if it asks more or other than the question needs. The query must still answer the "
    "WHOLE question; if it can answer only part of it, say in \"leaves_out\" which information the question asks "
    "for that it cannot return. Never answer an easier question silently. " + EXISTS_RULE + "\n"
    'Answer ONLY as JSON: {"fixes":[{"item":1,"sample_data":"triples to add, or empty",'
    '"sparql":"the corrected query, or null to keep it","leaves_out":"null or the information it cannot return"}]}')

def _query_terms(q_text, onto_g) -> list:
    """Die Ontologie-Terme einer Abfrage mit Art, Domain/Range bzw. Oberklassen - als Zeilen fuer die Korrektur."""
    from rdflib import URIRef
    from rdflib.namespace import RDF, RDFS
    from rdflib.plugins.sparql import prepareQuery
    try:
        q = prepareQuery(q_text, initNs=_test_namespaces(onto_g))
    except Exception:
        return []
    used = set()
    _query_uris(q.algebra, used, set())
    lines = []
    for u in sorted((u for u in used if not _is_builtin(u)), key=str):
        kinds = sorted({_short(o, onto_g) for o in onto_g.objects(u, RDF.type)})
        line = f"{_short(u, onto_g)}: {', '.join(kinds) or 'not declared'}"
        dom = [_short(o, onto_g) for o in onto_g.objects(u, RDFS.domain) if isinstance(o, URIRef)]
        rng = [_short(o, onto_g) for o in onto_g.objects(u, RDFS.range) if isinstance(o, URIRef)]
        if dom or rng:
            line += f", {' and '.join(dom) or '(any)'} -> {' and '.join(rng) or '(any)'}"
        sup = [_short(o, onto_g) for o in onto_g.objects(u, RDFS.subClassOf) if isinstance(o, URIRef)]
        if sup:
            line += f", below {', '.join(sup)}"
        lines.append(line)
    return lines

def correct_empty_queries(empty, sample, onto_g, issues, llm_config, step):
    """Eine Korrekturrunde fuer Abfragen ohne Ergebnis. Liefert (zusaetzliche Beispieldaten je Test als Texte,
    {cq: {"sparql", "leaves_out"}}) oder eine Fehlermeldung - dann bleibt alles, wie es war."""
    data = "\n".join(line for line in sample.serialize(format="turtle").splitlines()
                     if not line.startswith("@prefix")).strip() if len(sample) else "(none)"
    items = "\n\n".join(f"Item {k}. Question: {e['question']}\nQuery: {e['sparql']}\nTerms it uses:\n" +
                        "\n".join("- " + t for t in _query_terms(e["sparql"], onto_g)) for k, e in enumerate(empty, 1))
    dropped = ("\n\n**Sample triples the server dropped** (they did not fit the ontology):\n" +
               "\n".join("- " + x for x in issues[-10:])) if issues else ""
    try:
        with usage_step(step + " (correction of queries without result)"):
            result = _run_llm_json(llm_config, [{"role": "system", "content": CQ_FIX_SYS},
                                                {"role": "user", "content": items + "\n\n**Current sample data:**\n" +
                                                 data + dropped}])
    except Exception as ex:               # die Korrektur ist ein Zusatz: ohne sie bleiben die Tests gescheitert
        return f"The correction of queries without result failed ({str(getattr(ex, 'detail', ex))[:150]})."
    triples, queries = [], {}
    for x in (result or {}).get("fixes") or []:
        try:
            e = nth(empty, x.get("item"))
        except (TypeError, ValueError, IndexError, AttributeError):
            continue
        if e is None:
            continue
        if _stated(x.get("sample_data")):
            triples.append(str(x["sample_data"]))
        if _stated(x.get("sparql")):
            queries[e["cq"]] = {"sparql": str(x["sparql"]), "leaves_out": _stated(x.get("leaves_out")),
                                "corrected": True}
    return triples, queries

def _stated(v) -> str:
    """Ein Freitextfeld des Modells, ohne die Platzhalter, mit denen es 'nichts' sagt."""
    v = str(v or "").strip()
    return "" if v.lower().rstrip(".") in ("", "null", "none", "nothing", "n/a", "-") else v

def build_cq_test_prompt(turtle, cqs, context="", existing_sample=""):
    existing = ("\n\n**Existing sample data** (already loaded and kept - reuse its individuals where they fit; in "
                "\"sample_data\" write ONLY the triples you add, never repeat or change these):\n" + existing_sample
                if existing_sample else "")
    return [
        {"role": "system", "content": CQ_TEST_SYS},
        {"role": "user", "content": "**Ontology (Turtle):**\n" + turtle + _ctx(context) + existing +
         "\n\n**Competency questions:**\n" + "\n".join(f"{i}. {q}" for i, q in enumerate(cqs, 1)) +
         "\n\nWrite one test per competency question, numbered as above."}
    ]

# ── Competency Questions als Testfaelle ────────────────────────────────────────
# Frueher meldete das LLM per "cq_coverage" selbst, ob jede CQ abgedeckt ist — es bewertete also seine eigene
# Arbeit. Jetzt schreibt es nur noch Abfragen und Beispieldaten; ob eine CQ abgedeckt ist, entscheidet rdflib.
_BUILTIN_NS = ("http://www.w3.org/1999/02/22-rdf-syntax-ns#", "http://www.w3.org/2000/01/rdf-schema#",
               "http://www.w3.org/2002/07/owl#", "http://www.w3.org/2001/XMLSchema#")
_MAX_ROWS = 5

def _is_builtin(term) -> bool:
    return str(term).startswith(_BUILTIN_NS)

def _query_uris(node, out, seen):
    """Sammelt alle IRIs aus der Algebra einer geparsten SPARQL-Abfrage (inkl. Property-Paths)."""
    from rdflib import URIRef
    from rdflib.paths import Path
    if isinstance(node, URIRef):
        out.add(node)
        return
    if id(node) in seen:
        return
    seen.add(id(node))
    if isinstance(node, Path):
        children = vars(node).values()
    elif isinstance(node, dict):
        children = node.values()
    elif isinstance(node, (list, tuple, set, frozenset)):
        children = node
    else:
        return
    for child in children:
        _query_uris(child, out, seen)

def _short(term, g) -> str:
    from rdflib import URIRef
    if isinstance(term, URIRef):
        try:
            return g.namespace_manager.normalizeUri(term)
        except Exception:
            return str(term)
    return str(term)

def _is_schema_statement(p, o) -> bool:
    """Eine Aussage, die einen Begriff zur Klasse oder Property macht oder ihn in die Hierarchie haengt."""
    from rdflib.namespace import RDF, RDFS, OWL
    if p == RDF.type:
        return _is_builtin(o) and o not in (OWL.NamedIndividual, OWL.Thing)
    return p in (RDFS.subClassOf, RDFS.subPropertyOf, RDFS.domain, RDFS.range, OWL.equivalentClass,
                 OWL.equivalentProperty, OWL.disjointWith, OWL.inverseOf)

def _split_sample_data(sample, onto_terms, onto_individuals=frozenset()):
    """Trennt Beispieldaten in gueltige und ungueltige Tripel. Gueltig sind nur Instanzdaten, die
    ausschliesslich Klassen und Properties der Ontologie verwenden — sonst koennte eine Abfrage mit
    erfundenen Termen auf ebenso erfundenen Daten 'bestehen'. Ueber die Individuen der Ontologie (z.B. Bordeaux)
    duerfen die Daten Aussagen machen; nur Schema-Aussagen ueber Ontologie-Terme werden verworfen (Wein-Lauf 2)."""
    from rdflib import Graph
    from rdflib.namespace import RDF, OWL
    valid, issues = Graph(), []
    for s, p, o in sample:
        if s in onto_terms and (s not in onto_individuals or _is_schema_statement(p, o)):
            issues.append(f"{_short(s, sample)}: changes an ontology term instead of describing an individual")
        elif p == RDF.type and o not in onto_terms and o not in (OWL.NamedIndividual, OWL.Thing):
            issues.append(f"{_short(s, sample)} is typed with undeclared class {_short(o, sample)}")
        elif p != RDF.type and p not in onto_terms and not _is_builtin(p):
            issues.append(f"{_short(s, sample)} uses undeclared property {_short(p, sample)}")
        else:
            valid.add((s, p, o))
    return valid, issues

def _test_namespaces(onto_g) -> dict:
    """Prefixe fuer Beispieldaten und Abfragen: die der Ontologie, ergaenzt um gaengige Vokabulare. Ein
    unbekannter Prefix (z.B. dct:) wuerde sonst die gesamten Beispieldaten bzw. die Abfrage unparsebar machen;
    ob die Terme in der Ontologie existieren, wird danach ohnehin geprueft."""
    ns = {pfx: uri for pfx, uri in KNOWN_PREFIXES.values()}
    ns["dct"] = "http://purl.org/dc/terms/"
    ns.update({str(pfx): str(uri) for pfx, uri in onto_g.namespaces()})
    return ns

def _data_individuals(sample) -> set:
    """Alle Individuen der Beispieldaten: was als Subjekt oder Objekt vorkommt, ausser als Klasse einer
    rdf:type-Aussage - auch ohne eigenen Typ (Wein-Lauf 7: :Napa als Objekt von hasOrigin galt sonst als nicht
    deklarierter Term). Erfundene Klassen und Properties fallen weiter auf."""
    from rdflib import URIRef
    from rdflib.namespace import RDF
    out = set()
    for s, p, o in sample:
        if isinstance(s, URIRef):
            out.add(s)
        if isinstance(o, URIRef) and p != RDF.type:
            out.add(o)
    return out

def _answers_from_schema(q, onto_g, schema_terms) -> bool:
    """Liefert die Abfrage schon auf dem Schema allein ein Ergebnis - der Ontologie ohne die Aussagen ueber ihre
    Individuen? Dann listet sie Schema-Terme auf, statt die Frage aus Daten zu beantworten. Eine Klasse als Antwort
    ist erlaubt, wenn sie aus Daten kommt (Wein-Lauf 6: "Ist Bordeaux rot oder weiss?" -> :RedWine, der Typ eines
    Individuums)."""
    from rdflib import BNode, Graph
    g = Graph()
    for t in onto_g:
        if t[0] in schema_terms or isinstance(t[0], BNode):
            g.add(t)
    try:
        return any(any(v is not None for v in r) for r in g.query(q))
    except Exception:
        return True                       # im Zweifel wie bisher: nur Ontologie-Terme zaehlen nicht

def _run_cq_test(q_text, onto_g, data_g, onto_terms, schema_terms, sample_individuals):
    """Fuehrt eine CQ-Abfrage aus. Abgedeckt nur, wenn sie parst, nur existierende Terme verwendet und auf
    den Beispieldaten ein Ergebnis liefert, das nicht bloss aus Schema-Termen besteht - es sei denn, dieses Ergebnis
    haengt von Daten ab (die Abfrage liefert es auf dem Schema allein nicht)."""
    from rdflib.plugins.sparql import prepareQuery
    res = {"parses": False, "unknown_terms": [], "result_ok": False, "rows": [], "row_count": 0, "error": "",
           "terms": []}
    try:
        q = prepareQuery(q_text, initNs=_test_namespaces(onto_g))
    except Exception as ex:
        res["error"] = f"SPARQL does not parse: {ex}"
        return res
    res["parses"] = True
    if q.algebra.name not in ("SelectQuery", "AskQuery"):
        res["error"] = "Only SELECT and ASK queries are accepted as CQ tests."
        return res

    used = set()
    _query_uris(q.algebra, used, set())
    # Lokale Namen der verwendeten Ontologie-Terme: fuer die Evaluation (welche Klassen braucht eine CQ?)
    res["terms"] = sorted({re.split(r"[#/]", str(u).rstrip("#/"))[-1] for u in used
                           if u in onto_terms and not _is_builtin(u)})
    unknown = sorted(_short(u, onto_g) for u in used
                     if u not in onto_terms and u not in sample_individuals and not _is_builtin(u))
    res["unknown_terms"] = unknown
    if unknown:
        res["error"] = "Uses terms the ontology does not declare: " + ", ".join(unknown)
        return res
    if not any(u in onto_terms and not _is_builtin(u) for u in used):
        res["error"] = "The query uses no class or property of the ontology."
        return res

    # eine Zaehlung ohne Treffer liefert eine Zeile mit 0 - das ist kein Ergebnis auf den Beispieldaten (F3)
    zero = lambda v: isinstance(v, Literal) and isinstance(v.toPython(), (int, float, Decimal)) and v.toPython() == 0
    try:
        # rdflib wertet beim Lesen der Zeilen aus: auch ein Fehler dort trifft nur diese Frage, nicht den ganzen
        # Test (VA 5c, zweite Bruecke: "What do I do with this CompValue?" brach alle Hold-out-Laeufe ab)
        result = data_g.query(q)
        ask = bool(result.askAnswer) if q.algebra.name == "AskQuery" else None
        rows = None if ask is not None else [r for r in result if any(v is not None and not zero(v) for v in r)]
    except Exception as ex:
        res["error"] = f"Query failed: {type(ex).__name__}: {str(ex)[:300]}"
        return res
    if ask is not None:
        res["row_count"] = int(ask)
        res["rows"] = [{"answer": str(ask).lower()}]
        res["result_ok"] = ask
        if not res["result_ok"]:
            res["error"] = "ASK returned false on the sample data."
        return res

    res["row_count"] = len(rows)
    res["rows"] = [{str(k): _short(v, data_g) for k, v in r.asdict().items()} for r in rows[:_MAX_ROWS]]
    if not rows:
        res["error"] = "No result on the sample data."
    elif all(v in schema_terms for r in rows for v in r if v is not None) and _answers_from_schema(q, onto_g, schema_terms):
        res["error"] = "The result consists only of ontology terms — it answers from the schema, not the data."
    else:
        res["result_ok"] = True
    return res

def _type_conflicts(sample, onto_g, known=None):
    """Beispieltripel, deren Subjekt oder Objekt nach seinen angegebenen Typen nicht in Domain oder Range der Property
    liegt (Wein-Lauf 4: die Rebsorte Cabernet Sauvignon als Subjekt von goesWellWith, Domain Wein). Ohne
    Disjunktheit merkt das der Reasoner nicht - er folgert einfach den zweiten Typ, und die Abfrage 'besteht' auf einer
    Verwechslung. Solche Tripel werden verworfen und gemeldet; ein Individuum ohne angegebenen Typ wird nicht geprueft.
    known: weitere Beispieldaten, deren Typen mitzaehlen (die behaltenen aus dem letzten Test)."""
    from rdflib import Graph, Literal, URIRef
    from rdflib.namespace import RDF, RDFS
    supers = {}
    def ancestors(c):
        if c not in supers:
            seen, todo = {c}, [c]
            while todo:
                for p in onto_g.objects(todo.pop(), RDFS.subClassOf):
                    if isinstance(p, URIRef) and p not in seen:
                        seen.add(p)
                        todo.append(p)
            supers[c] = seen
        return supers[c]
    types = {}
    for g in (onto_g, known if known is not None else Graph(), sample):
        for s, t in g.subject_objects(RDF.type):
            if isinstance(t, URIRef) and not _is_builtin(t):
                types.setdefault(s, set()).add(t)
    def misfit(node, cls):
        return isinstance(cls, URIRef) and not _is_builtin(cls) and types.get(node) and \
            not any(cls in ancestors(t) for t in types[node])
    valid, issues = Graph(), []
    for s, p, o in sample:
        bad = ""
        if p != RDF.type:
            d = next((d for d in onto_g.objects(p, RDFS.domain) if misfit(s, d)), None)
            r = None if d or isinstance(o, Literal) else next((r for r in onto_g.objects(p, RDFS.range) if misfit(o, r)), None)
            if d:
                bad = f"{_short(s, onto_g)} is not a {_short(d, onto_g)}, the domain of {_short(p, onto_g)}"
            elif r:
                bad = f"{_short(o, onto_g)} is not a {_short(r, onto_g)}, the range of {_short(p, onto_g)}"
        if bad:
            issues.append(bad + " - triple dropped")
        else:
            valid.add((s, p, o))
    return valid, issues

def _entail(sample, onto_g):
    """Was aus den Beispieldaten nach der Ontologie folgt: Oberproperties, Inverse, symmetrische und transitive
    Properties, Oberklassen (DECISIONS 71). Eine Abfrage auf eine allgemeine Relation soll Daten finden, die mit einer
    Subproperty formuliert sind - so wie ein Reasoner. Bewusst ohne Domain/Range-Typisierung: die erzeugt Typen, die
    niemand angegeben hat, und wuerde Abfragen 'bestehen' lassen, die nur auf Folgerungen aus Fehlern beruhen."""
    from rdflib import URIRef
    from rdflib.namespace import RDF, RDFS, OWL
    sup_p, inv, sup_c = {}, {}, {}
    for p, q in onto_g.subject_objects(RDFS.subPropertyOf):
        sup_p.setdefault(p, set()).add(q)
    for p, q in onto_g.subject_objects(OWL.inverseOf):
        inv.setdefault(p, set()).add(q)
        inv.setdefault(q, set()).add(p)
    for c, d in onto_g.subject_objects(RDFS.subClassOf):
        if isinstance(d, URIRef):
            sup_c.setdefault(c, set()).add(d)
    sym = set(onto_g.subjects(RDF.type, OWL.SymmetricProperty))
    trans = set(onto_g.subjects(RDF.type, OWL.TransitiveProperty))
    facts = set(sample)
    for _ in range(12):
        new = set()
        for s, p, o in facts:
            if p == RDF.type:
                new |= {(s, RDF.type, d) for d in sup_c.get(o, ())}
                continue
            new |= {(s, q, o) for q in sup_p.get(p, ())}
            if isinstance(o, URIRef):
                new |= {(o, q, s) for q in inv.get(p, ())}
                if p in sym:
                    new.add((o, p, s))
        for p in trans:
            pairs = [(s, o) for s, q, o in facts if q == p]
            succ = {}
            for s, o in pairs:
                succ.setdefault(s, set()).add(o)
            new |= {(s, p, x) for s, o in pairs for x in succ.get(o, ())}
        new -= facts
        if not new:
            break
        facts |= new
    return facts - set(sample)

def translate_cq_report(report, merged, namespace):
    """Uebersetzt Beispieldaten und Abfragen eines CQ-Ergebnisses durch zusammengefuehrte Properties (p -> c; '^c':
    p war die Inverse von c, das Tripel wird umgedreht bzw. die Abfrage nutzt den Pfad ^:c). Dann muessen nach einer
    Konsolidierung nur Abfragen neu geschrieben werden, die wirklich nicht mehr gehen."""
    if not report or not merged:
        return report, 0
    from rdflib import Graph, URIRef
    def target(name):
        flip, seen = False, set()
        while name in merged and name not in seen:
            seen.add(name)
            name = merged[name]
            if name.startswith("^"):
                flip, name = not flip, name[1:]
        return name, flip
    out, changed = copy.deepcopy(report), 0
    if out.get("sample_data") and namespace:
        g, g2 = Graph(), Graph()
        try:   # wie beim Testen: der leere Praefix ist der Ontologie-Namespace, auch wenn die Daten ihn nicht deklarieren
            g.parse(data=f"@prefix : <{namespace}> .\n" + out["sample_data"], format="turtle")
        except Exception:
            return report, 0      # unlesbar: lieber unveraendert lassen als die Daten zu verlieren
        for pfx, ns in g.namespaces():
            g2.bind(pfx, ns)
        for s, p, o in g:
            local = str(p)[len(namespace):] if str(p).startswith(namespace) else None
            if local in merged:
                new, flip = target(local)
                changed += 1
                if flip and isinstance(o, URIRef):
                    g2.add((o, URIRef(namespace + new), s))
                    continue
                if not flip:
                    g2.add((s, URIRef(namespace + new), o))
                    continue
            g2.add((s, p, o))
        out["sample_data"] = g2.serialize(format="turtle")
    names = sorted(merged, key=len, reverse=True)
    if names:
        pat = re.compile(r"(?<![\w:#/-])(:|<" + re.escape(namespace or "\0") + r")(" + "|".join(map(re.escape, names)) +
                         r")(>?)(?![\w-])")
        def sub(m):
            new, flip = target(m.group(2))
            ref = (":" + new) if m.group(1) == ":" else "<" + namespace + new + ">"
            return ("^" if flip else "") + ref
        for t in out.get("tests") or []:
            if t.get("sparql"):
                q2 = pat.sub(sub, t["sparql"])
                if q2 != t["sparql"]:
                    t["sparql"], changed = q2, changed + 1
    return out, changed

def _parse_sample(text, prefixes, onto_terms, issues, what="Sample data", onto_individuals=frozenset()):
    from rdflib import Graph
    g = Graph()
    try:
        g.parse(data=prefixes + "\n" + (text or ""), format="turtle")
    except Exception as ex:
        issues.append(f"{what} is not valid Turtle and was ignored: {ex}")
    valid, bad = _split_sample_data(g, onto_terms, onto_individuals)
    issues += bad
    return valid

def test_competency_questions(turtle, cqs, llm_config, context="", step="CQ tests", previous=None):
    """previous: das letzte Ergebnis fuer (teilweise) dieselben Fragen. Damit bleibt die Messung zwischen Iterationen
    vergleichbar: die alten Beispieldaten bleiben (soweit sie noch zur Ontologie passen) und werden nur ergaenzt, und
    eine Abfrage, die vorher bestand und es auf der neuen Ontologie noch tut, wird nicht neu geschrieben. Sonst
    wuerfelt jede Iteration Daten und Abfragen neu, und eine Frage kann ohne Aenderung der Ontologie 'durchfallen'."""
    from rdflib import Graph
    from rdflib.namespace import RDF
    onto_g = Graph(bind_namespaces="core")   # sonst wird ein eigenes geo: zu geo1: (F2)
    onto_g.parse(data=turtle, format="turtle")
    onto_terms = set(onto_g.subjects()) | set(onto_g.predicates()) | set(onto_g.objects())
    prefixes = "\n".join(f"@prefix {p}: <{ns}> ." for p, ns in _test_namespaces(onto_g).items())
    # Schema-Terme: alles aus der Ontologie ausser deren Individuen (z.B. Aufzaehlungswerte sind legitime Antworten)
    onto_individuals = {s for s, o in onto_g.subject_objects(RDF.type) if not _is_builtin(o)}
    schema_terms = onto_terms - onto_individuals

    def data_graph(sample):
        g = Graph()
        for prefix, ns in onto_g.namespaces():
            g.bind(prefix, ns)
        for t in onto_g:
            g.add(t)
        for t in sample:
            g.add(t)
        for t in _entail(sample, onto_g):
            g.add(t)
        return g

    sample_issues = []
    previous = previous or {}
    dropped = []
    kept_sample = _parse_sample(previous["sample_data"], prefixes, onto_terms, dropped, "Previous sample data",
                                onto_individuals) \
        if previous.get("sample_data") else Graph()
    kept_sample, conflicts = _type_conflicts(kept_sample, onto_g)
    dropped += conflicts
    for prefix, ns in onto_g.namespaces():
        kept_sample.bind(prefix, ns)
    if dropped:
        sample_issues.append(f"{len(dropped)} triples of the previous sample data no longer fit the ontology and were dropped.")

    # 1. Bestandene Abfragen der letzten Runde auf den alten Daten erneut ausfuehren
    entries = {}
    old_passed = {_norm(t.get("question")): t for t in previous.get("tests") or []
                  if t.get("status") == "passed" and t.get("sparql")}
    if old_passed:
        old_data = data_graph(kept_sample)
        old_individuals = _data_individuals(kept_sample)
        for i, question in enumerate(cqs, 1):
            t = old_passed.get(_norm(question))
            if not t:
                continue
            res = _run_cq_test(t["sparql"], onto_g, old_data, onto_terms, schema_terms, old_individuals)
            if res["result_ok"]:
                entries[i] = {"cq": i, "question": question, "sparql": t["sparql"], "expected": t.get("expected") or "",
                              "missing": "", **res, "status": "passed", "reused": True}

    # 2. Nur die uebrigen Fragen gehen an das Modell, mit den vorhandenen Daten als Ausgangspunkt
    todo = [(i, q) for i, q in enumerate(cqs, 1) if i not in entries]
    sample_valid = kept_sample
    if todo:
        existing = kept_sample.serialize(format="turtle") if len(kept_sample) else ""
        with usage_step(step):
            spec = _run_llm_json(llm_config, build_cq_test_prompt(turtle, [q for _, q in todo], context, existing))
        added = _parse_sample(spec.get("sample_data"), prefixes, onto_terms, sample_issues,
                              onto_individuals=onto_individuals)
        added, conflicts = _type_conflicts(added, onto_g, kept_sample)
        sample_issues += conflicts
        sample_valid = Graph()
        for t in kept_sample:
            sample_valid.add(t)
        for t in added:
            sample_valid.add(t)
        for prefix, ns in onto_g.namespaces():
            sample_valid.bind(prefix, ns)
        data_g = data_graph(sample_valid)
        sample_individuals = _data_individuals(sample_valid)
        by_index = {}
        for t in spec.get("tests", []):
            try:
                by_index.setdefault(int(t.get("cq")), t)
            except (TypeError, ValueError):
                pass
        def judge(entry):           # data_g und sample_individuals: die jeweils aktuellen (nach einer Korrektur neu)
            if not entry["sparql"]:
                entry.update(status="not_answerable", rows=[], row_count=0,
                             error=entry["missing"] or "No query could be written for this CQ.")
                return
            entry.update(_run_cq_test(entry["sparql"], onto_g, data_g, onto_terms, schema_terms, sample_individuals))
            entry["status"] = "passed" if entry["result_ok"] else "failed"
            # die Abfrage laeuft, beantwortet aber nach Angabe ihres Autors nur einen Teil der Frage (Wein-Lauf 4:
            # "die beste Wahl" als blosse Liste) - das kann eine Bewertung nur senken, nie heben
            if entry["result_ok"] and entry["leaves_out"]:
                entry.update(status="partial", error="Answers only part of the question: " + entry["leaves_out"])

        for k, (i, question) in enumerate(todo, 1):
            t = by_index.get(k, {})
            entry = {"cq": i, "question": question, "sparql": t.get("sparql") or "",
                     "expected": t.get("expected") or "", "missing": t.get("missing") or "",
                     "leaves_out": _stated(t.get("leaves_out"))}
            judge(entry)
            entries[i] = entry
        # 3. Abfragen ohne Ergebnis auf den eigenen Beispieldaten: eine Korrekturrunde (DECISIONS 109)
        empty = [entries[i] for i, _ in todo if entries[i]["status"] == "failed" and entries[i]["error"] in NO_RESULT]
        if empty:
            fix = correct_empty_queries(empty, sample_valid, onto_g, sample_issues, llm_config, step)
            if isinstance(fix, str):
                sample_issues.append(fix)
            else:
                snippets, queries = fix
                for k, text in enumerate(snippets, 1):   # einzeln: ungueltiges Turtle in einem verwirft nicht alle
                    extra = _parse_sample(text, prefixes, onto_terms, sample_issues,
                                          f"Sample data of correction {k}", onto_individuals)
                    extra, conflicts = _type_conflicts(extra, onto_g, sample_valid)
                    sample_issues += conflicts
                    for t in extra:
                        sample_valid.add(t)
                for e in empty:
                    e["first_error"] = e["error"]
                    if e["cq"] in queries:
                        e.update(queries[e["cq"]])
                data_g = data_graph(sample_valid)
                sample_individuals = _data_individuals(sample_valid)
                for i, _ in todo:            # alle neu: die ergaenzten Daten gelten fuer jede Abfrage
                    judge(entries[i])
        problem = check_partial_answers([entries[i] for i, _ in todo], llm_config, step)
        if problem:
            sample_issues.append(problem)
    tests = [entries[i] for i in range(1, len(cqs) + 1)]
    return {"tests": tests, "passed": sum(t["status"] == "passed" for t in tests), "total": len(tests),
            "reused": sum(1 for t in tests if t.get("reused")),
            "sample_data": sample_valid.serialize(format="turtle") if len(sample_valid) else "",
            "sample_triples": len(sample_valid), "sample_issues": sample_issues}
