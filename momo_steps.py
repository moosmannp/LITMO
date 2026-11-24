"""Prompts der MOMo-Schritte vor der Generierung: Kontextentwurf, CQs, Key Notions, Patterns."""

import re

from project import (_catalog_listing, _context, _cq_text, _ctx, decided_definitions, MAX_CQS, MOMO_METHOD, _norm,
                     PATTERN_CATALOG, pattern_template_text, _PATTERNS_BY_ID)
from corpus import data_documents_text, inventory_overview

CQ_SYS = (MOMO_METHOD + "\nMOMo Step 2 — gather competency questions. Competency questions (CQs) are "
          "example queries of interest in natural language that the populated knowledge graph must be able "
          "to answer. They refine the use case and sanity-check whether the data sources are adequate. "
          "Write them as a potential future USER would ask them, not as a modeler. Aim for sufficiently "
          "DIFFERENT questions covering distinct aspects — not variations of one another.\n"
          'Answer ONLY as JSON: {"competency_questions":[{"question":"...","rationale":"why this CQ matters / which aspect it probes"}]}')

def build_cq_prompt(use_case, data_sources, data_preview, existing=None, context="", literature=""):
    have = "\n".join("- " + _cq_text(c) for c in existing or [])
    wanted = MAX_CQS - len(existing or [])
    lit = ("\n\n**Literature corpus (concept inventory)** - prefer questions that the sources support, adapted to "
           "the use case, and cover the main themes rather than one corner of the domain:\n" + literature) if literature else ""
    return [
        {"role": "system", "content": CQ_SYS},
        {"role": "user", "content": "**Use case / problem description:**\n" + (use_case or "(none)") +
         "\n\n**Data sources:**\n" + (data_sources or "(none)") +
         "\n\n**Data preview:**\n" + (data_preview or "(none)") + _ctx(context) + lit +
         ("\n\n**Competency questions the team already has (do not repeat or rephrase them):**\n" + have
          if have else "") +
         "\n\nPropose at most " + str(wanted) + " sufficiently different competency questions."}
    ]

MAX_KEY_NOTIONS = 7

NOTION_SYS = (MOMO_METHOD + "\nMOMo Step 3 — identify key notions for the domain. A key notion is a CENTRAL concept "
              "that is the ORIGIN POINT of a whole subset of the ontology: it becomes a MODULE, and the module's other "
              "classes, properties and attributes are modeled around it later (Step 5). Key notions are therefore FEW — "
              "typically 3 to 6 for a use case, never more than " + str(MAX_KEY_NOTIONS) + ". "
              "Do NOT list every noun that recurs in the competency questions. Things that are merely attributes, values, "
              "parts, types or participants of a key notion belong INSIDE that notion's module and are not key notions "
              "themselves (e.g. for recipes: Recipe is a key notion, but Ingredient amount, cooking time, cuisine label "
              "or step number are parts of the Recipe module). Ask of each candidate: would a team sit down and model "
              "this as its own module with its own schema diagram? If not, fold it into another notion. "
              "Also surface IMPLICIT or 'hidden' concepts that a human modeler would recognize but that are not "
              "literally named — e.g. technically 'enslavement' is a momentary event, but 'being enslaved' is a STATE "
              "with temporal duration, and that state is likely the real key notion. "
              "Keep provenance: for every notion record which CQs motivate it, so requirements trace "
              "use case -> CQs -> key notions -> modules and feature creep is avoided. "
              "The team may already have defined some key notions: never repeat or rename those — only propose "
              "notions that are genuinely MISSING. Returning an empty list is fine if the team's notions already "
              "cover the use case.\n"
              'Answer ONLY as JSON: {"key_notions":[{"name":"CamelCaseName","description":"what this module covers",'
              '"hidden":true|false,"from_cqs":["the CQ text or index that motivates this notion"]}]}')

def build_notion_prompt(use_case, data_sources, cqs, existing=None, context="", literature=""):
    cq_text = "\n".join("- " + (c.get("question", "") if isinstance(c, dict) else str(c)) for c in cqs) or "(none)"
    existing_text = "\n".join(
        "- " + n.get("name", "") + (": " + n.get("description", "") if n.get("description") else "")
        for n in (existing or []) if isinstance(n, dict) and n.get("name")) or "(none yet)"
    return [
        {"role": "system", "content": NOTION_SYS},
        {"role": "user", "content": "**Use case:**\n" + (use_case or "(none)") +
         "\n\n**Data sources:**\n" + (data_sources or "(none)") +
         "\n\n**Competency questions:**\n" + cq_text +
         "\n\n**Key notions the team has already defined:**\n" + existing_text + _ctx(context) +
         ("\n\n**Literature corpus (concept inventory)** - its themes are candidate modules and its central "
          "concepts candidate key notions; still keep key notions few and central:\n" + literature if literature else "") +
         "\n\nPropose only the missing key notions, if any. Mark implicit/hidden concepts with \"hidden\": true."}
    ]

PATTERN_SYS = (MOMO_METHOD + "\nMOMo Step 4 - identify existing ontology design patterns (ODPs) to be used. Decide for "
               "EACH key notion whether a pattern from the curated library below (the ODPA Patterns Repository, "
               "https://github.com/odpa/patterns-repository) really fits as the TEMPLATE for that module. "
               "Returning null is the EXPECTED answer when nothing fits well - a module built from scratch is better "
               "than one forced into an unsuitable pattern.\n"
               "How to judge the fit:\n"
               "- Compare the pattern's classes, properties and competency questions with the notion, the use case and "
               "the project's competency questions. Never choose a pattern only because its name sounds similar.\n"
               "- \"strong\": the pattern's core structure matches the notion; it needs only small adaptations.\n"
               "- \"partial\": only some parts are usable, or it needs substantial changes.\n"
               "- Otherwise return \"pattern\": null and \"fit\": \"none\".\n"
               "- For each notion you get CANDIDATES with their full structure. Prefer them; you may pick another pattern "
               "from the library only by its short description, and then rate it at most \"partial\".\n"
               "- A notion may have several reasonable choices (a Recipe could be a Document, a Plan or a Process) - use "
               "the use case and CQs to pick the best overall fit, and list the others as alternatives.\n"
               "You MUST only use pattern IDs exactly as listed; never invent patterns.\n"
               'Answer ONLY as JSON: {"patterns":[{"notion":"KeyNotionName","pattern":"PatternID or null",'
               '"fit":"strong|partial|none","rationale":"why it fits or why nothing fits",'
               '"keep":"which classes/properties of the pattern the module keeps","change":"what to drop, rename or add",'
               '"alternatives":["OtherPatternID"]}]}\n\n'
               "**Pattern library (ID: intent):**\n" + _catalog_listing())

# Vorauswahl von Kandidaten je Key Notion: Wortueberschneidung mit Name, Klassen, Zweck, Domaenen und den
# Competency Questions des Patterns. So sieht das Modell die echte Struktur der aussichtsreichsten Patterns,
# statt nur nach dem Namen zu waehlen.
_PATTERN_STOP = set("""a an the of and or to in on for by with as is are be that this which what who whom whose
when where how does do did has have had its it their they them from at into about than then there these those
can may will would should could not no all any some each one two per via thing things
pattern patterns represent representing model modeling modelling used use using""".split())

def _pattern_tokens(text) -> list:
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(text or ""))
    out = []
    for t in re.split(r"[^A-Za-z0-9]+", text.lower()):
        if len(t) < 3 or t in _PATTERN_STOP:
            continue
        out.append(t[:-1] if len(t) > 4 and t.endswith("s") and not t.endswith("ss") else t)
    return out

def _pattern_index():
    from collections import Counter
    index = {}
    for pat in PATTERN_CATALOG["patterns"]:
        w = Counter()
        for t in _pattern_tokens(pat["id"] + " " + pat.get("name", "")):
            w[t] += 3
        for c in pat.get("classes", []):
            for t in _pattern_tokens(c.get("name")):
                w[t] += 2
        for t in _pattern_tokens(pat.get("intent")):
            w[t] += 2
        for prop in pat.get("object_properties", []) + pat.get("datatype_properties", []):
            for t in _pattern_tokens(prop.get("name")):
                w[t] += 1
        for t in _pattern_tokens((pat.get("domains") or "") + " " + (pat.get("competency_questions") or "")):
            w[t] += 1
        index[pat["id"]] = w
    return index

_PATTERN_INDEX = _pattern_index()
PATTERN_CANDIDATES = 6

def candidate_patterns(notion: dict, cq_texts: list, k: int = PATTERN_CANDIDATES) -> list:
    from collections import Counter
    q = Counter()
    for t in _pattern_tokens(notion.get("name")):
        q[t] += 3
    for t in _pattern_tokens(notion.get("description")):
        q[t] += 2
    related = [c for c in cq_texts if any(_norm(r) and _norm(r) in _norm(c) for r in notion.get("from_cqs") or [])]
    for t in _pattern_tokens(" ".join(related)):
        q[t] += 1
    name_tokens = set(_pattern_tokens(notion.get("name")))
    scored = []
    for pid, w in _PATTERN_INDEX.items():
        score = sum(min(qw, 3) * min(w[t], 4) for t, qw in q.items() if t in w)
        if not score:
            continue
        # Patterns mit sehr viel Text treffen zufaellig mehr Woerter - leicht nach Umfang normalisieren
        score /= (1 + len(w) / 60) ** 0.5
        # Notion-Name steckt im Pattern-Namen (Agent -> AgentRole): starkes Signal
        if name_tokens and name_tokens <= set(_pattern_tokens(pid)):
            score *= 2
        scored.append((score, pid))
    scored.sort(reverse=True)
    return [pid for _, pid in scored[:k]]

def pattern_candidate_text(pat) -> str:
    """Struktur eines Kandidaten fuer den Prompt, inklusive der Competency Questions des Patterns."""
    text = "- " + pat["id"] + "\n" + pattern_template_text(pat)
    if pat.get("domains"):
        text += "\n    domains: " + str(pat["domains"])[:150]
    if pat.get("competency_questions"):
        text += "\n    pattern CQs: " + str(pat["competency_questions"])[:300]
    return text[:1200]

def build_pattern_prompt(use_case, notions, cqs, context=""):
    notions = [n if isinstance(n, dict) else {"name": str(n)} for n in notions]
    cq_list = [(c.get("question", "") if isinstance(c, dict) else str(c)) for c in cqs]
    cq_text = "\n".join("- " + c for c in cq_list) or "(none)"
    shown, notion_lines, cand_blocks = set(), [], []
    for n in notions:
        cands = candidate_patterns(n, cq_list)
        notion_lines.append("- " + n.get("name", "") + (": " + n["description"] if n.get("description") else "") +
                            "\n  candidates: " + (", ".join(cands) if cands else "(no close candidates in the library)"))
        for pid in cands:
            if pid not in shown and _PATTERNS_BY_ID.get(pid):
                shown.add(pid)
                cand_blocks.append(pattern_candidate_text(_PATTERNS_BY_ID[pid]))
    return [
        {"role": "system", "content": PATTERN_SYS},
        {"role": "user", "content": "**Use case:**\n" + (use_case or "(none)") +
         "\n\n**Competency questions:**\n" + cq_text +
         "\n\n**Key notions (each becomes a module) with pre-selected candidate patterns:**\n" +
         ("\n".join(notion_lines) or "(none)") +
         "\n\n**Structure of the candidate patterns:**\n" + ("\n".join(cand_blocks) or "(none)") + _ctx(context) +
         "\n\nDecide for each key notion whether a pattern really fits. null is the expected answer when nothing "
         "fits well. Rate each choice as strong or partial."}
    ]

MAX_CONTEXT_QUESTIONS = 8

CONTEXT_SECTIONS = ("## Purpose & intended use\n## In scope / out of scope\n## Glossary\n## Domain rules\n"
                    "## Data sources\n## Reuse\n## Decisions made")

CONTEXT_SYS = (MOMO_METHOD + "\nYou prepare the PROJECT CONTEXT document of an ontology project. Every later step "
               "(competency questions, key notions, design patterns, generation, quality fixes) receives this document, "
               "so it must state the team's knowledge and decisions precisely and briefly.\n"
               "Write Markdown with exactly these sections, in this order:\n" + CONTEXT_SECTIONS + "\n"
               "Section contents: Purpose = what the ontology is for and how it will be used (knowledge graph, data "
               "integration, reasoning ...). Scope = two bullet lists 'In scope' and 'Out of scope'. Glossary = one bullet "
               "per central term: **Term** - definition; synonyms; not to be confused with. Domain rules = one sentence "
               "per rule (cardinalities, what is a class and what is an individual or a value). Data sources = per source "
               "its fields with type, unit and value range or enumeration, plus 1-2 example records. Reuse = vocabularies "
               "or terms to reuse directly, to align with only, and not to use. Decisions made = 'decision - reason'.\n"
               "Rules:\n"
               "1. Use only what the inputs state or clearly imply. Append ' [confirm]' to every item you INFERRED rather "
               "than read explicitly. Never present a guess as a fact.\n"
               "2. If nothing is known for a section, write '- (not yet known)'.\n"
               "3. Compact bullet points; no prose paragraphs; do not explain the MOMo method.\n"
               "4. Leave out conventions (namespace, prefix, label languages, license, OWL profile) - a form covers them.\n"
               "5. If a current document is given, keep every item WITHOUT [confirm] word for word (the team wrote or "
               "confirmed it) and only improve or extend the rest.\n"
               "Then ask the team at most " + str(MAX_CONTEXT_QUESTIONS) + " QUESTIONS - only about gaps or ambiguities "
               "that would change the model (scope boundaries, class vs. individual, cardinalities, units, which terms to "
               "reuse). Each question offers 2-4 short answer options and marks the one you recommend. Never ask what the "
               "inputs already answer, and never ask about conventions.\n"
               'Answer ONLY as JSON: {"markdown":"the document","questions":[{"id":"q1","section":"Glossary",'
               '"question":"...","options":["...","..."],"recommended":0}]}')

CONTEXT_ANSWER_SYS = (MOMO_METHOD + "\nYou maintain the PROJECT CONTEXT document of an ontology project. The team "
                      "answered questions about it. Update the document:\n"
                      "- Put the content of each answer into the section where it belongs, phrased as a fact or rule.\n"
                      "- Remove [confirm] from items an answer confirms; correct or delete items an answer contradicts.\n"
                      "- Record answers that settle a modeling choice under '## Decisions made' as 'decision - reason' "
                      "(use the team's answer as the reason if none is given).\n"
                      "- Keep everything else unchanged, including the section order and the team's own wording.\n"
                      "If an answer opens an important new ambiguity, ask up to 3 follow-up questions in the same format; "
                      "otherwise return an empty list.\n"
                      'Answer ONLY as JSON: {"markdown":"the updated document","questions":[{"id":"q1","section":"...",'
                      '"question":"...","options":["...","..."],"recommended":0}]}')

def build_context_draft_prompt(session, extra_requirements=""):
    momo = session.get("momo") or {}
    ctx = _context(session)
    parts = ["**Use case:**\n" + (momo.get("use_case") or "(none)"),
             "**Data sources (as described by the team):**\n" + (momo.get("data_sources") or "(none)")]
    if extra_requirements.strip():
        parts.append("**Special requirements:**\n" + extra_requirements.strip())
    parts.append("**Uploaded data (table profiles, RDF summaries and excerpts):**\n" + (session.get("data_preview") or "(none)"))
    docs = data_documents_text(session)
    if docs:
        parts.append("**Full text of the uploaded documents - read them completely; take over what matters for the "
                     "glossary, domain rules, scope and data sources:**\n" + docs)
    literature = inventory_overview(session, max_central=40, max_conflicts=0)
    if literature:
        decided = "\n".join(f"- {concept}: " + "; ".join(f"{p['name']}: {p['definition']}" for p in d["parts"])
                            for concept, d in decided_definitions(session))
        parts.append("**Concept inventory of the literature corpus (step 3) - the ontology is built from it.** Use it "
                     "for the Glossary (the central concepts with their definitions - not all of them), for the scope "
                     "(the themes) and for Reuse (the existing ontologies). Concepts marked as CONFLICTING are decided "
                     "by the team in a separate list of this step (DECISIONS 83): do not resolve them in the document "
                     "and do not ask about them. In the Glossary give such a concept the team's decided definition "
                     "where one is listed below, otherwise write 'definition decided separately'.\n" + literature +
                     ("\n\nDecided definitions:\n" + decided if decided else ""))
    if ctx["source_text"]:
        parts.append(f"**Existing context file of the team ({ctx['source_name']}) - take its content over into the "
                     f"document; items stated there are confirmed:**\n" + ctx["source_text"])
    if ctx["markdown"].strip():
        parts.append("**Current document (keep items without [confirm] word for word):**\n" + ctx["markdown"])
    return [{"role": "system", "content": CONTEXT_SYS},
            {"role": "user", "content": "\n\n".join(parts) + "\n\nWrite the project context document and your questions."}]

def build_context_answer_prompt(markdown, answers):
    qa = "\n".join(f"- Q: {a.get('question', '')}\n  A: {a.get('answer', '')}" for a in answers)
    return [{"role": "system", "content": CONTEXT_ANSWER_SYS},
            {"role": "user", "content": "**Current document:**\n" + markdown + "\n\n**The team's answers:**\n" + qa}]

def _clean_questions(questions) -> list:
    out = []
    for i, q in enumerate(questions or []):
        if not isinstance(q, dict) or not str(q.get("question") or "").strip():
            continue
        opts = [str(o) for o in (q.get("options") or []) if str(o).strip()][:4]
        rec = q.get("recommended")
        out.append({"id": f"q{i + 1}", "section": str(q.get("section") or ""), "question": str(q["question"]).strip(),
                    "options": opts, "recommended": rec if isinstance(rec, int) and 0 <= rec < len(opts) else None})
    return out[:MAX_CONTEXT_QUESTIONS]
