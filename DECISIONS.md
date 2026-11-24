# Implementation decisions

A log of the decisions behind the code: what was decided, why, and which alternatives were considered and not
chosen. `DEVELOPMENT.md` describes *what the tool does*; this file explains *why it does it that way*. New
decisions are appended to the end of their area and numbered continuously; a decision that is replaced stays in the
log, marked as superseded, so the reasoning is not lost.

Format: **Decision** · **Why** · **Alternatives not chosen**. Status is "in use" unless stated.

Areas: [A Platform](#a-platform-and-process) · [B LLM calls](#b-llm-calls) ·
[C Quality checks](#c-quality-checks-on-the-generated-ontology) · [D Inputs and project context](#d-inputs-and-project-context) ·
[E MOMo steps](#e-momo-steps) · [F Literature corpus](#f-literature-corpus) ·
[G Generation module by module](#g-generation-module-by-module) · [H Changing the ontology: edit operations](#h-changing-the-ontology-edit-operations) ·
[I Evaluation](#i-evaluation)

---

## A. Platform and process

### 1. One FastAPI file and one HTML file, no build step
**Decision.** `app.py` (backend) and `index.html` (frontend, plain JavaScript) stay single files; only logic that is
pure and testable on its own moves into a separate module (`ontology_edits.py`, see 43).
**Why.** The tool is started with one command and can be read and changed without a toolchain. This was the
existing structure, and a framework migration would have cost more than any benefit for a single-user tool.
**Alternatives.** React/Vue with a bundler (build step, more setup for every contributor); splitting `app.py` into a
package up front (large diff, no functional gain). The files are now large (`app.py` about 3,700 lines); splitting
along the existing sections is the next step if that becomes a problem.

### 2. Sessions are JSON files, saved by one middleware
**Decision.** Every session is `data/sessions/<id>.json` (override: `ODT_SESSION_DIR`). An HTTP middleware writes all
sessions whose content changed after every non-GET `/api/` request. Writes are atomic (temp file, then replace).
Sessions without content are not written, because every page load creates one. The browser only remembers the open
project id in `localStorage` and restores it on load.
**Why.** A server restart used to destroy all work. The user asked for persistence (JSON or SQLite) plus export and
import of the whole project. One middleware saves every endpoint, including future ones, without touching each handler.
**Alternatives.** SQLite: more machinery (schema, migrations) for a handful of single-user projects, and
unreadable in an editor. Saving inside each endpoint: easy to forget in new endpoints. Saving on a timer: loses
the last seconds on a crash. Storing the project in the browser only: not shareable, lost with the browser profile.

### 3. API keys are never stored or exported
**Decision.** Keys come with each request from the browser and are not part of a session, the session file or the
project export. After a restore the user enters the key again; the notice says so.
**Why.** Session files and exports are meant to be shared and archived; a key in them would leak.
**Alternatives.** Encrypted storage on the server (needs a secret to manage); keys in `localStorage` (readable by
any script on the page).

### 4. Project export/import is one JSON file
**Decision.** `*.project.json` holds the whole session (`format: ontology-development-tool/project`). Full texts of
the literature corpus, which live outside the session file (see 32), are embedded in the export (`corpus_texts`).
On import only ids of the expected shape are accepted, because ids become file names.
**Why.** One file is easy to send and archive and survives moving to another machine.
**Alternatives.** A zip with the full texts as files (smaller, but two formats to handle); exporting without full
texts (then paper cards could not be extracted again).

### 5. The server runs in the terminal panel, not as a background task
**Decision.** The app server is started with `run_in_terminal`, not as a background task.
**Why.** Background tasks are stopped after two hours, which killed the server during long sessions; a terminal tab
stays and the user can see the log.
**Alternatives.** Windows service or scheduled task (overkill for development).

### 6. Git: commits to `main`, with an explicit identity, never the local preview config
**Decision.** The user chose "directly to main". There is no global git identity, so commits use
`git -c user.name=… -c user.email=… commit`. `.claude/launch.json` (local preview configuration) is never committed;
`data/` is in `.gitignore` because sessions contain uploaded data.
**Why.** The user's choice; sessions and local configuration must not end up in the repository.
**Alternatives.** Pull requests (offered, declined); configuring a global identity (changes the user's machine).

### 7. The hard-coded RWTH key in `index.html` is left alone and not used by the assistant
**Decision.** It stays as it is (documented as a known limitation in `DEVELOPMENT.md`); tests with real LLMs were not
run, because they would need a key the assistant was not given.
**Why.** Using a key found in a file is not what the user asked for. Removing it changes how the tool is used and is
only needed before the repository is shared.
**Alternatives.** Removing it now (offered, not requested).

### 8. Panel ids are stable; the displayed numbers are not
**Decision.** Panels keep their element ids (`panel1`…`panel8`) when steps are added; the sidebar shows new numbers.
`panel7` (project context) is shown as step 4, `panel8` (literature) as step 3.
**Why.** Saved projects store the current step and completed steps by id; renumbering ids would break them.
**Alternatives.** Renumbering everything with a migration of saved projects (risk for no user benefit). Cost: the id
order no longer matches the display order, which is documented.

### 9. Tests are plain assertion scripts
**Decision.** `tests/test_ontology_edits.py` and `tests/test_edit_flow.py` use plain `assert` and run with
`python tests/<file>.py`. They are written so that pytest could collect them, but pytest is not installed, so only
the direct run is verified. The LLM is replaced by a scripted fake, so no key and no network are needed.
**Why.** The project had no tests; adding a test dependency for a few files was not worth it, and the logic that
broke before (silent failures) is deterministic and testable.
**Alternatives.** pytest as a requirement; testing against real models (cost, non-deterministic, needs keys).
*Superseded by DECISIONS 123:* with about 160 tests the suite runs with pytest, a development-only requirement.

### 52. `start.bat` uses the project's `.venv` and is the recommended way to run the server
**Decision.** `start.bat` switches to its own folder, creates `.venv` if it is missing, installs `requirements.txt`
into it and starts uvicorn with the venv's Python on `127.0.0.1:8000`. If a server is already listening on port 8000,
it only opens the tool in the browser. The file is plain ASCII with CRLF line endings.
**Why.** The server in the Claude app's terminal panel was stopped twice when the panel was reset; a generation that
runs for minutes ("Failed to fetch") is lost that way. A server in its own window survives that. The old script used
the global Python, which has no FastAPI, only worked when started from its folder, and showed umlauts garbled
because the file was UTF-8.
**Alternatives.** Running the server as a Windows service (setup and rights for a development tool); keeping
`python app.py` (that binds to `0.0.0.0` and so exposes the tool, including session data, to the network);
detecting a running server with `netstat` (prints the state in the Windows language, e.g. "ABHÖREN", so the check
failed on this machine; `Get-NetTCPConnection` does not depend on the language).

---

## B. LLM calls

### 10. Anthropic: streaming, a large output budget, truncation detection
**Decision.** Calls stream with `max_tokens` 64,000, and a response cut at the limit raises `LLMTruncatedError` instead
of producing unparsable JSON. Effort is `high` for modeling (`medium` for reading papers, see 34); Haiku does not
get an effort parameter. For the Claude 5 models the server-side fallback is requested, and a `refusal` stop reason
becomes a clear error.
**Why.** The `JSONDecodeError` in generation was a response truncated at 8,192 tokens. The SDK requires streaming
for large budgets (HTTP timeouts). A truncated answer must never look like a valid but incomplete one.
**Alternatives.** Continuing a truncated answer with a second call (fragile for JSON); raising only the limit (the
silent failure would remain).

### 11. OpenAI-compatible providers: try both token-limit parameters
**Decision.** The call tries `max_tokens` first (`max_completion_tokens` first for OpenAI itself) and switches if the
server rejects the parameter. The budget is 32,000 tokens.
**Why.** GPT-5.x and GPT-6 reject `max_tokens`, while KI:connect and Gemini expect it, and KI:connect passes GPT-5.x
requests through unchanged, so the provider name does not tell which parameter works.
**Alternatives.** A table per model (goes stale with every new model); one parameter only (breaks half the providers).

### 12. JSON from models is parsed leniently
**Decision.** `parse_llm_json` parses with `strict=False` (models write real line breaks inside strings) and, if that
fails, retries after removing `//` and `/* */` comments and trailing commas outside strings. The text around a
failure is logged.
**Why.** Both errors occurred in practice ("Invalid control character", a JSON answer with comments); the meaning was
always unambiguous.
**Alternatives.** Retrying the call (costs tokens and may fail the same way); a stricter prompt alone (does not
prevent it).

### 13. Token usage is tracked per request with context variables
**Decision.** Every LLM call is logged with a step label ("Generation", "Paper card", "Module: Data" …) in a context
variable; the response carries the log. Providers that report no usage count as "unknown" and the totals say so. On an
error the tokens already spent are appended to the message. Threads for parallel calls run in a copy of the context.
**Why.** The user asked for the token usage of generation; a failed run also costs tokens.
**Alternatives.** Estimating tokens from text length (inaccurate); a global counter (wrong with parallel requests).

### 14. Model lists are static, except RWTHgpt
**Decision.** The model choices for Anthropic, OpenAI and Gemini are lists in `index.html`, updated on request. For
RWTHgpt the list comes from the screenshot the user supplied; `/api/models` can also read the deployment names from
KI:connect.
**Why.** There is no reliable cross-provider model listing without keys; the user knows which models they can use.
**Alternatives.** Fetching lists from every provider (needs a key before the first choice); free text only.

### 15. A Pro subscription cannot be used for API calls
**Decision.** The tool uses API keys only.
**Why.** The user asked; the API and the chat subscription are billed separately. Errors about the workspace or the
credit balance are account issues, not bugs, and are explained as such.
**Alternatives.** None available.

---

## C. Quality checks on the generated ontology

### 16. Competency questions are tests run by rdflib, not graded by the model
**Decision.** After generation and every feedback round the model writes one SPARQL query per competency question
plus a small set of sample individuals. rdflib decides: a question counts as covered only if its query parses, uses
only terms the ontology declares, and returns a result that does not consist of schema terms alone. Sample triples
with undeclared terms are dropped; missing prefixes get fallback declarations.
**Why.** The earlier `cq_coverage` field let the model grade its own work, which is not evidence. The user asked for
verification against the ontology plus sample individuals.
**Alternatives.** The model reporting coverage (self-grading); a real triple store with reasoning (heavy for a
check that only needs "does the vocabulary suffice"); checking only that the query parses (says nothing about
whether the ontology can answer).

### 17. At most 10 competency questions
**Decision.** Suggestions are capped at 10 and deduplicated against the team's own.
**Why.** MOMo says 10–12 sufficiently different questions are enough; more are variations of each other and make the
tests slow and expensive. The user asked for the limit.
**Alternatives.** No limit; 12 (MOMo's upper end).

### 18. OOPS! pitfalls: avoid them in the prompt, fix critical and important ones automatically
**Decision.** The generation prompt lists the OOPS! catalogue pitfalls that the JSON format can express
(`OOPS_GUIDANCE`). After generation the ontology is scanned; critical and important pitfalls are fixed
automatically, minor ones are only reported. A fix that yields invalid Turtle is discarded, and the report is refreshed
after a fix so it shows what remains. The Turtle export declares the license, `owl:inverseOf`, reused external
classes and the OPLa terms, so those pitfalls do not recur.
**Why.** The user asked for both. The scanner had never reported a pitfall (see `DEVELOPMENT.md` §5), so everything
that follows depends on its output being read correctly.
**Alternatives.** Fixing only critical pitfalls (the previous behaviour); fixing minor ones too (mostly style, and
each fix risks new changes). Accepted trade-off: fixing P10 and P11 gives every property a global domain and range,
which MOMo would avoid in favour of scoped axioms.

### 19. Fixes are accepted only if the result is valid Turtle
**Decision.** Every ontology is serialized and parsed by rdflib before and after a fix; invalid results are discarded.
**Why.** A "correction" that breaks the file is worse than the original.
**Alternatives.** Trusting the model's JSON.

---

## D. Inputs and project context

### 20. Step-2 uploads are analyzed by type, not cut to a preview
**Decision.** Tables get a column profile over all rows (type, empty share, range or frequent values, three example
rows; up to 200,000 rows, all sheets of a workbook). RDF gets a summary of declared classes, properties, instance
counts, predicates and used namespaces. Text and PDF are read in full for the context draft (up to 120,000
characters per file, 300,000 in total) and contribute only a 4,000-character excerpt to later prompts. Where text is
cut, the cut is marked.
**Why.** The old preview silently cut every input, and the user asked why. A profile over all rows says more than a few
rows, and later prompts must not grow with the documents.
**Alternatives.** Sending everything to every prompt (cost, limits); chunking and retrieval for step 2 (not needed
once the full text goes through the context draft; for large corpora see 29).

### 21. PDF text only from the visible page area
**Decision.** Text is extracted with a visitor that keeps only text inside the page's crop box, then normalized
(NFKC, control characters removed, hyphenation joined).
**Why.** Some PDFs (found with the VIS4ML paper) contain the whole double page on every page and show a crop, so
plain extraction read everything twice (148,000 instead of 76,000 characters), and the old limit cut it silently.
**Alternatives.** Plain `extract_text` (duplicates); OCR (slow, needed only for scans, which are reported instead).

### 22. The data-preview window in step 2 was removed
**Decision.** Step 2 only lists the files and how each was prepared.
**Why.** The user did not need it; it duplicated what the context draft shows.
**Alternatives.** Keeping it collapsed.

### 23. A project-context step with a document and a conventions form
**Decision.** Step 4 drafts a Markdown document (purpose, scope, glossary, domain rules, data sources, reuse,
decisions) from the use case, the data and an optional context file. Inferred items carry `[confirm]`; the model asks
at most 8 targeted questions with options, and the answers are merged. A form sets namespace, prefix, label
languages, license and OWL profile, and namespace, prefix and license are applied to the output by the server. The
document and conventions go into every later prompt.
**Why.** The user wanted the model to know the project beyond the use case, without writing a context file by hand.
Deterministic enforcement is used where a wrong guess would be silent (namespace, license).
**Alternatives.** Only a form (cannot hold glossary and rules); a chat interview (slow, hard to review and edit); a
free-form file only (nothing prompts the team for missing knowledge); trusting the model with the conventions
(it ignored them).

### 24. Labels are stored per language
**Decision.** Classes, properties and individuals carry `labels: {"en": …, "de": …}`; descriptions are in the first
language of the convention. Older `label_de` still reads.
**Why.** Ontologies for German-speaking teams usually need both languages, and the language is a project convention.
**Alternatives.** German only (the original); one field per language (rigid).

### 25. Context for feedback rounds is always sent
**Decision.** The edit prompt always contains the project context (see 46). *Superseded:* earlier, the context was
appended to a feedback round only when it had changed since the last generation, because the conversation history
already contained it.
**Why.** The conversation history no longer exists (see 47); the context is small.
**Alternatives.** Keeping a "context changed" flag (only useful with a history).

---

## E. MOMo steps

### 26. Pattern suggestions only where a pattern really fits
**Decision.** For each key notion the catalogue is pre-ranked by word overlap (normalized by pattern size, with a
boost when the notion is part of the pattern's name). The model sees the structure of the top 6 candidates, rates the
fit as strong, partial or none, says what to keep and change, and `null` is the expected answer. Only strong fits are
pre-selected; the team selects patterns like standards; keep/change notes go to generation.
**Why.** The user asked whether the tool suggests a pattern for everything. The model used to be forced to pick one,
and "role" being a stop word hid the `AgentRole` pattern.
**Alternatives.** Always suggesting the best pattern (forced bad fits); embeddings for ranking (a dependency and a
model download for 126 patterns); letting the model see only names and intents (judges on names).

### 27. Spanning axioms and naming review are removed from the interface
**Decision.** The step 7 panel (MOMo steps 8–9) is gone from the interface; the endpoints remain in `app.py`.
**Why.** The user asked for it for now; the two steps were not covered well by the tool.
**Alternatives.** Deleting the endpoints (they may return).

### 28. Key notions are the team's; suggestions are optional and capped
**Decision.** Suggestions fill nothing automatically, are accepted one at a time, never repeat the team's notions, and
are capped at 7.
**Why.** MOMo treats key notions as the team's central modeling decision (3–6, rarely more); recurring nouns are not
key notions.
**Alternatives.** Filling the list automatically (the earlier behaviour: too many, too shallow). The cap is revisited
for literature-based ontologies (see "Open points").

---

## F. Literature corpus

### 29. One paper card per paper, merged afterwards
**Decision.** Each paper is read in its own call and condensed into a card (concepts with definition, broader term,
synonyms, page and verbatim quote; relations; taxonomies; candidate questions; vocabularies). The cards are merged
into a concept inventory.
**Why.** About 60 papers (about 5 million characters) fit neither the project context (300,000 characters) nor any
prompt. One call per paper works with every model, can run in parallel, is cacheable, and only new papers cost
anything.
**Alternatives.** A larger context window (not available everywhere, expensive for each later step); embeddings and
retrieval (concepts that no question targets are never found, and conflicts need all definitions together);
a running summary over all papers (order-dependent, loses detail); extracting only titles and abstracts (misses the
definitions).

### 30. Pages and quotes are required, and quotes are checked
**Decision.** PDFs are read with `[page N]` markers. For every concept the model gives a page and a quote of at most 25
words, and the server checks that the quote occurs in the paper's text (`quote_ok`); unverified quotes are shown as
a warning.
**Why.** Definitions drive an ontology, and a model can invent a convincing one. A checkable quote exposes it; pages
make the source traceable.
**Alternatives.** Trusting the definition; asking for page only (no check); fuzzy matching (kept strict apart from
spacing, case and punctuation).

### 31. Extraction runs from the browser, a few papers in parallel
**Decision.** The browser sends one request per paper, three at a time; progress, stop and resume are in the page,
and the server holds no job.
**Why.** The API key stays in the browser (see 3), and the server needs no queue. A stopped run continues with the
papers that still have no card.
**Alternatives.** A server-side background queue (needs the key on the server, state to persist, more failure modes);
one request for everything (timeouts, no progress).
**Consequence.** Restarting the server during a run interrupts it; running requests finish, queued papers wait.

### 32. Full texts are files next to the session, not in its JSON
**Decision.** `data/sessions/<id>/corpus/<doc id>.txt`. The session keeps metadata and cards only.
**Why.** The session JSON is rewritten after every changing request; 5 million characters would be written each time.
**Alternatives.** In the session (slow saves); not storing (cards could not be redone). The project export includes them (4).

### 33. Duplicates are detected by content, and the id comes from the hash
**Decision.** The same bytes are added once. The document id is derived from the hash, so uploading a file again
restores a missing full text (for example after an import).
**Why.** Re-uploading the same 60 papers must not double the cost; the corpus held duplicates in practice.
**Alternatives.** Comparing file names (the same paper is often saved under different names).

### 34. Papers are read with medium effort and up to 200,000 characters each
**Decision.** Extraction uses effort `medium` and reads up to 200,000 characters per paper, marking longer ones.
**Why.** Reading and condensing needs less reasoning than modeling and runs 56 times; 200,000 characters (about 50,000
tokens) cover almost every paper. Three files in the test corpus are longer (one is a book).
**Alternatives.** The same effort as modeling (cost); splitting long papers into several calls (complexity for a rare case).

### 35. The inventory is grouped by rules first, then consolidated by one call
**Decision.** Terms are grouped deterministically by a key that ignores case, hyphens, articles, CamelCase and plural
of the last word, and by stated synonyms; abbreviations never link groups. One model call then merges the remaining
synonyms, finds conflicting definitions, groups concepts into themes and writes consolidated definitions. If that call
fails, the name-based grouping is still shown.
**Why.** Rules are cheap, predictable and explainable; the model is needed only where meaning decides. Linking by
abbreviation would join unrelated terms ("VA" …). Conflicts are the most useful result and exist only in a
global view.
**Alternatives.** Everything by the model in batches (merges across batches are missed); embeddings (a dependency;
similar is not the same).

### 36. The consolidation prompt shows definitions only where conflicts can exist
**Decision.** Concepts from several sources get all their definitions in the prompt, concepts from one source get at most one
short definition (dropped first when the list is too long), within a budget of 200,000 characters.
**Why.** With 1,395 concepts the first version dropped all definitions to fit and then could not find a single
conflict, which was not plausible for 56 papers.
**Alternatives.** Truncating the list (loses concepts); two-stage consolidation (planned, see "Open points").

### 37. Existing ontologies and concept tables become cards without a model
**Decision.** RDF (Turtle, RDF/XML, JSON-LD, N-Triples) is converted directly: classes with label, definition, first
superclass, synonyms and URI; object properties as relations; title, creator, namespace and imports. For CSV and Excel
the server proposes the columns for term, definition, broader term, synonyms and URI from the headers (English and
German), and the team confirms the assignment per sheet. OWL/XML is detected and rejected with a hint. Each source is
limited to 1,500 concepts.
**Why.** Their content is already explicit, so extraction would only add errors and cost. A wrong column assignment
would silently ruin a table, hence the confirmation.
**Alternatives.** Model extraction (cost, errors); guessing columns without confirmation; supporting OWL/XML (needs a
parser rdflib lacks; reading it as RDF/XML yields an empty graph, which is why it is detected explicitly).

### 38. Step 3 takes papers, ontologies and concept tables; step 2 stays for data
**Decision.** Everything that should shape the vocabulary goes to step 3; step 2 is for data the ontology must represent.
**Why.** The user asked where such sources belong. Mixing them with data produced a table profile of a glossary,
which says nothing about its terms.
**Alternatives.** One upload area for everything with automatic routing (unclear which sources are meant as data).

### 39. The inventory feeds the later steps
**Decision.** `inventory_overview()` (themes, central concepts, conflicts, existing ontologies, candidate questions)
goes into the context draft, the competency-question suggestions and the key-notion suggestions. The most consequential
conflicts become questions in the context step; others are recorded with a proposed resolution marked `[confirm]`.
**Why.** Without it, a test showed that generation used none of the 1,395 extracted concepts (49 classes from the
model's general knowledge).
**Alternatives.** Showing the inventory only for reading.

---

## G. Generation module by module

### 40. With an inventory, generation is a plan, then one call per module, then a deterministic merge
**Decision.** One planning call assigns inventory concepts to the modules (one per key notion) as classes with fixed unique
names, and names concepts better modeled as properties or individuals. Then one call per module (four at a time)
receives only that module's concepts with all source definitions, existing-ontology URIs, the relations the sources
state, its design pattern, the competency questions and the class names of the other modules (for domain and
range). The server merges: names are unique, planned classes a module left out are added with the consolidated
definition, referenced but undefined classes become labelled placeholders, and a failed module does not stop the run.
**Why.** One call can neither read hundreds of definitions nor write hundreds of classes (output limit). Modules are
MOMo's unit anyway, and parallel calls are faster. The report states what was planned, produced, added and
failed, so nothing is hidden.
**Alternatives.** One call (the 49-class result); chunking by alphabet or theme (cuts across modules); letting each
module choose its own concepts (overlaps and gaps between modules).
**Consequence.** Classes of a module cannot be checked against another module's output during generation; the
placeholders and the later OOPS!/CQ checks catch the gaps.

### 41. Provenance is exported per class
**Decision.** Classes carry `sources` (exported as `dct:source`, a citation) and `see_also` (`rdfs:seeAlso`, URIs of
matching terms in existing ontologies). Only source ids and URIs that exist in the inventory are accepted from the model.
**Why.** A research ontology should be traceable to its sources, and existing terms are the starting point for
alignment.
**Alternatives.** PROV-O (heavy for a citation per class); `skos:definition` with the source inside the text (not queryable).

---

## H. Changing the ontology: edit operations

### 42. Feedback and fixes return operations, not a new ontology
**Decision.** For feedback rounds, OOPS! fixes, syntax fixes and the SHACL adjustment, the model answers with a list of
operations (add, update, rename and remove for classes, properties, individuals, axioms and modules, plus
`update_ontology`) and a summary. The server applies them to a copy and returns the result.
**Why.** For a literature-based ontology (about 260 classes with two languages and sources) the full ontology is about 39,000
tokens. A rewrite per round exceeded the 32,000-token limit of OpenAI-compatible providers, cost the same again in
output tokens on every call, and could silently drop what the request never touched (the sources and links of every
class). With operations the answer is a few hundred tokens, everything unmentioned stays as it is, and the change list
is exact.
**Alternatives.** Raising the limits (Anthropic only; cost remains); a full rewrite with a "keep all fields" instruction
(unreliable at this size); RFC 6902 JSON Patch (paths are positions in lists, so a model that miscounts changes the
wrong element; names are stable and self-explaining); diffs of the Turtle text (fragile, and the Turtle is generated
from the JSON model anyway).

### 43. The edit logic is its own module, with no dependency on the web app
**Decision.** `ontology_edits.py` holds applying, checking, listing and renaming; `app.py` only talks to the model.
**Why.** It is pure logic with many edge cases, so it can be tested in isolation (28 tests), and no test needs a
server or a model.
**Alternatives.** Keeping it in `app.py` (testing needs the whole app).

### 44. Operations refer to names and are validated one by one
**Decision.** Operations use the names from the listing (case-insensitive when unique); an operation that fails is
rejected with a reason and leaves no partial change (each runs on a snapshot). Rejections for something that does not
exist yet are retried after the others, up to three passes, so the order the model chose does not matter. A name
renamed earlier in the same batch still resolves to the new name. Names are unique across classes, properties and
individuals (Turtle has one namespace); a cycle in the hierarchy, a datatype used as a class (or as the range of an
ObjectProperty), a class used as a datatype range, a prefix the Turtle export cannot declare, and an unknown reference
are rejected; renames update every reference; removing a class moves its subclasses up and needs `replace_with` while
the class is still used; an inverse is linked in both directions, and changing a property to a DatatypeProperty
removes its inverse on both sides. An integrity check before and after reports new problems.
**Why.** A model that is one rename ahead of itself (or that keeps using the old name after renaming) should not lose
a whole round, and a bad operation must never corrupt the ontology. An unknown prefix was accepted at first and
produced unparsable Turtle; it is now rejected with the list of usable prefixes, and the export also declares prefixes
that occur only in axioms. Linking inverses both ways removes a source of OOPS! P13.
**Alternatives.** Applying operations in order and failing at the first error (brittle); applying without validation
(dangling references that only show up in the Turtle); positional references (see 42).

### 45. Rejected operations go back to the model once
**Decision.** If operations are rejected, one correction call returns corrected operations for exactly those. If nothing is
applicable after that, the request ends with an error and the ontology stays unchanged; an empty list is a valid
answer ("nothing to change") and is shown with the model's summary.
**Why.** Most rejections are a small slip (a misspelled name) that the model fixes immediately; a second loop would
rarely help and would cost more.
**Alternatives.** No correction round (the user sees many rejections); unlimited rounds (cost, loops).

### 46. The model sees a compact listing, and unaffected modules are shortened
**Decision.** The prompt contains a text listing of the ontology instead of the JSON (about 11,000 tokens for 260 classes,
against 39,000). Modules whose name, classes or properties appear in the request are listed in detail (label,
description, source count); the others by class name and parent only. If nothing in the request matches, everything is
listed in detail.
**Why.** The model needs names, hierarchy and meaning to decide, not the exact JSON. A request about one module needs
that module in detail and the rest as context, about 5,000 tokens in total.
**Alternatives.** The full JSON (cost); always only the focus modules (the model could not find a class it should
link to); a UI selector for the focus (planned, not built; text matching works without extra clicks).

### 47. No conversation history; earlier requests are kept as a short list
**Decision.** The stored `history` (every previous prompt and the full ontology JSON) is gone and existing sessions drop
it on load. The state is the ontology itself; the last eight change requests are included in each prompt as "already
applied, do not undo", and files attached in step 8 are included once.
**Why.** The history repeated the full ontology in every message, and the edit prompts do not need it. Keeping the team's
earlier requests prevents the model from undoing them. Attached files were never given to the model before; now they are.
**Alternatives.** Keeping the history (size, and the old JSON would contradict the operations); no memory of earlier
requests (they are undone).

### 48. Syntax errors are fixed by renaming first, by the model last
**Decision.** If the Turtle does not parse, names that are no valid local names are renamed by the server (`VisualEncoding`
from "Visual Encoding"), with all references. Only if that does not help does the model see the error and answer
with operations. The old call also lost the namespace prefixes, which is fixed.
**Why.** Syntax errors come from our own serialization and in practice from invalid identifiers; a deterministic fix is
free, instant and predictable. References are matched by their exact spelling here, because two broken names may
differ only in punctuation ("Visual Encoding", "Visual-Encoding!"); the first version merged them and crashed. The
renames are shown next to the syntax badge, so they do not happen silently.
**Alternatives.** Always asking the model (cost for something a rule solves); sanitizing every name before every
serialization (silently changes names that would have been fine, and hides what the model produced).

### 49. This log is part of the repository and is kept up to date
**Decision.** `DECISIONS.md` is updated in the same change as the code it describes.
**Why.** The user asked for the decisions, their reasoning and the alternatives to be recorded.
**Alternatives.** Relying on commit messages (they say what changed, rarely what was rejected).

### 50. Source references from edits must be traceable
**Decision.** After the operations are applied, every `sources` entry and `see_also` URI that a class did not have
before must occur elsewhere in the ontology, come from the literature corpus, or be named in the request text;
anything else is dropped and listed in the result.
**Why.** An invented citation looks exactly like a real one, and the provenance of a literature-based ontology is
only worth something if it is real (the same rule as in generation, 41). A citation the team names in its feedback is
legitimate even if it is not in the corpus.
**Alternatives.** Rejecting the whole operation (loses the rest of a useful change); showing the citations to the
model so it can copy them (more prompt for a rare case); no check (the guarantee of 41 would only hold until the first
feedback round).

### 51. Feedback attachments and the request log only count when a round succeeds
**Decision.** Attached files are marked as used only after the round succeeded; a request enters the log of earlier
change requests (see 47) only if at least one operation was applied. The log keeps the last 30 entries.
**Why.** The first version marked attachments as used before the model call, so a failed call lost them; and a
question such as "Is the hierarchy fine?" was later presented to the model as an "already applied change".
**Alternatives.** Clearing attachments only on explicit removal (they would be sent again in every round).

---

## I. Evaluation

Background and sources: [`EVALUATION.md`](EVALUATION.md).

### 53. The built-in evaluation measures; it does not let a model judge
**Decision.** Stage A only computes deterministic measures (CQ coverage decided by rdflib, inventory coverage,
traceability, structure, HermiT). A model is used only to translate competency questions into SPARQL and to write
sample data, as in the existing CQ tests.
**Why.** The literature shows that LLM judgments of ontologies agree only moderately with experts: macro-F1 at most
0.66 for "is this CQ modelled" (OE-Assist, 2025); agreement on the ranking but not on absolute scores (RIGOR, 2025).
Wrong suggestions also mislead human reviewers.
**Alternatives.** An LLM rubric score (cheap, but not reliable enough to report as a quality figure; reserved for
ranking variants after calibration against experts, stage E); no automatic evaluation (every check by hand).

### 54. CQ coverage has three levels: full, partial, none
**Decision.** full = the query runs and returns data; partial = a query could be written with ontology terms, but a
term is missing or there is no answer; none = no query (or it does not parse). The CQ tests record which ontology terms
each query uses (`terms`), which also feeds traceability.
**Why.** CQ4OE (2026) shows that partial coverage is far higher than full coverage (about 89 % vs. 23.5 %); one
yes/no figure hides the difference between "nearly there" and "not modeled at all".
**Alternatives.** Only covered/not covered (the earlier report); a weighted score (an arbitrary weighting).

### 55. Hold-out questions come from the paper cards
**Decision.** Up to 10 questions extracted from the literature that the generation did not see are tested like the
team's. They are ordered by support; questions similar to the team's or to each other (word overlap after stop words
and stemming ≥ 0.5) are skipped; at most two per paper while others are available.
**Why.** The team's questions measure fit to the brief, not generalization. The paper cards already hold such
questions with their sources, so no extra effort is needed. The per-paper limit was added after the first run on the
real corpus: one taxonomy paper about uncertainty filled half of the set.
**Alternatives.** Holding back some of the team's own questions (there are only ten); generating new questions with
a model (RETROFIT-CQ, Pan et al. 2024 - an extra source of error; the extracted ones are traceable to papers).

### 56. Inventory coverage uses a stored link, then name matching; no embeddings yet
**Decision.** Module-by-module generation stores the concepts the plan assigned to each class (`inventory_concepts`,
as terms, not ids). Coverage counts a concept if a class is linked to it or its name or label matches the concept's
label or a variant (`concept_key`: case, hyphens, plural, CamelCase). Reported for all concepts, for the central ones
(≥ 2 sources) and per theme.
**Why.** The link is exact and free; the plan already knows which concept became which class. Terms instead of ids
keep it valid after the inventory is rebuilt (ids are renumbered).
**Alternatives.** Embedding similarity (Zaitoun et al. 2023; needs sentence-transformers/PyTorch and a threshold
that the literature has not settled - planned as a fallback for classes without a link); ids (break on rebuild).

### 57. "Untraceable", not "superfluous"
**Decision.** A class without sources, inventory link, passing CQ query or key-notion role is reported as untraceable:
a candidate for superfluous elements in the sense of Lippolis et al. (2025), to be reviewed, never removed
automatically. A failing CQ query does not count as a reason.
**Why.** A helper class demanded by a pattern or by the structure can be legitimate; only a person can tell. The measure
is still the cheapest signal of over-generation.
**Alternatives.** Calling them superfluous (overstates the evidence); counting failing queries (a broken query would
then justify any class).

### 58. HermiT via owlready2, in a separate process, on the ontology and the sample data; no error provocation
**Decision.** The reasoner check runs HermiT (owlready2, needs Java) in a child process with a 180-second limit, once
on the ontology and once with the CQ sample data. It reports consistency and unsatisfiable classes. Without Java it is
skipped with a note. No error-provocation tests (deliberately inconsistent data per disjointness axiom).
**Why.** HermiT has no timeout of its own and owlready2 keeps global state; a child process isolates both. Without
individuals a consistent ontology proves little (open world), so the generated sample data are reused. Error
provocation per disjointness axiom only confirms OWL semantics (a declared disjointness always detects such data)
and costs one reasoner start per axiom; the informative question - which sibling classes are *not* declared
disjoint - is answered structurally (disjointness coverage of sibling groups).
**Alternatives.** owlrl (pure Python, OWL 2 RL only, no unsatisfiability check); ROBOT (Java CLI, more setup);
ELK (no Python binding in owlready2).
**Result.** On the 229-class VA ontology both checks take about seven seconds together.

### 59. The report belongs to an iteration and can be downloaded
**Decision.** The evaluation is stored with the iteration it measured, shown as outdated after a change, and can be
downloaded as JSON. The CQ results of the current iteration are reused, so a repeated evaluation usually costs one
model call (the hold-out questions).
**Why.** Comparing variants and repeated runs (stage E) needs the figures per run outside the tool.
**Alternatives.** Re-evaluating automatically after every change (costs a model call per feedback round).

### 60. Concepts can be represented other than as a class, and "deliberately not modeled" is a result
**Decision.** Coverage distinguishes four outcomes per inventory concept: a class; represented otherwise (an individual
by name, or the concept's words inside a property name, e.g. "Encode" in `encodesAttribute`); deliberately not modeled
(a decision recorded with its reason when gaps were filled); missing. Central-concept coverage is reported as a class
and "represented in some form".
**Why.** In the first real run, 34 of the 130 "missing" central concepts were in fact property names and 4 were
individuals - actions and named frameworks are often rightly not classes. Counting them as gaps misleads, and so
would counting a reasoned "out of scope" as a gap again and again.
**Alternatives.** Class-only coverage (the first version); asking a model whether a concept is covered (see 53).
The property match is a name-based estimate and is labelled as such in the report.

### 61. Hierarchy is measured against the literature's own broader/narrower statements
**Decision.** Taxonomic recall: of the broader/narrower relations the sources state between terms that are both
classes - from the paper cards' broader terms and taxonomies (category -> taxonomy name) - how many does the class
hierarchy realize, directly or transitively (parent chain and SubClassOf axioms)?
**Why.** Depth alone says nothing about whether the hierarchy is right; a gold standard does not exist for this
domain (EVALUATION.md). The inventory is a reference with provenance, in the spirit of Dellschaft & Staab's taxonomic
measures. The real VA ontology realized 43 of 82 such relations, while the inventory held 936 broader statements and
329 taxonomies that generation had barely used.
**Alternatives.** Comparing with VIS4ML/VISO (stage C; different scope); depth and breadth only (no notion of
correctness).

### 62. Gaps are closed on the existing ontology, in packages, with recorded decisions
**Decision.** Two actions in the evaluation box - "Add missing central concepts" and "Build hierarchy from the
literature" - use edit operations on the existing ontology. The work is split into packages (12 concepts, 25
relations or 6 taxonomies) that the browser sends one by one (`/api/gaps/start`, `step`, `finish`). Each concept comes
with its definitions, broader terms (marked when they already are a class), citations and existing-ontology URIs.
The model may also decline; everything it declines is recorded with a reason (`gap_decisions`,
`gap_hierarchy_decisions`) and not proposed again. One action is one iteration and one entry in the feedback log;
an OOPS! check runs at the end. A dry run counts the work before the user confirms.
**Why.** Regenerating would discard everything refined since, cost a full run, and the gaps are known exactly. Packages
keep each call small, make progress visible and stoppable (as in the paper extraction, 31). Without recorded
decisions every click would present the same declined concepts again.
**Alternatives.** Regenerating with a better plan (still planned for future runs: hierarchy-aware planning);
one call for all gaps (output limit, no progress); adding everything automatically (the papers' "broader" is often
loose - part-of or related-to).

### 63. Every gap package is checked by the reasoner; it is corrected or rolled back
**Decision.** Before a run, the unsatisfiable classes of the ontology are recorded. After each package, HermiT checks
again. If a class became unsatisfiable or the ontology inconsistent, the model gets one correction request naming the
classes; if that does not resolve it, the package is rolled back and reported. Without Java the packages are applied
unchecked, with a note.
**Why.** In a test with a model that applied every stated broader relation blindly, 27 classes became unsatisfiable:
new superclasses collided with existing disjointness axioms ("Knowledge" below "Insight", which is disjoint with it).
A real model judges these relations, but an unsatisfiable class is a silent, serious error. With the check, the same
test ended with no unsatisfiable class.
**Alternatives.** Checking only at the end (the cause could no longer be attributed to a package); rejecting single
operations (the reasoner cannot say which operation caused it without many runs); trusting the model.
**Cost.** About three to seven seconds of reasoning per package on a 230-280-class ontology.

### 64. Literature questions the CQ suggestions saw are not hold-out questions
**Decision.** "Suggest competency questions" shows the model up to 40 questions from the inventory. These are now
recorded per session (`cqs_shown_to_model`, accumulated over all suggestion calls) and excluded from the hold-out
selection (55); the report states how many were excluded. Sessions from before the recording do not know what was
shown: there the first 40 inventory questions are excluded to be safe, with a note. New sessions start with an empty
record, so a team that never used the suggestions loses nothing.
**Why.** A question the model has seen can shape the team's questions and through them the ontology. Testing it as
"unseen" would flatter the hold-out score - the number the paper would use to argue for generalization. The
near-duplicate filter against the team's questions (55) only catches questions that were adopted almost verbatim.
**Alternatives.** Not showing literature questions to the suggestion step (they are the best grounding it has);
excluding only questions similar to the team's (misses indirect influence); splitting the inventory questions into a
suggestion half and a test half up front (cleaner for a study, but halves both; can be added for experiments).

### 65. Declined concepts can be reconsidered
**Decision.** In the evaluation details, every concept the model declined while filling gaps (62) has a "Reconsider"
button, plus "Reconsider all". It removes the recorded decision (under the concept's label and all its variants, since
the model may have named a variant) via `/api/gaps/reconsider`; the concept counts as missing again and is proposed by
the next "Add missing central concepts". The coverage in the stored report is recomputed at once (deterministic, no
model); the CQ results stay. The list now says that the model made these decisions.
**Why.** The decisions are the model's, not the team's. Without a way back, a wrong "out of scope" would be permanent
and hide the concept from coverage as "decided". Hierarchy decisions are not shown in the UI yet and are not covered.
**Alternatives.** Re-running the whole evaluation after each click (slow, may call the model for CQ tests); letting the
team confirm each decision before it is recorded (an extra step in every run; reconsidering afterwards is cheaper).

### 66. Gap filling links each class to its inventory concept; taxonomy classes get the taxonomy's citation
**Decision.** `add_class` and `update_class` take `inventory_concepts`. The gap prompt asks the model to set it to the
concept's label when adding a class, and to link an existing class with `update_class` when that class already
represents the concept under another name, instead of declining it as "already represented". The server accepts only
real inventory concepts (a variant is rewritten to the label; unknown ones are dropped and reported, existing links are
never re-checked). If the model forgets the link, a new class is linked to the package concept whose words begin or end
its name or label ("Incomplete Knowledge" -> `IncompleteKnowledgeEvent`), only if exactly one concept fits and the
concept is not a single short word. Hierarchy packages ask for the taxonomy's citation as `sources` of every added class.
**Why.** The first run with a real model (gpt-6-sol, VA corpus) added 97 classes, none with a link: 14 central concepts
counted as missing although they had been added under a slightly different name, and 17 "already represented by X"
were counted as declined instead of covered. 60 of the 97 classes, mostly taxonomy categories, had no sources, so
traceability fell from 98.7 % to 80.7 %.
**Alternatives.** Fuzzy or embedding matching at evaluation time (would also match wrong pairs; the package knows which
concept a new class is for); trusting every link the model writes (it could link concepts it never saw).

### 67. CQ tests keep their sample data and passing queries between iterations
**Decision.** A CQ test run gets the previous result for the same question set (the team's from `cq_test_report`, the
hold-out's from `holdout_test_report`). The previous sample data is kept, minus triples that no longer fit the ontology.
A query that passed before is run again on that data; if it still passes, it is kept and the question is not sent to
the model. Only the other questions go to the model, which sees the existing data and may only add to it. If every
question still passes, there is no model call.
**Why.** In the real run, two questions dropped from full to partial with "no result on the sample data" although
nothing they need had changed: each run generated new data and new queries, so the score varied without any change to
the ontology. A before/after comparison (and a paper) needs the measurement to stay stable. Keeping data and queries
makes a regression mean that the ontology lost something a working query used.
**Alternatives.** Repeating each test several times and averaging (costs several times as much and still mixes noise
into each number - useful for a study, not for every iteration); a fixed hand-written sample data set (the team would
have to maintain it for every change); regenerating everything with a fixed seed (the providers do not guarantee
reproducible output).
**Limitation.** Sample data only grows. If it ever gets in the way, the team can clear it by removing the stored
test result; there is no button for that yet.
**Revised by 96:** this holds between iterations of one generation; a new generation starts with new sample data.
("Test from scratch" in step 8 now also clears them by hand.)

### 68. An own upper layer by kind of thing, not an upper ontology
**Decision.** A third action, "Group root classes under an upper layer", places the root classes under five classes
that group by what things ARE, across the modules: `Process`, `Agent`, `InformationObject` with `Specification`
below it, and `Quality`. Process, Agent, InformationObject and Quality are disjoint. The server creates the layer (in
its own module `UpperLayer`, with fixed definitions) - not the model, so every project gets the same layer; a class
that already has one of these names is used as it is (in the VA ontology: `Agent` from the Provenance module). The
model then places the root classes package by package (25 per package) with `update_class` parent; the reasoner guard
(63) checks every package, which here matters most: a class that ends up below two disjoint upper classes is
unsatisfiable. Classes that fit none are recorded and not proposed again. The model is asked to name classes that mix
two kinds (an activity and its result) - candidates for splitting. Upper-layer classes count as traceable by design.
**Why.** After two real runs the VA ontology still had 83-87 root classes: the literature's broader/narrower relations
are too loose to group them (89 of them were declined in run 2), and the roots fall into a few kinds that cut across
the modules (processes such as DataTransformation and ModelBuilding, content such as VisualRepresentation, qualities
such as DataType and Uncertainty, agents). One layer by kind adds depth and, through disjointness, lets the reasoner
find classes that are modeled as two kinds at once.
**Alternatives.** One root class per module (repeats the module structure, adds no meaning and no useful
disjointness); aligning with BFO or DOLCE/DUL now (forces splitting central classes such as Visualization, User, Task
into several, adds terms domain experts cannot read; planned instead as an optional alignment module that maps only
these five classes, see open points); letting the model propose the upper classes (a different layer in every project
and run); a separate Role class for User or Analyst (with disjoint Agent it makes every person typed as a user
inconsistent - the Agent definition includes agents acting in a role instead).

### 69. The upper layer is domain-neutral by default, adjustable per project, and empty classes are removed
**Decision.** The default layer has six classes with definitions that give examples from several domains: `Process`,
`Agent`, `PhysicalObject`, `InformationObject` with `Specification` below it, and `Quality`; the five top-level ones
are disjoint. The project context (step 4) shows the layer and lets the team rename, redefine, add (at most 12) or
remove upper classes, set a superclass within the layer and choose which top-level classes are disjoint; "Reset to
default" goes back. The server validates names, superclasses (only within the layer, no cycles) and makes only
top-level classes disjoint. At the end of a "Group root classes" run, upper classes that the run created and that
carry nothing (no subclass, no SubClassOf target, no domain or range, no individual) are removed again, repeatedly, so
an emptied superclass goes too; the disjointness axiom is reduced accordingly.
**Why.** The first version (68) was tuned to visual analytics: there was no class for material things, so classes such
as Machine, Organism or Ingredient in another domain would have been left out or forced under InformationObject, and
the definitions used VA examples. Some domains need other categories altogether. Removing empty classes keeps a domain
without physical things from carrying an empty PhysicalObject.
**Alternatives.** Letting the model choose the layer per project (different in every run, no shared alignment);
several fixed layers per domain type (we cannot foresee the domains); keeping empty upper classes (clutter, and they
look like modeling gaps). A shared default stays the recommendation in the UI: one later alignment with DOLCE/DUL or
BFO then covers every project that keeps it.

### 70. Properties are consolidated into a core vocabulary that the team approves; each property is merged, placed below, or kept
**Decision.** A fourth action, "Consolidate properties", runs in three stages. (1) One model call proposes a vocabulary
of general relations (target 40-70) derived from this ontology's own properties: name by general meaning, domain and
range as specific as the absorbed properties allow (preferably upper-layer or module root classes), an inverse only
where both directions are needed, characteristics (transitive, symmetric, asymmetric, functional, inverse functional),
and a sample of the properties each relation covers. Invalid proposals are dropped one by one and listed. (2) The team
reviews and edits the vocabulary in the evaluation box and approves it; an edit after approval needs a new approval.
(3) The server creates the core relations (an existing property of the same name becomes the core relation), then the
model decides for every other relation, in packages of 40 (one direction per inverse pair): `merge_property` into a
core relation when only domain and range differ, `sub_property_of` when it carries a meaning of its own, or keep with a
reason (recorded, not proposed again). At the end the team's competency questions are re-tested with the kept sample data (67): queries
that used a merged property are rewritten; a question that passed before and fails now is reported as possible loss of
meaning.
The data model gains `sub_property_of` and `characteristics` (Turtle `rdfs:subPropertyOf` and owl:TransitiveProperty
etc., also read back on import), and a new edit operation `merge_property`, which removes the property, points every
reference to the target, merges the inverse into the target's inverse (or removes it) and lets later operations still
use the old name. The server enforces OWL semantics instead of trusting the model: a subproperty's or merged property's
domain and range must lie within the target's (otherwise every use would silently retype its subject or object), no
cycles, no mixing of object and datatype properties, a datatype property can only be functional, and the OWL 2 DL
simple-property rule (no functional, inverse functional or asymmetric on a transitive property, its inverse, or any
superproperty of one). The evaluation reports relations (one per inverse pair), top-level relations, properties with a
superproperty and with characteristics; the action is offered when there are more than 70 top-level relations.
**Why.** The VA ontology had 530 object properties for 345 classes - 275 relations, almost all with one domain and one
range (`depictsMultidimensionalData: ParallelCoordinatesPlot -> MultidimensionalData`), no hierarchy, only 76 used by
any competency-question query. Narrow domains and ranges make reuse impossible and, as OWL inference rules, retype
individuals. Variant C keeps real distinctions as subproperties while folding pure domain/range variants into one
relation. The vocabulary is a design decision, so the team approves it before 500 properties are changed. Nothing in
the prompts is domain-specific: the vocabulary is derived from the ontology at hand, with general relation families
(part-whole, order, participation, input/output ...) only as orientation.
**Alternatives.** Variant A, replacing all properties with the core relations (loses distinctions that queries need);
variant B, keeping every property as a subproperty (keeps the bloat); a fixed relation vocabulary such as the OBO
Relation Ontology or DOLCE relations (domain-bound or too abstract for most teams; can be added later as an alignment
of the core relations); letting the model consolidate without approval (the vocabulary shapes every later query);
expressing the lost specialization as class restrictions now (`ParallelCoordinatesPlot SubClassOf depicts some
MultidimensionalData`) - right, but part of the axiom step that is still to come.
**Cost.** On the VA ontology about 21,000 input tokens for the proposal and about 46,000 per package (7 packages).

### 71. After a consolidation, tests are translated through the merges and run over the ontology's entailments
**Decision.** Three changes after the first real consolidation run. (a) A core relation that takes over the name of an
existing property loses that property's inverse and superproperty (they belonged to the narrow property); the
vocabulary's own inverse is linked afresh. (b) The edit engine records every merge (`p -> c`; `^c` when p was the
inverse of c and c has none). At the end of the run the stored sample data and queries of the team's and the hold-out
questions are translated through these merges - triples rewritten (or turned around), queries rewritten to `:c` or the
path `^:c` - before the re-test, so only queries that really break go back to the model. (c) Every CQ test runs over the
sample data plus what follows from the ontology: superproperties, inverses, symmetric and transitive properties,
superclasses (not domain and range typing). A query on a general relation then finds data stated with a subproperty, as
a reasoner would. Plus "Test from scratch" and "Evaluate from scratch", which discard the stored data and queries.
**Why.** In the run the consolidation itself worked (530 -> 301 object properties, 275 -> 111 top-level relations), but
(a) nine core relations kept the narrow inverse of the property whose name they took; one of them made a presentation
an information object and the sample data inconsistent. And the team's questions fell from 10 to 3 fully covered, all
with "no result on the sample data": 58 sample triples used merged properties and were dropped, the data chains broke,
and the model, allowed only to add data, did not repair long joins. That measured the test procedure, not the ontology.
**Alternatives.** Regenerating sample data after every consolidation (loses comparability, the reason for 67);
treating any failure as loss of meaning (it mostly was not); full OWL reasoning on the test data (HermiT already checks
consistency; for query answering the closure above is enough and fast); RDFS domain/range typing in the closure (would
let queries pass on types nobody stated, including ones derived from modeling errors).
**Repair.** The VA run copy was repaired directly (the nine inverse links removed, recorded in its feedback log);
afterwards it is consistent with its sample data. Its tests need "Test from scratch" once, because the merges of that
run were not recorded yet.

### 72. English is the default language; generated output follows the conventions of the ontology
**Decision.** The tool and the ontologies it models are English by default: the label-language convention defaults to
`en`, and the ontology label (`rdfs:label` of the owl:Ontology) uses the first label language like the descriptions,
instead of a hard-coded `@de`. Other languages remain possible through the conventions. Further corrections after an
external review of the consolidated VA ontology: properties created without a label get a lowercase verb phrase ("has
part", as the model writes them), not "has Part"; the approved core relations live in their own module `CoreRelations`
(so they carry `opla:isNativeTo`); the plain-English text of the upper-layer disjointness is regenerated when empty upper
classes are removed and uses correct articles; the Turtle export declares only prefixes that are used.
**Why.** The tool's UI and prompts are English and the ontologies are meant to be shared internationally; the German
defaults were left over from the first version. The review found the `@de` label, mixed label styles, 57 new properties
without a module, a disjointness text that still named the removed PhysicalObject, and six unused prefixes.
**Alternatives.** Putting each core relation into the module of its domain (most have the whole upper layer or nothing
as domain, so the module would be arbitrary); keeping all prefixes of the selected standards (dead lines that suggest
reuse which does not happen).
**Not changed (reviewed and rejected).** The review's suggestion to re-add the merged specific properties as
subproperties would undo most of the consolidation (variant B in 70); the lost domain/range specifics belong in class
restrictions (the axiom step). Its statement that the upper classes are not declared disjoint was wrong (they are, as
owl:AllDisjointClasses), and so was "precedesState was deleted": it was merged into `precedes`, so transitivity applies.

### 73. Prefixes come only from real namespaces
**Decision.** A selected standard yields a prefix declaration only (1) from an explicit prefix and namespace, (2) from
the table of known vocabularies, where the key must appear as a whole word in the standard's name and the longest key
wins, or (3) from a URL that looks like a namespace: ending in `#`, or in `/` on a host for persistent namespaces
(purl.org, w3id.org, purl.obolibrary.org, schema.org, w3.org/ns/, xmlns.com). Specification and documentation pages
(`w3.org/TR/...`, `.../docs/`), repositories and search URLs yield nothing. The RDF Data Cube vocabulary (`qb:`) was
added to the table.
**Why.** The reuse step of the VA project produced `dc:` for DCAT 3 (substring "dc" in "dcat"), `vocabdatacub:` bound
to the specification page instead of `http://purl.org/linked-data/cube#`, and `docs:` for the Vega-Lite documentation;
short keys such as `as`, `ro`, `ex`, `org` or `time` matched inside unrelated words. A wrong namespace makes every
reused term point nowhere, which is worse than no prefix.
**Alternatives.** Resolving every URL over HTTP to find the namespace (slow, often blocked, and pages do not say their
namespace reliably - planned instead as loading the vocabulary itself in the reworked reuse step).
**Context.** Reuse did not happen in the VA ontology at all, independent of the prefixes: the original has no external
term. The causes (no term lists, no reuse channel in planning and module generation, mostly "do not reuse directly"
hints, a German prompt) are addressed by the reworked reuse step, still to be built.

### 74. The reuse step records a namespace, a prefix and a decision, and loads the vocabulary itself
**Decision.** Step 7 (patterns and standards) now asks the model, in English, for each standard's namespace (the IRI
its terms live in - not a specification or documentation page), prefix, documentation URL, an optional download URL,
and a decision: `align` (keep the project's own classes and link them - the default), `use_terms` (use its terms
directly, for generic things), or `reference` (no RDF vocabulary, or orientation only). Suggestions are cleaned
(`clean_standard`): a namespace that is not one is dropped, known vocabularies are completed from the table, older
entries with only a URL keep working. The team can edit namespace, prefix, download URL and decision, remove a
standard, or add one by uploading a file. "Load vocabulary" fetches it - download URL, a known source for vocabularies
whose namespace serves no RDF (schema.org, Data Cube), then the namespace with content negotiation; HTML is refused,
text/plain is tried as Turtle - and stores a term list per prefix on the server: classes and properties of the
vocabulary's own namespace with English label, definition, parents, domain and range (at most 4,000 terms, files up
to 20 MB). Failures are shown with every URL tried and the suggestion to upload the file.
**Why.** Reuse never happened (73): the model never saw which terms exist and was told not to invent any, the stored
URLs were mostly web pages, and the prompt was German. A term list is the precondition for both later parts: aligning
existing ontologies (C) and reusing terms during generation (B), each of which can then check that a term exists.
**Alternatives.** Letting the model name terms from memory (unverifiable, the P40 risk); importing whole vocabularies
with owl:imports (pulls in their axioms and size, and still gives the model no term list); a fixed list of allowed
vocabularies (domain-dependent).
**Checked.** On 2026-10-16 PROV-O (50 classes, 83 properties), SKOS, RDF Data Cube and schema.org (938 classes, 1,538
properties) loaded in under 1.5 seconds each; the VISO URL suggested by the model returns 404, which the UI reports.

### 75. Existing ontologies are aligned with loaded vocabularies; the server checks terms, fit and logic
**Decision.** A fifth action, "Align with <prefixes>", is offered once a vocabulary is loaded. The server finds
candidates without a model: for each own class and property the vocabulary terms with the same name or label, the
class whose single word is the head of the own name ("ProvenanceActivity" -> prov:Activity), or a word overlap of at
least 0.5 (stop words such as is/was/by removed, stemmed); at most four per own term; terms already linked or declined
are left out. The model decides by meaning, in packages of 25: `SubClassOf` (usual), `EquivalentClasses` (same
instances only), `sub_property_of` a vocabulary property, or nothing with a reason (recorded). The edit engine receives
the term lists: a prefixed term of a loaded vocabulary must exist and be of the right kind (a class is not a property),
and a subproperty of a vocabulary property must fit its domain and range - through the ontology's links and the
vocabulary's own hierarchy, retried after the other operations so that a class link in the same answer counts. The
reasoner guard and the evaluation reason over the ontology plus the axioms of the vocabulary terms it uses
(superclasses, disjointness, domain and range, transitively), not whole vocabularies. Loaded vocabularies' prefixes are
declared in the export, and vocabulary properties used as superproperties are declared. The evaluation counts links
to reused vocabularies.
**Why.** Reuse needs a channel for ontologies that already exist (the VA ontology rebuilt PROV-O in its Provenance
module). Checking only the prefix let any invented term through; checking the term but not its domain, range and
disjointness would let alignments in that make the ontology inconsistent once someone loads the vocabulary.
**Alternatives.** Embedding similarity for candidates (needs a model or library and a threshold; names and labels
catch the cases that matter and keep the action cheap); letting the model search the whole term list (schema.org alone
has 2,500 terms); importing whole vocabularies for reasoning (schema.org would exceed the reasoner's time limit).
**Checked.** On the VA run copy with PROV-O, SKOS, Data Cube and DCAT loaded: 53 own terms with candidates in 3
packages, among them EntityWithProvenance -> prov:Entity, ProvenanceActivity -> prov:Activity, Agent -> prov:Agent,
Dataset -> dcat:Dataset, hasStartTime -> prov:startedAtTime (and noise such as recordsReasoning -> dcat:record for the
model to decline).
**Real run (2026-10-16, gpt-6-sol).** 3 class links (Agent, EntityWithProvenance, ProvenanceActivity below their PROV-O
counterparts) and 10 property links (isGeneratedBy, isAttributedTo, generatesEntity, seven provenance-record properties
below prov:has_provenance); 40 candidates declined; consistent with the PROV-O axioms and the sample data; competency
questions unchanged (10/10, hold-out 7/10); about 186,000 input tokens.

### 76. Every improvement action keeps the reasons of its decisions, and each can be reconsidered
**Decision.** The decisions of the hierarchy, upper-layer, property and alignment actions are stored like those of
"Add missing concepts" (65): per action a key (what the action leaves out next time) with the displayed item and the
model's reason; older projects with plain lists are converted on access. The evaluation report carries them, the
details list them per action with "Reconsider" per entry and "Reconsider all", and `/api/gaps/reconsider` takes the
action as `kind`. The property action's button reopens an applied vocabulary ("Map the remaining properties") instead
of proposing a new one, and a second run keeps the inverse and superproperty of relations that already are core
relations.
**Why.** After the alignment run, 40 declined candidates were listed only once, in the result message; the reasons
(e.g. for DataDerivation -> prov:Derivation) were lost and could not be revisited. Without reconsider, a wrong decision
by the model would be permanent. A second consolidation run would have cleared `isGeneratedBy ⊑ prov:wasGeneratedBy`,
set by the alignment, because it treated every existing core relation like a narrow property taking over a name (71).
**Alternatives.** Storing only names (no basis to reconsider); asking the team to confirm each decision during the run
(an extra step for dozens of items).

### 77. Generation is offered the matching terms of loaded vocabularies and checked against them
**Decision.** Both generation paths receive a section "Reusable vocabulary terms": in module-by-module generation the
terms that match the module's planned classes and their concepts (at most 25), in the single call the terms that
match the use case, the competency questions and the key notions (at most 40). Matching is the same as for the align
action (same name or label, head word, word overlap), plus: a longer text must contain all words of the term. Each
term carries the team's decision; the rules say how to reuse - for `align` keep the own class or property and link it
(parent, SubClassOf, EquivalentClasses for identical meaning, `sub_property_of` within domain and range), for
`use_terms` the term may also be used directly as parent, domain or range; planned classes keep their names. The
answer format gained `sub_property_of`. After generation, references to loaded vocabularies are checked like edit
operations (term exists, right kind, a subproperty fits domain and range); what fails is removed and reported with the
number of links. The crude stemming now maps "-ies" to "-y" (entities/entity).
**Why.** Generation had no channel for reuse (73): the model knew neither prefixes nor terms. Offering only matching
terms keeps the prompt small and relevant. A first version offered small `use_terms` vocabularies in full to every
module; on the VA ontology every module then received the 36 Data Cube terms - noise, so it was dropped.
**Not done.** Reuse in the planning call (mapping a concept directly to a vocabulary term instead of planning an own
class): it would change how planned classes, inventory links and modules fit together; the module-level reuse covers
the `align` default.
**Checked.** On the VA ontology with PROV-O, SKOS, Data Cube and DCAT loaded, the Provenance module would be offered
prov:Agent, prov:Activity, prov:Entity and seven more PROV terms, the Data module dcat:Dataset, qb:DataSet and related
terms; Knowledge, Task and Interaction none.
**Real run (2026-10-16, gpt-6-sol, fresh generation of the VA ontology with PROV-O, SKOS, Data Cube and DCAT loaded).**
Only 2 links came out of generation (CognitiveActivity and CollaborativeCommunication below prov:Activity), against 13
from the align action on the earlier ontology: offering terms is not enough for the model to link systematically while
it builds a module. The align action after generation remains the reliable path; generation-time reuse is a bonus.
**Since 98** the plan links classes to vocabulary terms, and terms of `use_terms` vocabularies can replace own classes.
The run also showed a regression of this change, see 78.

### 78. Module names used as prefixes are repaired
**Decision.** After generation, a reference `Module:Class` - a module name in the place of a prefix, with an existing
class after it - becomes `Class`, and the report lists it as repaired. The reuse section of the prompt says that
prefixes belong only to vocabulary terms and own classes, also of other modules, are referred to by bare name; the
listing of the other modules says so too. The count of links to vocabularies ignores module names.
**Why.** The fresh generation after 77 produced 25 references such as `User:Audience` and `Model:Model` (the original
generation had none): the new prompt spoke of prefixed names while the other modules were listed as "User: Audience,
...". In Turtle that becomes `:User:Audience`, a valid but dangling IRI - 25 domains, ranges and superclasses pointed
to classes that do not exist - and the link count reported 27 links where 2 were real.
**Alternatives.** Rejecting such references (loses the modeling decision, which is right apart from the notation);
listing other modules' classes without the module names (the grouping helps the model use the right classes).
**Repair.** The fresh-generation copy was repaired directly (25 references, recorded in its feedback log).

### 79. "Regenerate" asks once and starts; a failed generation shows the previous ontology again
**Decision.** The Regenerate button asks for confirmation (the current ontology and everything the improvement actions
and feedback rounds changed will be replaced; export first to keep it) and then starts the generation. If the
generation fails, the previous ontology - which the server keeps until a new one succeeds - is shown again with the
error. The generation report separates corrected Module:Class references from removed ones. The remaining German
user-facing messages and the Turtle repair prompt are English (72).
**Why.** Regenerate only hid the ontology and showed a "Generate Ontology" button, which looked as if the ontology had
been deleted; a failed generation also left the view empty although nothing had been lost.
**Alternatives.** Keeping the two-step flow with an explanation (one click more for the same result).

### 80. An answer without operations but with a summary or decisions means "change nothing"
**Decision.** If the model's answer has no `ops` field but a summary or a list of skipped items, it is read as an
empty list of operations: nothing changes, the skipped items are recorded as decisions. An answer with neither (for
example a whole ontology instead of operations) is still an error. Failed packages of an improvement action now show
their reason in the result; their items stay undecided, so running the action again retries them.
**Why.** In the align run on the fresh generation, two of three packages failed with HTTP 500 ("the model's answer
contains no list of operations"): for packages where no candidate fitted, the model answered with a summary and the
declined items only - a correct answer that the server rejected. The UI counted the failures without saying why.
**Alternatives.** Asking the model again with a reminder of the format (one call more for an answer that was right).

### 81. Provider errors are reported as such, and a reached limit stops an improvement run
**Decision.** `call_llm` translates errors of the model provider: a reached limit (rate limit or message quota - HTTP
429, or 400/403 with "limit", "quota" or "exceeded" in the message) becomes HTTP 429 with the model's name and the
advice to wait or choose another model; a refused key 401; no connection or a timeout 504; any other provider error
502. Errors of the tool itself (an unreadable answer, a truncated answer) stay as they are. An improvement run stops
at a 429 or 401 instead of sending the remaining packages, and says so; unexpected errors of a package are also
written with their stack trace to the server log.
**Why.** After 80, the align run on the fresh generation failed again with two HTTP 500s; the cause was the message
quota of the RWTHgpt model gpt-6-sol. The provider's error surfaced as a generic 500 with the name of an SDK class, and
the run kept sending packages that could only fail.
**Alternatives.** Retrying with backoff (a message quota resets after hours, not seconds); switching to another model
automatically (changes the results without the team noticing - the run then continued with gpt-6-luna, chosen by the
user, which a comparison has to note).

### 82. The server code is split into modules; app.py keeps the endpoints
**Decision.** `app.py` (5,700 lines) is split without any change in behavior into `store.py` (sessions and their
files), `llm.py` (model calls, provider errors, token usage, JSON answers), `project.py` (context, conventions, ODP
catalog), `ontology_io.py` (Turtle/RDF, prefixes, SHACL), `corpus.py` (data files, literature, inventory),
`momo_steps.py` (prompts of the steps before generation), `vocabularies.py`, `editing.py` (edit operations, provenance
guard, OOPS!), `testing.py` (CQ tests), `generation.py` and `improvements.py`; `app.py` keeps the endpoints and their
request models (about 1,400 lines). Imports go one way (store and llm at the bottom, improvements and app at the top);
there is no cycle. Every module calls the model as `llm.call_llm(...)`, so tests replace it in one place
(`llm.call_llm`, `editing.check_oops`); the tests refer to functions in the module that now holds them.
The split was done by a script that assigns every top-level statement to a module and computes the imports; every
line of the old file is in exactly one new module (checked by comparing the lines), the 89 tests pass unchanged in
substance, and on a copy of the VA project loading, Turtle export and counting the packages of all five improvement
actions give identical results before and after.
**Why.** PLAN.md phase 0: almost every later phase changes the generation and the improvement actions, and most bugs
of the last days arose at transitions inside the single large file.
**Alternatives.** The five modules named in PLAN.md only (corpus, generation, vocabularies, improvements, testing):
the shared foundations (model calls, Turtle, context, edit operations) would have had to sit in one of them and
created import cycles - the inventory prompts need the context, the context draft needs the inventory - so they got
modules of their own. Keeping `app.py` as a facade that re-exports everything (tests unchanged): replacing
`app.call_llm` in a test would then not reach the modules, which is exactly the kind of silent gap the split is meant
to remove. Splitting the UI as well: postponed to phase 4, where it is rebuilt anyway.

### 83. The team decides conflicting definitions in step 4; generation and evaluation hold to them
**Decision.** Step 4 lists the conflicts of the concept inventory, most sources first, each with its issue, its
positions and the sources holding them. Per conflict the team **takes a position**, writes an **own definition**,
**splits** the concept into 2-4 classes, or **leaves it open**. Every decision except "open" names its class(es) and
their definitions; class names are unique across all decisions. Decisions are stored in the project context under the
concept (not the inventory id), so they survive a rebuild of the inventory; a decision whose concept is no longer a
conflict stays valid and is listed at the end. An optional model call (packages of 15 conflicts, in parallel)
recommends a decision with a reason; recommendations are stored apart and become decisions only when the team
accepts them, one by one or all at once.
Effect:
- `context_block` lists the decisions as "Decided definitions" in every prompt, ahead of the glossary and the sources.
- The planning gets a rule for them, and the server then fixes the plan: the class that holds the concept takes the
  decided name, the further classes of a split go into the same module (an unplanned concept into the module of its
  theme), and all carry the concept.
- The module prompt marks those classes with DECIDED DEFINITION.
- After generation the server writes the definitions into the descriptions and reports where the model deviated and
  which decided class is missing.
- The evaluation checks without a model that every decided class exists and carries its definition (also matching a
  class from before the decision through its inventory link); **Apply decided definitions** repairs an existing
  ontology with edit operations (replace descriptions, add the missing classes of a split next to the concept's
  class), again without a model.
- The context draft no longer resolves conflicts in the glossary or asks about them; it uses the decided definitions.
**Why.** PLAN.md phase 1: the VA inventory has 58 conflicts (Visualization as process, artifact or explanation method;
Insight; Interaction ...). So far the model resolved them silently during generation ("where they differ, follow the
project context, otherwise the majority of sources"), and the context draft put its own resolutions into the glossary
marked [confirm] - a decision of the model, not of the team, and not checked afterwards.
**Alternatives.** Leaving conflicts to the context questions (at most 8 questions for 58 conflicts; the answers end up
as prose that nothing checks). Asking the model for every split during generation (the planning would decide a
modeling question the team should own). Only reporting deviations after generation instead of writing the decided
text (the team's text is fixed, so a deviation is never better - the report still says where the model deviated).
A model call for splits in existing ontologies, to move subclasses and properties to the new class: postponed; the
repair adds the class next to the concept's class, and the feedback round can move the rest.

### 84. One generation path: plan, then module by module - with or without literature
**Decision.** The single-call generation (`ONTO_SYS`, `build_initial_prompt`, `build_momo_context`) is removed. Every
project is generated by a plan call and one call per module, four at a time:
- With a literature inventory, as before: the plan assigns inventory concepts to the modules.
- Without one, the plan derives the classes from the use case, the competency questions, the key notions and the
  data preview, and gives each planned class a one-sentence note; the module prompt shows the note instead of the
  sources' material, and a class missing from a module's answer gets the note as its description.
- Without key notions the plan proposes 3-8 modules (named like key notions; a module named twice is merged); with
  key notions the modules stay fixed.
- Plan and module prompts now get the data preview (at most 20,000 characters) and the use case as written in the
  generation step, including its additional requirements - both reached only the single call before.
- The reuse terms offered to a module are also matched against the notes of its planned classes, so that a project
  without literature, whose class names alone say little, still finds them.
**Why.** PLAN.md phase 2, before phase 3, so that the design decisions of phase 3 are built once: generation-time reuse
had to be built for both paths and only worked well in one; the decided definitions of phase 1 reach only the module
path. A single call also cannot write a larger ontology within the output limit.
**Alternatives.** Keeping the single call for small projects (two paths again, each later change twice). Requiring key
notions before generating (MOMo asks for them, but the tool guides rather than blocks; the plan's own modules are the
fallback, and the report says that they were proposed).

### 85. A project picker lists the saved projects; a failed restore no longer starts a new project
**Decision.** **📂 Projects** in the header lists all saved projects (`GET /api/sessions`), last saved first, with
title, iteration, classes and modules, number of sources, save time and the first characters of the id; empty
projects only while they are open. **Open** remembers the project in the browser and reloads the page - the same path
as after a restart. A project can get its own title (`POST /api/session/rename`, stored as `title`, exported with
the project); without one it is named after its ontology, else after its use case. When restoring a project fails
partway, the page keeps that project and says so instead of creating a new one, and a stored step that no longer
exists falls back to step 1.
**Why.** The browser remembered only the last project; the other saved projects (several copies of the VA project
among them) were reachable only through the browser console. The copies share the ontology name, hence the own title.
While testing, a project with a stored step 9 failed in the middle of restoring: the page then silently created a new
empty project, so the saved one seemed lost.
**Alternatives.** Switching without a reload (every part of the page state would have to be reset - the reload
reuses the tested restore path). Deleting projects from the list: left out; projects are archived, and users
delete their data themselves.

### 86. Follow-ups of wine run 1: named key notions, OWL 2 datatypes, richer plans and traceability without literature
**Decision.** Four fixes from [`examples/wine/RUNS.md`](examples/wine/RUNS.md):
- **Key notions** are only rows with a name: the server does not store empty rows (nor empty competency questions),
  the pattern step refuses to run without a named notion, and the UI counts only named notions. Continuing from
  step 6 with suggestions that were not added asks first and names them.
- **Datatypes**: the module prompt lists the OWL 2 datatypes and says how to write a year and a date. The reasoner
  check replaces a range outside the OWL 2 datatype map with `rdfs:Literal`, and literals of such a type with plain
  ones, then reasons; the report lists the replaced datatypes with their properties
  (`reasoner.datatypes_outside_owl2`). The ontology itself is not changed.
- **Planning without literature** also asks for the notions a domain expert expects beyond the words of the
  questions (kinds, parts, participants, places and times, value sets), and for the things the questions name
  individually as individuals; 5-15 instead of 4-15 classes per module.
- **Traceability** records its basis: `literature` with sources or an inventory, `competency questions` without
  them, `none` without tested questions either (no percentage then). The evaluation names the basis.
**Why.** In run 1 an empty placeholder row counted as a key notion, so the pattern step ran and the model invented
six notions; suggestions not added with "+ Add" were lost without a word. HermiT stopped on `xsd:gYear`, so the
logical check reported nothing at all. The plan had six classes for a wine shop and no individuals although the
questions name Bordeaux, Cabernet Sauvignon and seafood. Traceability showed 50 % "untraceable" because there were no
sources, which reads as a defect of the ontology.
**Alternatives.** Rewriting non-OWL-2 ranges in the ontology itself (`xsd:gYear` -> `xsd:integer`): changes the
team's model silently, and some projects may not target OWL 2 DL; reported instead. Leaving datatypes to the project
conventions only: run 1 had OWL 2 DL in the conventions and still got `xsd:gYear`. Blocking navigation away from
step 6 everywhere: only the Continue button asks; the sidebar stays free, as MOMo guides rather than blocks.

### 87. CQ sample data may describe the ontology's own individuals
**Decision.** The guard on the CQ sample data rejects a triple about an ontology term only if the term is a class or
property, or if the triple is a schema statement (typing as a class or property, `subClassOf`, `subPropertyOf`,
`domain`, `range`, `equivalentClass`, `equivalentProperty`, `disjointWith`, `inverseOf`). Triples about the
ontology's individuals are instance data and are kept; the CQ test prompt says they may be used and described.
**Why.** In wine run 2 the plan created individuals the questions name (Bordeaux, Red, Cabernet Sauvignon). The model
wrote its sample data about them, and the guard dropped all nine triples about `:Bordeaux` as "changes an ontology
term", so four sound queries found nothing and the run scored 0 of 7. The guard was written when ontologies had
hardly any individuals.
**Alternatives.** Telling the model to create its own sample individuals only: the questions name Bordeaux, so the
query has to use the ontology's `:Bordeaux`, and a second individual for the same thing would make the test pass on a
copy rather than on the ontology.

### 88. Follow-ups of wine run 2: pattern choices follow the key notions, no repeated hierarchy, fairer traceability
**Decision.**
- **Patterns:** continuing to the pattern step drops the choices for key notions that are no longer in the list
  (and says which) and asks for suggestions only for notions without a choice (`suggest-patterns` with `only`);
  existing choices stay. The endpoint keeps only suggestions for the notions asked for, spelled as in the list.
- **Axioms:** merging the modules leaves out SubClassOf axioms that only repeat a class's `parent`; the generation
  report counts them (`redundant_axioms`).
- **Traceability:** a passing CQ query also traces the domain and range classes of the properties it uses.
**Why.** In run 2 the pattern list still held six choices for notions the model had invented in run 1, and the
pattern step was not offered for the real ones, because it only ran on its own while the list was empty. Three of
five axioms were `SeafoodDish SubClassOf Dish` and the like, already stated by the hierarchy. Traceability counted
`WineColor` as untraceable although the passing query for "Is Bordeaux red or white?" needs it as the range of
`hasColor` (run 2: 73.3 % -> 53.3 % untraceable).
**Alternatives.** Dropping stale pattern choices on every save: a notion renamed while typing would lose its choice
without the user seeing it; the step change is visible and says what was removed. Re-suggesting patterns for all
notions after a change: would overwrite choices the team made by hand. Counting every class connected to a used
property through the hierarchy as well: too generous; a superclass is not needed for the answer.

### 89. Core relations are decided in step 7, before generation, and the modules build on them (PLAN.md phase 3a)
**Decision.** Step 7 gets a card **Core Relations**. One model call proposes the vocabulary (`/api/properties/propose`
with `before_generation`) from the use case, the competency questions (numbered, so each relation can name the
questions it serves under `covers`), the key notions and - with literature - the 250 best-supported relations of the
inventory. Size: about 5-15 relations without literature, 20-50 with. Domain and range may only be classes that
certainly exist after planning: the key notions (each is a class of its module) and the classes decided in step 4;
otherwise empty ("any"). The vocabulary is stored as before (`property_vocab`) with `basis: "plan"` and the allowed
classes; the team edits it in the same table as the consolidation and approves it. Only an approved (or applied)
vocabulary is used. The generation then
- gives every module prompt the core relations and the rule: use a core relation wherever it fits and the classes lie
  within its domain and range; create an own object property only where a question needs a distinction, and then
  below a core relation (`sub_property_of`), within its domain and range; never define a core relation;
- creates the core relations itself in the module `CoreRelations`, drops a module's own version of a core relation or
  of its inverse, and sets a domain or range the plan did not create as a class to "any" instead of a placeholder;
- reports properties below a core relation, those without one, and those outside the domain or range of their core
  relation (the rules of 70, here only reported) in `modular_report.core_relations`.
On by default: the card proposes on its own when step 7 is entered before the first generation; **Don't use core
relations** switches it off (`status: "off"`), and then nothing is proposed again unless asked. Projects that already
have an ontology are not changed: the card offers a proposal, and an approved vocabulary from a consolidation (basis
"ontology") is used by their next generation. The shared code moved from `improvements.py` to a new module
`relations.py`, which generation and repair both import. The consolidation in the evaluation stays as a repair tool;
a vocabulary from step 7 is reviewed there, not in the evaluation box.
**Why.** In both wine runs the modules modelled the pairing relation twice (`goesWellWith` in the Wine module,
`isSuitableWithWine` in the Dish module), because modules run in parallel and do not see each other's properties;
every object property came with an inverse. In the VA project the relation vocabulary was derived only after 530
narrow properties existed, at about 0.55 M input tokens (PLAN.md). A vocabulary decided before generation costs one
call and is visible to every module.
**Alternatives.** Allowing any inventory concept or upper-layer class as domain or range: the plan may not create
such a class (upper layer before planning is phase 3b), and a missing class would become a placeholder. Letting
modules record where they use a core relation (`Wine goesWellWith Dish` as a scoped restriction): right, but that is
the class-restriction step (phase 5); until then the core relation's own domain and range carry the main class pairs.
Rejecting or repairing violations automatically: reported first, as the rules of 70 decide on edits, not on a fresh
generation; a repair would need another model call per module.

### 90. Follow-ups of wine run 3: specific core relations, own properties for own kinds of connection, labels
**Decision.**
- **Proposal prompt:** each core relation names one kind of connection; catch-alls (hasDescription, hasProperty,
  hasAttribute, hasDetail, hasFeature, isRelatedTo) are ruled out by name. "Any" as domain or range only where a
  relation really connects many kinds of things, instead of "prefer empty to a class that is too narrow".
- **Module rule:** a module creates its own object property for a connection of its own kind - to a different kind
  of thing (a value set, a kind or variety, a place, a time) or a distinction a question needs - and places it below
  a core relation only if it shares that relation's meaning; otherwise without one. Still not allowed: a property that
  only restricts a core relation to particular classes.
- **Labels:** both vocabulary prompts ask for labels in every label language; they are kept with the relation while it
  keeps its name (`label_name`) and dropped after a rename in the table. Core relations get labels when they are
  created, in the generation and in the consolidation; the first language falls back to the name ("has part").
- **Structural metrics:** core relations are not counted as "properties without domain or range".
- **Pattern step:** the cleanup of pattern choices also runs when step 7 is opened from the sidebar; new notions without
  a choice are named with a button. Model calls still only start from "Continue" or a button, never on opening a step
  or restoring the page.
**Why.** In run 3 the model proposed `hasDescription` (Wine -> any), and the modules, told to create own properties
"only where a question needs a distinction", put colour, characteristics and grape variety under it and even
origin and vintage below it; `WineVariety` lost its link and Cabernet Sauvignon became a wine. The core relations were
created without labels (86.1 % instead of 100 % labelled), and the three general relations counted as structural
problems. The stale pattern entries survived because step 7 was opened from the sidebar.
**Alternatives.** Rejecting catch-all names on the server: a list of names is easy to bypass and would reject a
legitimate `describes` in a documentation ontology; the prompt rule and the team's review suffice. Requiring every
module property to sit below a core relation: forces wrong placements like origin below description.

### 91. A CQ test passes only on data of the right classes and for the whole question
**Decision.** Two checks in the competency-question tests:
- **Sample data of the wrong class:** a triple whose subject or object has asserted types (in the ontology or the
  sample data, with superclasses) none of which lies within the property's declared domain or range is dropped and
  listed as a sample issue, in new and in kept sample data. An individual without an asserted type is not checked,
  and a domain or range that is not a named class (a union) is not checked either.
- **Part of the question:** the test model states per query what part of the question it does not answer
  (`leaves_out`), and is told to write the query for the part it can answer rather than an easier question silently. A
  query that returns data but leaves something out gets the new status `partial` (level partial, the reason as its
  error) and is not kept as a passing query for the next test.
**Why.** Wine run 4 reported 6 of 7 questions as fully covered. Question 3 passed because the sample data used the
grape variety Cabernet Sauvignon as the subject of `goesWellWith` (domain Wine); without a disjointness axiom the
reasoner does not object and the triple simply makes the grape a wine. Question 4 ("the best wine for grilled meat")
passed on a plain list of wines that go with grilled meat. Applied to run 4's data, the first check drops exactly the
Cabernet triple.
**Alternatives.** A keyword rule for superlatives and comparisons ("best", "most", "than" without ORDER BY or a
filter): English only, while the questions may be in any language, and easy to satisfy with a meaningless ORDER BY.
A second model call that judges each query against its question: an LLM judge again, which DECISIONS 16 and 53 ruled
out, and a further call per test; the self-statement can only lower a result. Inferring types from domain and range
before the check: would make every misused individual fit.
**Revised the same day.** A test from scratch on run 4 with this rule marked four of seven questions partial, two of
them wrongly: "which characteristics should I consider" (the model: nothing says which ones a customer should
consider) and "which characteristics affect suitability" (the model: it does not rank the degree). The rule now names
what `leaves_out` is for - information the question asks for that the query cannot return (a ranking where nothing
records what to rank by, a comparison, a change over time, a missing class or relation) - and what it is not for:
judgements the asker makes from the returned facts, such as what to consider or whether a returned value is good
enough. Questions 3 (now through a wine of the grape variety) and 4 (no ranking) came out as intended. A further
test from scratch with the narrowed rule: 5 full, 2 partial (4: no ranking; 6: no change across vintages), 0 none.
**Also:** a query selects what its question asks for, at that level - a question about kinds returns the kinds,
DISTINCT, and a variable is added only where the question names it. In that test, "which characteristics of a wine
affect its appropriateness for a dish" returned every wine, characteristic, value and dish, and its "expected"
described one such row instead of a list of kinds of characteristics. This changes no level (a query with more
columns still answers), only how readable the queries and their expected answers are.

### 92. The plan gives every class its superclass (a first step towards PLAN.md phase 3d)
**Decision.** Every planned class gets a `parent`: the planned class (in any module) of which it is a kind, or null
for a top class. The plan prompt asks for each class whether it is a kind of something else the ontology needs, and
to plan a broader class where several classes are kinds of one notion the use case needs (rule 5, "no helper
classes", has this as an exception); a value set may stay one class with individuals. The server keeps a parent only
if it is a planned class, and breaks a cycle at the class that closes it. The module prompt shows it ("below: X");
the module keeps it or puts a class of its own between. After the merge, a planned class whose module left the parent
empty (or named a class that does not exist) gets the planned one; a different parent of the module stays and is
reported when the planned one is not above it (`modular_report.hierarchy`: planned, set from the plan, placed
differently). The generation report says when the plan gave no class a superclass.
**Why.** Wine run 4 came out flat: 9 root classes, no subclass (run 3 had a place class over country and region,
and kinds of dishes). Nothing in the plan asked for a hierarchy; each module decided alone, and across modules nobody
did. Planning the superclasses also lets a class of one module sit below a class of another.
**Alternatives.** Building the hierarchy after generation with the hierarchy action: it needs the literature's
broader terms and costs a model call per package (about 0.5 M tokens in the VA project). Forcing the module to keep
the planned parent exactly: it may know a more specific class in between. With literature, phase 3d will add the
inventory's broader terms and taxonomies to the plan prompt; the `parent` field is where they go.

### 93. The generation report is stored in the project
**Decision.** The reports of a generation (modules, planned superclasses, core relations, decided definitions, reuse)
are stored with the project (`generation_report`, with the time of the generation) and shown again in step 8 after a
reload, marked as the report of the last generation without later changes. A new generation replaces it.
**Why.** For wine run 5 the report was not copied before the page was reloaded; the plan's own numbers (superclasses
planned, set from the plan, placed differently by a module) could not be recovered from the ontology.
**Alternatives.** Recomputing the report from the ontology: what the plan proposed and the modules changed is not in
the ontology. Keeping a history of all reports: the run records in the examples serve that purpose.

### 94. A category of X is not a kind of X; a property has at most one inverse
**Decision.**
- **Plan and module rule:** a class whose members are categories, types or grades of something is never placed below
  that thing ("a category of products is not a product"). Prompt only.
- **Inverses:** a property declared as the inverse of a property that already has another inverse loses that
  declaration at the merge; the target's own declaration wins, without one the first claim. The generation report
  lists what was removed, and the structural metrics list such second inverses for every ontology (`inverse_conflicts`,
  shown under the structural problems), so imported and edited ontologies are covered too.
**Why.** In wine run 5 the plan put `DishCategory` below `Dish`, which makes the categories Seafood and GrilledMeat
dishes. And `isVintageOfObservation` (Vintage -> CharacteristicObservation) was declared a second inverse of
`hasVintage`, next to `isVintageOf`: two inverses of one property are equivalent, so every observation linked from a
vintage would become a wine. The reasoner accepts both silently. Applied to run 5's ontology, the check finds exactly
this one case.
**Alternatives.** Recognizing category classes by their names (Category, Type, Kind, Grade): English only and
unreliable. Rejecting a second inverse instead of removing it: the generation has no one to ask; the report says what
was removed.

### 95. A class is an answer when it comes from data; one representation per distinction
**Decision.**
- **CQ test:** a result made only of ontology terms no longer fails by itself. It fails only if the query returns a
  result on the schema alone - the ontology without the statements about its individuals; otherwise the answer
  depends on data (sample data or the ontology's own individuals) and counts. ASK queries are not affected.
- **Plan and module rule:** a distinction is made either by subclasses or by a value set, never both; a module does
  not add a value set for a distinction the planned subclasses already make, or the reverse. Prompt only.
**Why.** In wine run 6, "Is Bordeaux a red or white wine?" was answered with `SELECT ?type WHERE { :Bordeaux a ?type .
VALUES ?type { :RedWine :WhiteWine } }` -> `:RedWine`, which is right, and failed as "answers from the schema" because
the answer is a class. Re-running run 6's queries with the new check passes exactly this one. The same run modelled
colour twice, as `RedWine`/`WhiteWine` and as a `ColorCharacteristic` value set.
**Alternatives.** Allowing classes as answers whenever the query names an individual: a query can name an individual
and still list the schema. Comparing the results with and without data row by row: the simpler test (anything on the
schema alone) already separates the cases seen so far.

### 96. Individuals of the sample data need no type; a regeneration starts the CQ tests afresh (revises 67)
**Decision.**
- **Data individuals:** every IRI in subject or object position of the sample data counts as an individual of the
  data, except as the class of an `rdf:type` statement. A query may name it without it being declared in the
  ontology or typed in the data. Invented classes and properties are still reported as undeclared terms.
- **Regeneration:** a new generation drops the stored CQ and hold-out test results. The next CQ test writes new sample
  data and queries; between iterations of the same generation (feedback rounds, repairs) they are kept and only
  extended, as decided in 67.
**Why.** In wine run 7 two queries failed as "undeclared terms" on `:Napa` and `:grilledMeat`, which the sample data
used as objects of `hasOrigin` and `hasDishCategory` without typing them; with the change both run and are partial
for the reason their author gives (no ranking, no quality). And the kept sample data carried individuals of earlier
generations into a new ontology: run 6's `:NapaZinfandel :hasCharacteristic :Zinfandel` fits run 7 formally, but
Zinfandel is a wine there, so question 1 listed "Wine" as a kind of characteristic; run 6's spelling `:grilledMeat`
had been carried along since. Because a generation restarts the iteration count at 1, the evaluation could also have
taken the previous generation's CQ results as current when the tests were not run again.
**Alternatives.** Keeping the sample data across generations for comparability (67): two generations are different
ontologies, so the comparison is between their own tests; within a generation the reason of 67 still holds. Counting
individuals of the sample data only when typed: the model often leaves the type of an object to the property's range.

### 97. The plan puts the top classes below the upper layer (PLAN.md phase 3b)
**Decision.** The upper layer of step 4 (DECISIONS 68, 69) is used by the generation, switched on by default and
switchable per project in step 4 (`context.use_upper_layer`). The plan receives the upper classes with their
definitions; a class without a planned parent gets the upper class it is a kind of as `parent`, or none if none fits;
the plan does not plan the upper classes themselves. The server accepts an upper class as a planned parent. The
module prompt marks an upper parent ("below: X (upper layer class)") and asks for an upper class as parent of every
class the module adds without a superclass. The merge creates the layer (an existing class of the same name is taken
over, as in the repair action) before the planned parents and the core relations are applied, and removes the upper
classes that end up empty at the end. Core relations may use the upper classes as domain and range. The generation
report lists the upper classes used, those removed as empty and the top classes outside the layer
(`modular_report.upper_layer`). The reasoner checks the disjointness of the layer in the evaluation, as before. The
upper-layer code moved from `improvements.py` to a new module `upper.py`, which generation, core relations and repair
import.
**Why.** The upper layer was configured in step 4 but applied only after generation, by "Group root classes" - in the
VA project about 0.26 M input tokens (PLAN.md). The plan already decides every class's superclass (DECISIONS 92), so
placing the top classes is one more choice in the same call. And the core relations had no class to name for a
relation between many kinds of things except "any" (wine run 4: `Country` and `Region` unconnected because
`hasOrigin` pointed to "any").
**Alternatives.** Letting only the module place its top classes: each module sees only its own classes and would
decide alone, as the hierarchy did before DECISIONS 92. Keeping the repair action as the only way: it stays for
imported and edited ontologies.

### 98. The plan reuses loaded vocabularies (PLAN.md phase 3c)
**Decision.** When vocabularies are loaded in step 7, the plan receives their class terms that match the key notions,
the competency questions and the inventory's concepts (at most 40, the matching of DECISIONS 77), each with the team's
decision for its vocabulary, and a rule:
- a planned class that is a kind of a listed term, or means the same, gets a `link` to it; the merge adds
  `SubClassOf(class, term)` (as the align action does), unless the module already set it;
- a notion that a term of a `use_terms` vocabulary already covers gets no own class: it is listed under "other" as a
  term (`"as": "term"`, `"ref"`), and the module prompt tells the module to use the term directly as parent, domain or
  range.
The server accepts a term only if a loaded vocabulary declares it as a class and the team did not mark the vocabulary
"reference only"; a term in place of a class needs a `use_terms` vocabulary. A term that fails is reported, and a
notion that should have become a term is modelled as a class instead. After generation the references are checked
again (DECISIONS 77). The generation report lists the planned links, the terms used instead of own classes and the
proposals left out (`modular_report.reuse`). "Additional prefixes" moved from step 8 to step 7, next to the
vocabularies. The module-level offer of matching terms (77) stays.
**Why.** Offering terms only while a module is built gave 2 links in the VA run against 13 from the align action
afterwards (DECISIONS 77): the plan decides what each class is, so it is the place to decide what it is a kind of in a
reused vocabulary - as for the upper layer (97).
**Alternatives.** Letting the plan set the vocabulary term as the class's `parent`: the parent is the class's place in
the own hierarchy (92) or the upper layer (97); a vocabulary link is an additional statement, as the align action
makes it. Offering whole vocabularies to the plan: the noise DECISIONS 77 removed from the module prompts.

**Revised by 101:** the plan no longer sees the vocabulary terms; links are decided after planning.

### 99. A reused vocabulary keeps its own prefix; the project's prefix gives way
**Decision.** Loading a vocabulary keeps the prefix its file declares for its namespace (read by rdflib, or from the
file's text where rdflib drops it: `xmlns:` in RDF/XML, `@prefix`/`PREFIX` in Turtle, the JSON-LD `@context`);
without one, the known prefix list, and only then a prefix derived from the namespace. If that prefix is the
project's own prefix (conventions, step 4), the project's prefix changes to `<prefix>-onto` (with a number if taken)
and the page says so; the same when the team types a vocabulary prefix or adds an additional prefix. The project
cannot take a prefix a vocabulary or an additional prefix holds (the conventions are refused with the reason). Two
vocabularies, or a vocabulary and an additional prefix, with the same prefix for different namespaces are refused -
neither may change, so the team removes one.
**Why.** Preparing wine run 11 with the W3C wine ontology: the tool derived the prefix `wine` from its namespace, which
is the project's own prefix, and the project's prefix then silently won in the Turtle header - `vin:` terms would
have resolved to the project's namespace. rdflib also dropped the file's own prefix `vin`, because the file binds the
namespace twice (as default and as `vin`). The team's rule: a reused vocabulary's prefix is its identity in every
other project and document that uses it; the project's prefix is a local choice.
**Alternatives.** Renaming the vocabulary's prefix on a collision: breaks the rule above. Refusing the load until the
team changes its prefix: an extra step for something the tool can do and report.

### 100. Large vocabularies: term lists in their own files, matching through a word index
**Decision.** A vocabulary file may have up to 300 MB (was 20 MB) and up to 500,000 terms (was 4,000, the rest cut
off). The term list of a loaded vocabulary is written to its own file next to the project
(`<project>/vocabularies/<prefix>.json`); the project keeps name, namespace, source, counts and the file's path.
Term lists are read through one accessor that caches them, with a name directory and a word index, as long as the file
does not change; projects that hold their term lists inline (from before) work as they are. The search for matching
terms (the plan's and the modules' reuse, the align candidates) only scores terms that share a word or a concept key
with what it looks for - the same rules as before, which can only match on a shared word or key. Export and import of
a project carry the term files. Downloads may take 120 s; the page says a large vocabulary can take a minute.
**Why.** The team asked for large ontologies such as FoodOn (40 MB, 40,056 classes) to be importable. Measured: download
4 s, parsing 15-28 s, term extraction 1 s; the term list is 8 MB of JSON. Inside the project file, those 8 MB would
be written again after every change of the project; in their own file the project entry is 193 bytes. Scoring every
term against every concept would have been 40,000 terms per concept; through the index the first search takes 1.7 s
(building the index), later ones 0.3 s, the align candidates 0.1 s.
**Alternatives.** A database for the terms: more machinery than one JSON file per vocabulary. Keeping only the terms
that match the project: the project changes, and a later concept would find nothing. Parsing with a faster library
than rdflib: parsing is a one-off of half a minute per vocabulary.

### 101. Vocabulary links are decided after planning, per planned class (revises 98)
**Decision.** The plan no longer receives terms of loaded vocabularies. After planning, the server looks for the most
similar class terms for every planned class (the matching of the align action: same name or label, head word, word
overlap; at most 4 per class; vocabularies marked "reference only" are left out). If any class has candidates, one
small model call decides per class: `subclass` (every instance is an instance of the term), `equivalent` (the same
instances) or `use` (the term replaces the planned class - only for "use terms directly" vocabularies; the class is
dropped from the plan and the module uses the term, and its planned subclasses get the term as superclass) - or no
link. The server accepts only candidates of that class; `use` for an "align" vocabulary becomes `subclass`, and for a
key notion's class or a decided class `equivalent`, as those stay own classes. The merge writes SubClassOf or
EquivalentClasses; the report lists the links ("=" same meaning, "->" a kind of), the terms used instead of classes,
what was left out and how many planned classes had candidates. If the call fails, generation continues without links.
**Why.** Wine run 11 (DECISIONS 98 with the W3C wine ontology loaded): the plan saw 40 matching terms and planned most
of them as classes of its own - 35 instead of 10-11, same-named copies such as `IceWine` and `TexasWine` that the use
case does not ask for; and a same-named copy could only be linked as a subclass. Planning first keeps the plan about
the project; candidates per planned class keep the choice local, as in the align action. With run 10's classes and the
W3C vocabulary the call is about 400 tokens (6 classes with candidates).
**Alternatives.** A stricter selection of terms for the plan prompt plus a rule "terms are not classes": the plan
would still see a list of terms to copy from. Letting the modules link (DECISIONS 77): 2 links in the VA run.

### 102. Follow-ups of wine run 12: careful equivalences, remembered "no link", inverses only where needed
**Decision.**
- **Equivalent links:** "equivalent" only if the term's definition says the same as the planned class, with the same
  scope; a broader term gives "subclass", and so does doubt.
- **"No link" is remembered:** the link call lists the classes with candidates but no fitting term under "none" with a
  reason; they are stored as decisions of the align action (the store of DECISIONS 76, moved to `project.py` so the
  generation can write it), so "Align" in the evaluation does not offer them again. The evaluation lists them with
  their reason, and they can be reconsidered as before.
- **Inverses:** the module prompt and the OOPS! guidance no longer ask for inverses "where meaningful" or for
  "consistent inverses", but for an inverse only where a competency question or the data need both directions; a
  query can follow a property backwards. A missing inverse is OOPS! P13, a minor pitfall the tool does not repair.
**Why.** In run 12 all four links were equivalences, two of them broader than the planned class (`WineRegion =
vin:Region`, the W3C Region being any region). The evaluation offered "Align with vin" for 6 classes, among them those
the link step had just declined. And every module relation came with an inverse (8 pairs, 12 top-level relations) -
an observation since run 1; the prompts themselves asked for inverses.
**Alternatives.** Allowing only subclass links: a class that means exactly the vocabulary's class could not say so.
Removing inverses after generation: a question may need both directions; the model sees the questions, the merge
does not.

### 103. The plan receives the literature's broader terms and taxonomies (PLAN.md phase 3d)
**Decision.** With a concept inventory, the plan's concept listing shows each concept's broader terms as the sources
state them - as concept ids where the broader term is itself a concept of the inventory, otherwise as text; at most
three, the most frequent first. A new block lists the sources' taxonomies whose root or at least two categories are
inventory concepts (the selection of "Build hierarchy"), categories mapped to concept ids, those with the most mapped
categories first, at most 25,000 characters; a taxonomy whose root and mapped categories equal one already listed (the
same taxonomy from another paper) is shown once. The plan rule asks to use them for each class's `parent` and to leave
out relations the sources state loosely (a part, a phase, a related topic), listing them under `hierarchy_declined`
with the reason. Those are stored as decisions of "Build hierarchy" (its key: "A is a kind of B", normalized), so the
repair does not propose them again; the evaluation lists them and they can be reconsidered. The generation report
counts them.
**Why.** The literature's hierarchy was used only after generation: "Build hierarchy" cost about 0.5 M input tokens in
the VA project (PLAN.md), for relations the inventory knew before planning - 1,167 of 1,395 VA concepts carry broader
terms, and the corpus has 329 taxonomies. The plan already sets every class's superclass (DECISIONS 92); now it does so
with the sources' statements. For the VA project the plan prompt grows from about 90,000 to 144,000 characters
(roughly 36k tokens), with 181 distinct taxonomies.
**Alternatives.** Showing the broader terms only as text: the plan would have to match them to concepts itself; ids
make the relation exact where it exists. Leaving taxonomies to the repair: they are what gives the VA ontology its
depth (task, interaction and encoding taxonomies).
**Fixed with 104:** the format hint for `hierarchy_declined` reached the model with doubled braces (`{{ }}`), because it
is inserted as a value, not as part of the template.

### 104. Every central concept is planned or excluded with a reason (PLAN.md phase 3e)
**Decision.** With a concept inventory, the plan rule says that every concept with two or more sources (the central
concepts, as in the evaluation) must be accounted for: in a class's concepts, under "other" (property or individual),
or under `excluded` with a reason. Before the modules are generated the server checks the plan. Central concepts the
team or "Add missing central concepts" declined earlier count as excluded with that reason. The rest go to a
completion call (60 per call) that places each one - in a planned class of the same meaning, a new class with its
module and planned or upper-layer superclass, as a property or individual - or excludes it with a reason; module and
class names are checked against the plan, and a new class's superclass must be planned or upper. What is still without
a place is reported; the generation goes on. Exclusions are stored as decisions of "Add missing central concepts"
(`gap_decisions`, keyed by the concept), so the repair does not propose them again; the evaluation lists them as
"deliberately not modelled", and they can be reconsidered. The generation report shows how many central concepts the
plan placed, the completion added or excluded, earlier decisions covered, and which are still open.
**Why.** "Add missing central concepts" cost about 1 M input tokens in the VA project (PLAN.md), for concepts the
plan could have placed: the old rule let the plan leave out concepts "out of scope or specific to one paper" without
saying which. Now every leave-out has a reason the team can check, and the completion handles only the gap, not the
whole inventory.
**Alternatives.** Refusing a plan with gaps and planning again: a second full plan call (36k tokens in VA) to fill a
few gaps. Forcing every central concept into a class: some are rightly properties, individuals or out of scope.

---

### 105. Vocabulary links by concept labels, and a second link call after the modules (follow-up of VA run 1)
**Decision.** Two changes to the links of DECISIONS 101. (1) The candidates for a planned class are searched not only
by its name but also by the labels and variants of the inventory concepts it represents (up to 8 labels; per term the
best match counts); the align action also uses a class's linked inventory concepts. (2) After the modules are merged,
a second small call links what the first could not see: the upper-layer classes, the classes a module added on its
own, and all properties, including the core relations. Its candidates are those of the align action (same matching,
nothing already linked or decided, no "reference only" vocabulary); the listing shows each property's domain and range
and the candidate's. The model answers per term `subclass` or `equivalent` (classes), `subproperty` (properties), or
none with a reason; the server accepts only candidates of that term and applies the links with the edit operations,
so a subproperty whose domain or range does not lie within the vocabulary property's is refused (as in the align
action). Terms with no fitting candidate become decisions of the align action; refused links stay open for it. The
generation report lists the links ("<" a subproperty of), the refused ones and the declined count. If a call fails,
generation continues; "Align" can add the links.
**Why.** VA run 1 (`examples/va/RUNS.md`) had 6 links to reused vocabularies against the baseline's 13. The first call
found candidates for only 8 of 219 planned classes, since many class names differ from the literature's terms; the
upper class `Agent` (-> `prov:Agent`) and module properties such as `used`, `wasDerivedFrom` or `startsAt` were never
offered - the baseline's links were mostly properties (10 of 13). On run 1's ontology the labels double the classes
with candidates (9 -> 19), and the second call would see 30 terms (13 classes, 17 properties): a few thousand tokens.
**Alternatives.** Offering the vocabulary properties to the modules: the modules copied vocabulary terms before
(wine run 11) and could not be checked per link. Running the align action automatically: it sends the ontology listing
with each batch (the costly part of the repairs). A reasoner check per batch, as in the align action, which reverts
links that make classes unsatisfiable: it would run Java during generation; the evaluation's reasoner check reports
such classes, and the loaded vocabularies so far declare few disjoint classes.
**Fixed with 105:** in VA run 2 two module properties had the range "(any)", copied from the core relations' listing;
the Turtle export wrote `:(any)`, which no parser reads. The merge now clears a domain or range that is no name ("any",
"(any)", free text): no domain or range is what the module meant. In VA run 3b a module wrote a restriction as a
class name (`SubClassOf(UsefulAI, "isPartOf some HumanCenteredAI")`); the merge now leaves out axioms whose classes
are no names and lists them in the generation report - restrictions come with PLAN.md phase 5.

### 106. A vocabulary term replaces a class only with the same meaning and the same name (revises 101)
**Decision.** In the link call after planning, `use` (the term instead of the planned class) now requires that the
term means the same as the class, as for `equivalent`; a broader term gives `subclass`. The server also checks it:
a replacement is accepted only if the term has the same name or label as the class or one of its concepts (the
candidate matching's strongest score); otherwise the class stays and is linked as a subclass of the term, and the
report lists this under the terms left out.
**Why.** VA run 2 (`examples/va/RUNS.md`): `TaskTarget` and `AnnotationActivity` disappeared in favour of
`prov:Entity` and `prov:Activity`. The candidates came from a head word ("data entity", "...Activity"), the rule did
not ask for the same meaning, and a replaced class takes its concepts and its place in the hierarchy with it. A
same-named term (run 1: `Dataset -> dcat:Dataset`) still replaces the class.
**Alternatives.** Only the prompt rule: the model chose `use` for a broader term before, and a wrong replacement
loses a class, whereas a subclass link to a term that turns out equivalent loses nothing. Dropping `use` altogether:
"use terms directly" would then mean nothing in generation.

### 107. A separate check decides whether a partial answer's gap is asked for
**Decision.** After the CQ tests (and the hold-out tests), every answer its author marked as partial goes to one short
call that sees only the question, the query, the first five result rows and the stated gap - not the ontology and not
the sample data. It classifies the gap as `missing` (information the question itself asks for: it names it, or it is
what the which/what/how asks for) or `beyond` (a judgement about the returned facts, a proof or certainty the
question does not ask for, more detail than asked, or information the answer contains in another form). `beyond`
makes the answer full; the author's remark and the check's reason stay in the report. When in doubt the check answers
`missing`; an unanswered or unclear item stays partial, and if the call fails all stay partial and the report says
so. Reused passing queries are not checked again.
**Why.** VA runs 3a-3c (`examples/va/RUNS.md`): three generations of one configuration gave 8, 4 and 2 fully answered
competency questions, and most partial answers stated judgements - "whether the insight is sufficiently justified to
be accepted as knowledge", "how much they help an audience understand", "not that the interaction caused the
insight". The rule of DECISIONS 91 is in the prompt, but the model that writes the query also writes the gap and
over-reports it; a reviewer with only the question and the answer in view judges the question's wording, not the
work behind it. The test's own noise was larger than the differences it should measure.
**Alternatives.** A sharper rule in the test prompt: the rule exists and is ignored. Ignoring `leaves_out` altogether:
a list where the question asks for the best one would count as full again (wine run 4). Letting the check see the
ontology: a longer call that would start judging the modelling instead of the question.

### 108. Model calls wait out a rate limit and have a broken JSON answer repaired
**Decision.** (1) When the provider reports a rate limit (429), a call waits and tries again - as long as the
provider's `Retry-After` header says (at most 120 s), otherwise 15, 30 and 60 s - and reports the limit only after
the third wait. A used-up quota (`insufficient_quota`) is reported at once. The SDKs' own short retries stay. (2) An
answer that is no valid JSON, even after the existing relaxed parsing, goes to one short repair call with only that
answer and the parser error: "return exactly the same content as valid JSON". If the repair fails too, the original
error stands. It is counted as its own step ("... (JSON repair)"). All calls that expect JSON use it: generation
(plan, completion, links, modules), CQ and hold-out tests and their check, paper cards, inventory, definitions and the
smaller MOMo steps. The completion and the two link calls, which generation can do without, now also continue when
their answer stays unreadable.
**Why.** VA runs 3a-3c: 3b's first generation stopped at a token rate limit right after 3a's tests; 3b's first
retest lost its hold-out test to a `JSONDecodeError`, its second the check of the hold-out answers to a 429. Each
cost a re-run of 50-260k tokens, and a measurement series of several runs in a row reaches a per-minute limit
regularly. A broken answer is almost always a quoting error in otherwise complete content; repairing it costs about
the answer's size, repeating the call the whole prompt again.
**Alternatives.** Repeating the call with the same prompt: the full input again (51k for the hold-out tests), and a
new answer instead of the one that was only badly quoted. Waiting longer: a per-period quota that is exhausted for
hours should fail visibly rather than keep a request open. Throttling the parallel module calls in advance: the limits
differ by provider and are not known to the tool.
**Revised in the review before VA runs 4a-4c:** waiting only for a real rate limit (HTTP 429 or the SDK's
RateLimitError), not for 400/403 errors that are reported as a limit because their text says "limit" or "exceeded"
(a too long input does not get shorter by waiting); and not when the provider asks for more than 120 s (a quota for
the period) - then the limit is reported at once instead of after three futile waits.
**Fixed after the external code review of 2026-10-29 (before VA runs 4a-4c):** a truncated answer in an optional step
(vocabulary links, plan completion, hierarchy and core relations after the modules) no longer aborts the whole
generation; a failed vocabulary-link call is no longer stored as "no link" for every candidate class (they are offered
again after the modules and by "Align"); a new generation drops the previous evaluation (its iteration 1 looked
current); the page saves key notions and competency questions before generating; and one session whose text cannot be
written as UTF-8 (a lone surrogate, e.g. from PDF text) is saved as an ASCII escape instead of stopping every later save.

### 109. One correction round for a query without result on its own sample data
**Decision.** A CQ or hold-out test whose query parses, uses only declared terms and still returns nothing on the
sample data (or whose ASK is false) gets one correction round, after the tests and before the check of partial
answers (107). One call receives, per such test, the question, the query and the ontology terms the query uses with
their kind, domain and range or superclasses, plus the current sample data and the triples the server dropped - not
the ontology itself. It may add sample triples and correct the query; the corrected query must still answer the whole
question or state what it leaves out. The server checks the added triples with the same guards as the first sample
data (declared terms, no schema statements, no type conflicts), adds them, and runs all queries of this test run
again. The report notes for each such test that a correction round took place and whether it rewrote the query. If
the call fails, the tests stay failed and the report says so.
**Why.** VA runs 3a-3c and their retests: questions such as "How can I trace an insight back through interactions,
visualization states, reasoning, and data?" failed with "No result on the sample data" - the model wrote a long chain
of joins and sample data that miss one link of it. Nothing was missing in the ontology; the question still counted as
partial, and which question failed varied from test to test. A correction with the query and the terms in view
costs a few thousand tokens; a new test run costs 50k.
**Alternatives.** Rewriting the whole test (the full prompt again, and new queries for every question). Counting such
failures as full: an empty result can also mean that the ontology cannot connect the parts. A correction round that
also sees the ontology: it would be the full prompt again.
**Fixed in the review before VA runs 4a-4c:** the sample data of each correction is read on its own; one correction
with invalid Turtle no longer discards the triples of all others.

### 110. Taxonomy categories and concepts of the questions are not excluded as "too specific" (revises 104)
**Decision.** The plan rule for central concepts (104) adds: a category of one of the literature's taxonomies, or a
concept a competency question names, is not excluded for being narrow, specific or part of one framework - it becomes
a subclass, or an individual of the class for its taxonomy where the categories are fine-grained values. The server
checks it: such concepts the plan still excludes (a taxonomy category by label or variant; a question naming the
label or a variant as a word of at least four letters that is not a stop word) go to the existing completion call,
marked REVIEW with the plan's reason and why they are protected. There they may stay excluded only as out of scope
for the use case or the same as another concept; what the call does not place keeps the plan's reason. Concepts the
team or "Add missing central concepts" decided on earlier are not reviewed. The generation report gives the number of
reviewed exclusions and those kept.
**Why.** VA runs 1, 2 and 3a-3c excluded 24-70 central concepts per run, the same configuration giving 24 in one run
and 68 in another. About half were categories of the literature's taxonomies, excluded as "a narrowly named event in
one uncertainty taxonomy" or "a stage of one named design-study framework" - the literature (two or more sources)
treats them as a classification the domain uses, and the competency questions ask for exactly such distinctions
("what kinds of uncertainty are involved"). "view", which a competency question names, was excluded in one run. The
exclusions that recur in all five runs (generic research vocabulary such as "method", "taxonomy", "pitfall") are
mostly right and stay possible with a reason.
**Alternatives.** Forbidding the exclusion of taxonomy categories: some taxonomies are one paper's method (design-study
stages) and are rightly out of scope - the review asks for that reason instead. Only the prompt rule: it is the
plan's longest prompt, and its exclusions varied most. Reviewing every exclusion: about 50 per run, most of them right.
**Fixed in the review before VA runs 4a-4c:** a category written as "group: category" counts by its last part, as in
the hierarchy measure.

### 111. The literature's broader terms are decided after the modules; declined ones are reported apart
**Decision.** (1) After the modules (and the vocabulary links), the server lists the broader/narrower relations of the
literature between two classes of the generated ontology that the hierarchy does not realize - leaving out those the
plan or the team declined earlier. One short call per 60 relations sees each relation with both classes' current
superclass and description and decides `kind_of` or `decline` with a reason. `kind_of` sets the broader class as
superclass if the class has none or only an upper-layer class above it, otherwise adds a SubClassOf axiom (a second
superclass); the server refuses it if the two would fall under disjoint classes, and the edit operations refuse
cycles. Declined relations become decisions of "Build hierarchy" and are not asked again. The generation report lists
the relations, those added, declined and refused. (2) The evaluation reports relations declined with a reason apart:
`realized_pct` keeps its denominator (comparable with earlier evaluations), `realized_or_declined_pct` counts them
like decided central concepts.
**Why.** VA runs 1, 2 and 3a-3c realized 48-65 % of the literature's relations (baseline after "Build hierarchy":
64.7 %), and of 118 distinct unrealized relations 53 were missing in only one run: whether the plan adopted a broader
term was largely chance. 5-10 per run were declined by the plan with a good reason ("interaction is a process, not
a kind of insight") and still counted as missing. The plan sees broader terms only for concepts it lists; classes the
completion or the modules add, and relations whose two ends end up in different modules, it cannot settle - after the
modules all classes exist. The call costs a few thousand tokens; "Build hierarchy" sent the ontology listing with
every package.
**Alternatives.** Adopting every broader term automatically: the sources use "broader" loosely (a part, a step, a
related notion), and a second superclass of another kind makes a class mean two things. Only fixing the measure: it
would hide that half of the relations are neither realized nor decided.
**Fixed in the review before VA runs 4a-4c:** two broader terms of one class in the same call: the first set the
superclass and the second overwrote it, while the report listed both - now the second becomes a SubClassOf axiom.
An upper-layer class is never put below a domain class.

### 112. Relations without a core relation are offered the core relations again after the modules
**Decision.** After the modules, the vocabulary links and the hierarchy step, every module relation that still has no
core relation above it - and that the team or "Consolidate properties" has not decided on - goes to a short call
(40 per call) with the list of core relations and, per relation, the candidates: the core relations and their
inverses whose domain and range contain the relation's own (by the class hierarchy including SubClassOf axioms),
specific ones first. The model answers `below` with one candidate (every statement of the relation is also one of the
core relation) or `none` with a reason (a connection of its own kind). The server accepts only candidates, applies the
superproperty with the edit operations (which check domain and range again) and stores `none` as a decision of
"Consolidate properties". The generation report lists the relations placed, kept and refused; the core-relation
figures of the report are recomputed afterwards.
**Why.** VA runs 3a-3c had 85-99 top-level relations (target about 70; baseline 112): the 41 core relations plus
44-58 module relations below none of them - `hasTaskInput` not below `usesAsInput`, `hasModelOutput` not below
`produces`, `hasParentItem` not below `hasPart`. 36 of the 41 core relations were never used as a superproperty. The
modules have the rule (DECISIONS 90) but see 41 core relations next to their own material; with the relation and its
fitting candidates side by side the decision is a small one, as in the links (105) and the hierarchy (111).
**Alternatives.** A stronger module rule: the modules already get one, and their prompts are the longest. Placing
relations by domain and range alone: 23 of the 41 core relations relate "any" to "any" and fit almost everything -
the meaning has to decide. Fewer core relations: they are the team's approved vocabulary; how many it should have is
the team's choice in step 7.

### 113. An unreachable OOPS! service fails fast and is not tried again for ten minutes
**Decision.** The OOPS! request gets separate time limits: 10 s to connect, 120 s for the answer. If no connection can
be made, the report says "The OOPS! service (oops.linkeddata.es) cannot be reached - it is down or blocked by your
network", and further OOPS! checks of the same server process report the same at once for ten minutes, with the time
of the next attempt. A service that accepts the connection but answers too slowly is reported as a timeout and tried
again next time. Neither counts as a pitfall; the OOPS! fix is skipped.
**Why.** In wine run 13 and VA runs 1, 3a and 3c the OOPS! check ended with "did not respond within 60 s". A test on
2026-10-28: oops.linkeddata.es resolves, but no TCP connection to port 443 or 80 is accepted, while other sites answer
- the service is down or blocked. Each check waited the full 60 s, and generation, feedback and the OOPS! repair call
it, the fix twice; the message did not say that nothing could be checked.
**Alternatives.** Dropping OOPS! when it fails: it is the only external pitfall scanner, and it may come back.
Checking reachability before each call: an extra request, and a failed connection says the same.

### 114. Documentation export: one document, a chapter per module, Markdown or HTML (PLAN.md phase 6)
**Decision.** Step 8 offers "📄 Documentation (HTML)" and "(Markdown)". The server builds one document without a
model call from what the project holds: an overview (name, namespace, summary, license, counts, reused vocabularies,
the competency questions with their last test result, the key figures of the last evaluation), the upper layer and
the core relations, then one chapter per module - its documentation, a class diagram (Mermaid: inheritance including
superclasses in other modules, drawn dashed, and the relations between classes, left to right), the class hierarchy
as a tree, every class with labels, definition, superclasses (parent and SubClassOf axioms), equivalent classes,
individuals, the inventory concepts it represents, its sources and up to three definitions from the literature (term,
definition, page, and the quote if it was verified; verified ones first), the module's properties and axioms - and
for the review the central concepts deliberately not modelled and the broader terms not adopted, each with its
reason, and the references. The HTML file is self-contained (styles inline, light and dark); only the diagrams need
Mermaid from a CDN and otherwise show their source. The Markdown file renders on GitHub and in most editors,
diagrams included.
**Why.** The expert review and the paper need the ontology in a readable form with its evidence: which source defines
a class how, and which concepts and relations were left out for which reason - the Turtle file holds the definitions
and sources, but not the literature's own definitions with page and quote, nor the decisions. One document with
chapters keeps the cross-module superclasses and the review sections together; for VA run 3a it is about 360 KB of
Markdown, built in 0.04 s.
**Alternatives.** One file per module: the upper layer, the core relations, the decisions and the references would be
repeated or split off, and links between modules break. Diagrams as images drawn on the server: a layout library as
a new dependency; Mermaid is text, so the Markdown stays diffable. A model call that writes the documentation: the
content is already there, and the review needs it as recorded, not paraphrased.

### 115. Step 8 split into 8 Generate and 9 Evaluate & Refine; repair tools open where a measurement asks for them (PLAN.md phase 4)
**Decision.** Step 8 keeps what the generation produces: the readiness hints, the generate button, the generation
report, the token usage and the ontology view (statistics, tables, graph, Turtle), plus "Continue → Evaluate &
Refine". The new step 9 holds everything that tests, changes or exports the ontology: a summary line, the diff view,
the OOPS! report, the CQ tests, the evaluation, the **repair tools**, the export (Turtle, documentation), feedback,
the Turtle editor and SHACL. The repair tools - the improvement actions with their runs and the core-relation
review - are a collapsed section of their own instead of a part of the evaluation box. Each tool stands next to the
measurement that made it appear ("93 central concepts of the literature neither modelled nor decided", "82 root
classes outside an upper layer"), and the section opens by itself when the evaluation finds such a gap or when the
ontology was loaded from a file (remembered in the project); a running tool opens it as well. "Load Existing
Ontology" (step 2) now shows the loaded ontology (it did not before) and leads to step 9. The Turtle editor says what
saving loses: the modules, the sources and the links to the concept inventory. Panel ids stay as they are (step 8 is
still `panel6`), so saved projects open in the same step.
**Why.** After phase 3 generation does what the repairs did - central concepts, hierarchy, upper layer, links, core
relations - so the repairs are for gaps a measurement shows, not a step every ontology goes through; a separate
"improve" step would suggest that (PLAN.md). One step 8 with generation, evaluation, repairs, feedback and export had
grown to a page where the result of a generation and the tools for an existing ontology were hard to tell apart.
**Alternatives.** Three steps (generate, improve, refine): see above. Showing the repair tools always open: they
would invite running them without a gap. Hiding them without a gap: they stay available, collapsed, with "the
evaluation found no gap these tools address".

### 116. The JavaScript of the page in one file per step (PLAN.md phase 4)
**Decision.** The script of `index.html` (about 3,800 lines) moved unchanged into `js/`: `core.js` (state, navigation,
MOMo hints, token usage, helpers), `project.js` (start, saving, restoring, project picker, export and import), one
file per step from `step1-llm.js` to `step9-refine.js`, and `main.js`, which loads last and holds the only two
statements that run at load (the input listeners and `init()`). They stay classic scripts in that order: every
function remains global, so the `onclick` handlers in the markup and in rendered HTML keep working, and no build step
is needed. The server serves the folder at `/js`. The split was checked line by line (every line of the old script
is in exactly one file), every handler name used in the markup or the scripts resolves to a function, and the
walk-through of phase 4 (all steps of a new project, the VA project, loading an ontology) ran without errors.
**Why.** One file of 5,100 lines mixed markup, styles and the code of nine steps; a change to step 9 meant searching
through all of them, and two people could not work on different steps without conflicts.
**Alternatives.** ES modules: imports and exports for 217 functions, and the inline handlers would no longer reach
them without assigning each to `window`. A bundler: a build step the tool deliberately does not have. Keeping the
order of the old script: the sections were interleaved (step 1's code stood after step 7's); grouping them by step
is safe because no top-level constant refers to another name and only `main.js` runs code at load.

### 117. Fixes from the external code review of 2026-10-29
**Decision.** An external review of the whole repository at 25738bc listed 15 top and about 30 further findings; each
was checked again independently against the code (two checkers per top finding, one per further finding) and all
were confirmed, though several overstated how likely they are. Fixed before VA runs 4a-4c, because they can change a
generation or the measured figures:
- a failed vocabulary-link call is no longer stored as "no link"; a truncated answer skips only an optional step; a
  new generation drops the previous evaluation; the page saves key notions and questions before generating; a session
  that cannot be written as UTF-8 no longer stops all saving (noted under DECISIONS 108);
- the hierarchy step checks disjointness together with the edges already accepted in the same call and for all
  subclasses of the narrower class (DECISIONS 111 checked only the state before the call and only the class itself);
- the edit operations refuse cycles through SubClassOf axioms too, not only through the parent chain (as DECISIONS 44
  and 111 say they do);
- a class name a module wrote differently (`Wine_Region` -> `WineRegion`) keeps its references (parents, domains,
  ranges, individuals, axioms) instead of getting a placeholder; umlauts in class names are transliterated
  (`Qualitätswein` -> `Qualitaetswein`, before `QualitTswein`); a planned class renamed by a decided definition keeps
  its subclasses;
- list-valued answers (several parents, a union as domain, grouped concepts) take their first name instead of crashing
  the generation;
- security: no CORS - the page is same-origin, and with `allow_origins=["*"]` any web page open in the same browser
  could read and overwrite the projects; `python app.py` binds to 127.0.0.1 like start.bat; `escHtml` escapes quotes
  too, and the ontology tables escape names and descriptions (a loaded OWL file could run script in the page).
**Why.** The fixes before the runs protect a measurement series of about 1 M tokens; the security fixes are one line
each. **Postponed** until after the runs, with the review's other findings: the Turtle editor's round trip (its save
loses axioms and external references, not only modules and sources - medium effort), the plural handling of the
concept key (it changes the coverage measure, so all runs would be re-evaluated together), SHACL export, stale CQ
reports after loading or SHACL adjustment, the reasoner's JVM on timeout, and the frontend details. The GitHub token
in `github_push.bat` and the hard-coded KI:connect key are for the owner to revoke and rotate.
**Alternatives.** Fixing everything at once: the Turtle editor and the concept key are larger changes that would
mix with the measurement; doing them after the runs keeps 4a-4c comparable with 3a-3c on everything but steps 1-4.

### 118. The hierarchy target is "realized or declined", not "realized"
**Decision.** The success measure for the literature's broader/narrower relations (PLAN.md phase 3) is the share
realized **or declined with a reason**, not the realized share alone. For the VA baseline that is 93.5 % (99 realized,
44 declined by "Build hierarchy", of 153); runs 4a-4c reach 98.0-98.8 %. The evaluation keeps reporting both.
**Why.** The realized share compares different things: a relation counts only when both of its terms are classes of
the ontology at hand, and each generation has a different set of classes. Of the 99 relations the baseline realizes,
56-63 do not exist at all in 4a, 4b or 4c; of those that exist in both, the runs realize 30-36, decline 5-8 with a
reason and leave 0-2 open, and each run realizes 49-64 relations the baseline does not have. The hierarchy step after
the modules (DECISIONS 111) adds few superclasses because most stated broader terms are single-source and loose; what
it declines it declines with a reason. Seven of the ten baseline relations a run declines follow one modelling choice -
an executed interaction is not placed below the interaction technique that specifies it - which the expert review
should look at, not the measure.
**Alternatives.** Keeping "realized" and pushing the step to adopt more superclasses: it would adopt loose relations
("Goal is a kind of Axis") to reach a number that depends on which classes happen to exist. Comparing only the
relations both ontologies have: about 40 per run, too few and still dependent on the class set.

### 119. Core relations: general relations to the upper layer, and feedback after a generation
**Decision.** (1) The proposal of core relations (step 7) gets two rules: a core relation must be general enough that
relations of several modules can go below it - a relation between two specific classes that only one module uses
stays in that module; and, when the upper layer is used, one general relation with an upper class as range wherever
relations of several modules will point to its instances, in particular "has quality" (range Quality) for the
characteristics, levels, degrees and scopes of things. Such a relation is not a catch-all in the sense of the earlier
rule: its range says what it collects, and the module relations below it keep their meaning. (2) After a generation,
step 7 shows next to the approved core relations which of them have no relation of the modules below them, and the
relations below no core relation grouped by the nearest upper class their range lies below (groups of three or
more), with the hint to add a general relation and generate again. The server computes it from the ontology
(`GET /api/properties/usage`); no model call.
**Why.** VA runs 4a-4c kept 36-61 relations below no core relation, and the step after the modules (DECISIONS 112)
placed only 15-28: its reasons were mostly right ("task scope characterizes a task's breadth rather than assigning it
to a category"). The kept relations pointed to information objects (92), qualities (25), agents (13) and processes
(10) - and no core relation had Quality as range. At the same time 20 of the 41 core relations were below no relation
in any run (`hasField`, `recordsValue`, `presents`, ...): narrow relations count as top-level like any other. With 41
core relations, all top-level, the target of about 70 leaves room for only about 30 relations of their own across ten
modules - the lever is the vocabulary, not the placement.
**Alternatives.** A looser placement rule ("below a core relation if domain and range fit"): relations of a different
kind would be placed below unrelated ones, and queries over the core relation would return them. Adding "has quality"
automatically: the vocabulary is the team's decision in step 7. Removing unused core relations automatically: a general
one may be used directly between instances, which the schema does not show.

### 120. The Turtle editor and "Load existing ontology" read back everything the export writes
**Decision.** Reading a Turtle file into the project (the editor's Save & Apply, Load existing ontology) keeps what
the export writes: modules (`opla:Module` with label, key notion, documentation and pattern) and which module a class
or property belongs to (`opla:isNativeTo`), sources (`dcterms:source`), `rdfs:seeAlso`, axioms (`owl:AllDisjointClasses`
and `owl:disjointWith`, `owl:equivalentClass`, further named superclasses), and external terms with their prefix
(`schema:Thing`, `xsd:string`, `prov:used`) instead of only the local name. Only terms of the own namespace become
classes, properties and individuals - each once; module nodes and annotation properties no longer become individuals.
The namespace stays as declared (a slash namespace is no longer turned into `#`). Prefixes of a loaded file that the
project does not know are added to its prefixes, and the file is parsed without rdflib's own prefix bindings, which
renamed declared prefixes like `geo` or `schema`. When saving from the editor, what Turtle does not carry comes from the
previous version by name: the inventory concepts and the upper-layer marking of each class, the explanation and module
of each axiom, the order of the modules, which of several superclasses is the main one (also "none" for an upper class).
The server answers with its own export, which the editor then shows. Loading a file also drops the previous CQ
reports and evaluation (review finding T12).
**Why.** Code-review finding T1: one click on Save & Apply - even without an edit - removed all axioms and modules,
turned external parents into own classes or self-loops, made `xsd:string` an own term, changed slash namespaces and
duplicated individuals, while the page kept showing the old Turtle. The warning added in DECISIONS 115 named only part
of it. Now run 4a's ontology (278 classes, 160 properties, 26 axioms, 12 modules) goes through export and Save & Apply
without a single difference, and saving the result again changes nothing.
**Alternatives.** Disabling Save & Apply: the editor is the only way to make a change the edit operations cannot
express. Keeping the warning: the damage was silent and permanent. Storing the tool's extra fields as annotations in the
Turtle: a foreign file would still lack them, and the export would grow for a round trip only the editor needs.

### 121. Singular and plural get one concept key; stored decisions are migrated
**Decision.** The concept key (`concept_key`, which decides which terms count as one concept and under which key the
team's decisions are stored) now reduces singular and plural of the last word to the same form: irregular plurals come
from a short table (analyses, hypotheses, axes, indices, criteria, ...), words whose singular ends in s (bias, status,
focus, lens, ...) keep it and lose "-es" in the plural, and "-ics" is no longer exempt (metrics -> metric; the key is
never shown, so "analytics" -> "analytic" is harmless). Ordinary words are unchanged (idea, case, phase, use, cause).
Stored decisions are migrated once per project - when the server starts and when a project file is imported, marked by
`concept_key_version`: the excluded concepts (`gap_decisions`, stored as key -> reason) through the inventory's
labels and variants, the decided definitions by the concept each of them names.
**Why.** Code-review finding T11: metric/metrics, topic/topics, bias/biases ("bia"/"biase"), analysis/analyses and
axis/axes got different keys, so a concept named in the plural in one paper and in the singular in another could count
as two, and a decision taken on one form did not apply to the other. Effect on the VA runs, recomputed for the baseline
and runs 1-4c: none - central concepts as classes, represented, missing, and the hierarchy figures are the same with
both keys, so the comparisons stand. In run 4a's inventory 38 of 2,198 terms get a new key, and two pairs of
concepts would merge on the next rebuild of the inventory (Hypothesis/Hypotheses, aesthetic/aesthetics).
**Alternatives.** A stemmer (Porter, Snowball): it also cuts derivations (visualization -> visual), which would merge
concepts that differ. Keeping the old key and listing exceptions: the asymmetry was in the rules, not in single words.
Not migrating: decisions stored under the old key would silently stop applying.

### 122. The remaining findings of the code review
**Decision.** The findings postponed in DECISIONS 117 that 118-121 did not cover are fixed:
- *CQ tests and SHACL:* a COUNT that returns 0 is no result (before, a query counting nothing "passed"); prefixes rdflib
  binds itself (geo, schema, ...) keep the namespace the ontology declares; an item number from the model ("0", "2")
  is looked up safely (`nth`; "0" used to pick the last item). The SHACL export writes valid Turtle with several
  constraints per class, refuses counts that are not whole numbers (400 instead of 500), validates its output, and an
  applied adjustment counts as a new iteration, so the reports of the previous one are marked as outdated.
- *Server:* a reasoner that hangs is stopped together with its JVM (timeout on the subprocess); the Turtle repair calls
  the model in a worker thread instead of blocking the server; the page and its scripts are served with
  `Cache-Control: no-cache` and found relative to `app.py`, not to the working directory; text with lone surrogates
  (from broken PDFs) is sent as an escape instead of making the project list and the project fail with 500.
- *Generation and actions:* an upper class that an axiom still names is not removed as unused; a reasoner that could
  not run leaves an action package "not checked" instead of "checked, nothing new"; the hierarchy action and the
  evaluation count only open taxonomies - not yet decided and with categories not yet below their root; decisions on a
  taxonomy ("Taxonomy 'X'") now apply, before they were stored under a key the action never looked up.
- *Literature:* CSV and text files saved as Windows-1252 (German Excel) keep their umlauts; an abbreviation with two
  meanings in two papers ("VA" = visual analytics / visual attention) is grouped under its full form, not under the
  abbreviation; a consolidation that fails half-way leaves the grouping by name unchanged (it ran on the live list).
- *Prefixes:* owl, rdf, rdfs, xsd, sh and opla cannot be taken by the project, an additional prefix or a vocabulary
  for another namespace; a prefix derived from a namespace starts with a letter (`.../onto/1.0/` -> onto, not 10).
- *Documentation:* classes and properties of modules missing from the module list (loaded ontologies) and of no module
  get their own chapters instead of being left out; the table of deliberately unmodelled concepts uses the
  evaluation's classification (decisions on a variant count, a concept that has become a class is not listed).
- *Page:* the model list is filled at start; a base URL is only sent for RWTHgpt and Custom (a leftover URL redirected
  OpenAI requests); a saved key is not overwritten when RWTHgpt is chosen again; the server's Turtle and iteration win
  over the stored page state; returning to step 9 keeps unsaved Turtle-editor edits (with a note if the ontology
  changed meanwhile); loading an ontology hides the previous CQ and OOPS! reports; the CQ tests explain a missing
  LLM configuration instead of failing; a failed documentation download shows the reason instead of replacing the
  page; a second click cannot start a second paper extraction or action run; the core relations can be created when
  no property is left to assign.
**Why.** Together they remove the failure paths the review found in daily use. Only the count fix can change a
measured figure: a question whose query counts nothing on the sample data now gets a correction round instead of
passing. The VA runs are not re-evaluated for it; the next runs use it. A
browser that cached the scripts before the no-cache header needs one reload with Ctrl+F5.
**Alternatives.** Leaving the frontend details as they were: several of them lose work (editor edits, a saved key) or
send requests to the wrong endpoint. For the documentation, listing only the declared modules: a loaded ontology
without opla annotations would then have no chapters at all.

### 123. The tests run with pytest, sorted by topic, and do not depend on their order
**Decision.** The test suite runs with one `pytest` command (`requirements-dev.txt`, `pytest.ini`). `tests/conftest.py`
does the setup each file used to repeat (the project on the import path, sessions in a temporary folder) and, after
every test, restores each global of the tool's modules and of `requests` that the test replaced. `tests/helpers.py`
holds what several files share: the example ontology `base()`, the simulated model `FakeLLM`, its configuration
and the fixtures of the actions. The former `test_evaluation.py` (62 tests on many topics) is split into
`test_evaluation`, `test_cq_testing`, `test_actions`, `test_vocabularies`, `test_literature` and `test_turtle_export`;
the tests themselves are unchanged. The eight copies of the hand-written runner are gone.
**Why.** About 70 places in the tests replaced the model call (`L.call_llm = FakeLLM(...)`) and only a few put it back, so every test
ran with whatever the one before had left - the suite passed only because each file ran alone and in alphabetical
order. Run in one process, the first attempt already failed (a fake from the generation tests answered the rate-limit
test). With the restore after each test, all 161 tests pass in file order and in random order (pytest-randomly,
three seeds). One file with 1,400 lines on six topics also made it unclear where a new test belongs.
**Alternatives.** Rewriting every patch as a pytest `monkeypatch`: about 90 edits for the same effect, and new tests
written in the old style would leak again; the restore in `conftest.py` covers them too. Test classes or a mocking
library: more structure without more certainty. Keeping the runner per file: a second way to run the tests that
would have to be kept working.

### 124. "Evaluate 3x": three independent CQ tests with mean and spread (PLAN.md phase 6)
**Decision.** Step 9 has a third evaluation button, "Evaluate 3x". It tests the team's and the hold-out questions three
times, each run with new sample data and new queries (as "Evaluate from scratch"), and reports per run the questions
answered in full, partially and not at all, their mean and standard deviation, and per question in how many runs it
was answered in full and with which levels. Runs 2 and 3 run in parallel. The first run is stored as the
iteration's CQ test, as before - traceability, the reasoner's sample data and the next iteration's reuse build on
it; runs 2 and 3 only enter the mean. A failed run is named in the notes and left out of the mean. The tiles show
the mean ("8.7/10, mean of 3 runs (9, 8, 9; sd 0.6)") and how many questions vary; `tools/compare_runs.py` lists the
mean and spread per ontology.
**Why.** A single CQ test varied by up to 2 of 10 questions on the same ontology (wine runs, VA 3a-3c), because the
model writes the sample data and the queries anew. A change of one or two questions between configurations could not
be told apart from that noise. Three runs separate the two: the spread within one ontology against the differences
between ontologies.
**Alternatives.** Repeating the whole evaluation three times: the structural measures, the coverage and the reasoner
are deterministic and would only repeat. A configurable number of runs: three is what the plan asks for and keeps
the cost predictable (three times the tokens of the CQ tests: in the VA project one run of the team's and the
hold-out questions takes about 110k input tokens, so "Evaluate 3x" about 330k). Keeping the
best or the majority result as the stored test: it would hide the noise the button is meant to show.

### 125. Class restrictions: written by the modules, added by a repair tool, checked by the reasoner (PLAN.md phase 5)
**Decision.** The ontology gets class restrictions: `X SubClassOf p some Y`, `only Y`, and `min`/`max`/`exactly n Y`
(qualified; for a DatatypeProperty Y is a datatype). Only the class side - a restriction on the left side of
SubClassOf (MOMo's scoped domain, `(p some Y) SubClassOf X`) is left out, decided with the team.
- *Data model:* a list `restrictions` of the ontology (`class`, `property`, `kind`, `value`, `n`, `module`,
  `natural_language`), not entries of `axioms` as first proposed: code that knows only axioms between named classes
  (hierarchy, disjointness, cycle checks, the upper layer) then never misreads a restriction. Turtle writes each as an
  anonymous `owl:Restriction` under `rdfs:subClassOf`; the Turtle editor and "Load existing ontology" read them back
  (`hasValue` and composite fillers are not modelled and are left out). The documentation lists them per class and
  draws them as dashed arrows; the evaluation counts restrictions and classes with one.
- *Edit operations* `add_restriction` and `remove_restriction`. The class must lie within the property's domain and
  the value within its range - otherwise OWL would silently retype every X or Y; counts are whole numbers. Renames
  follow; removing a class drops its restrictions (a value class is replaced by `replace_with`); removing or merging a
  property moves its restrictions to the replacement or superproperty. A merge now records the merged property's own
  domain and range (`merge_records`), the class pair it gives up.
- *Generation:* each module writes the key restrictions of its classes - `some` only where every instance has the
  relation, `only` and numbers only where the domain or a question requires them; a pair that a core relation
  connects needs no new property. The server checks them like edit operations (the report lists what was left out).
  With Java, one reasoner run after all steps compares the ontology with and without restrictions; restrictions on
  classes that became unsatisfiable, on their superclasses and with them as value are removed and reported - at
  most two rounds, no model call.
- *Repair tool "Add class restrictions":* candidate class pairs with their evidence - recorded merges, relations that
  two or more papers state between two classes, and own object properties used by a passing CQ query - in packages
  of 30 per module. The model writes a restriction or declines the pair with a reason (stored, can be reconsidered);
  the reasoner guard checks each package. The evaluation counts the pairs left, which makes the tool appear.
  Restrictions do not change SPARQL answers, so the CQ re-test after the run (in the browser, as after every action)
  is a check that nothing else changed; the reasoner with the sample data shows whether an `only` contradicts them.
- The unused endpoints `/api/momo/spanning-axioms` (free-text DL that was never applied) and
  `/api/momo/review-naming` were removed with their prompts: restrictions cover the axioms, the naming conventions
  and OOPS! the naming.
- *Measurement:* `tools/lost_pairs.py` reconstructs the class pairs the VA consolidation gave up from the states
  before and after it (286 properties, 264 distinct pairs; the plan's 257 were counted on an intermediate state),
  writes them as merge records into a copy of the exported project, and after the repair counts how many pairs have a
  restriction again, next to the reasoner and the CQ results.
**Fixed after VA run 5a:** three modules wrote `hasPart min 2 ...`; `hasPart` is transitive, and OWL 2 DL allows no
number on a non-simple property, so HermiT refused the whole ontology (the generation's reasoner pass and the
evaluation reported an error instead of a result). The edit check now refuses a number on a property that is
transitive or has a transitive subproperty, also when a property with one becomes transitive later; the generation
report shows the reasoner's reason when it cannot check. The "Evaluate 3x" button now also shows before the first
evaluation, and the repeated tests keep per question why each run failed.
**Why.** A consolidation folds narrow properties into general ones; in the VA project 286 lost their class pair
(`depictsMultidimensionalData: ParallelCoordinatesPlot -> MultidimensionalData` became `depicts`), and a module that
uses a core relation between two of its classes had no way to say so (DECISIONS 89, 105). A restriction keeps the
pair without bringing back the narrow property: the relation vocabulary stays small, and the pair holds for the class,
not as a global domain and range that would retype every subject.
**Alternatives.** Scoped domain as well: needs general class axioms with a restriction on the left, in the data
model, export, import, checks and documentation, for a pattern the class side mostly covers. Restrictions as axioms
of the existing list: every function that reads `axioms` would have to tell them apart. Asking the model to repair
an unsatisfiable restriction during generation: costs a call in every generation that hits it; the repair tool can
add a better one later. Writing every merged pair as `some` without asking: a merged property's domain and range say
that some X relate to some Y, not that every X does.

### 126. A calmer page: light theme, grouped steps, step 9 in tabs, the generation as a pipeline
**Decision.** The page follows the mock-ups agreed with the team (four screens: step 9 overview and questions, step 8,
step 7), without changing what any action does or sends to the server:
- *Look:* a light theme - warm grey ground, white cards, one accent (#3346B8), status as text, soft fill and border
  colors (success, warning, error) that pass 4.5:1 for text. Every color is a CSS variable; the hard-coded colors of the
  dark theme in the CSS and the page scripts were mapped onto them. The graph keeps fixed values, since it draws on a
  canvas. Inter or the system font, no web font loaded.
- *Frame:* the header shows the project (opens the project list), the iteration and the model; New, Import, Export
  as plain buttons. The sidebar groups the steps (Prepare, Decide, Build and check) on one line each; the MOMo step
  numbers moved from the sidebar into each step's heading. The page is a flex column, so a wrapping header no longer
  makes the whole page scroll.
- *Step 9:* Evaluate, Evaluate 3x and the report are the head's actions; five tabs (Overview, Questions, Repair tools,
  Edit, Export) replace one long column of banners. The overview has scorecards and one **Needs attention** list that
  merges problems (outdated evaluation, reasoner error or unsatisfiable classes, questions that vary between runs,
  OOPS! pitfalls, untraceable classes) with the repair tools the evaluation asks for, each with its action. The
  questions tab shows each question's result per test run as filled, half and ring symbols - told apart by shape, not
  only color - with the reason of every run. The repair tools are a list of data now (label, action, why), from which
  both the tab and the attention list are drawn.
- *Step 8:* the generation report is a pipeline - plan, central concepts, vocabulary links, the modules (as cards
  with their class counts), the steps after the modules, class restrictions, the reasoner - each with its status,
  result, and the calls and tokens it used; warnings stand at the station they belong to.
- *Step 7:* "Design decisions" (as in the sidebar) in three tabs: patterns, core relations, vocabularies and
  prefixes. The core relations are grouped by their domain (between any classes, then the upper layer, then the
  rest), open while they are to be reviewed, closed with the names as a preview once approved.
- *Steps 1-6:* one sentence or two of introduction, the rest under "How this step works"; field labels in normal
  case; no emoji on buttons; the same Back / Continue bar in every step. The sidebar shows each step's state (sources,
  questions, key notions, undecided conflicts, core relations to review, an outdated evaluation, a missing key).
  Step 1 is one card, with show/hide for the key; a restored project without a key marks the model in the header
  "key needed" instead of a banner on every page. Step 2 offers two ways to start (describe the domain, or an
  existing ontology) instead of a second form below the first. Step 3 lists the sources as rows with their status
  as text (extracted, failed, pending, columns) and opens the inventory with scorecards (sources, concepts, central
  concepts, conflicts, themes). Step 4 is in five tabs (context document, open questions, definitions, conventions,
  upper layer), each counting what is still open - the 58 undecided definition conflicts of the VA project were easy
  to miss in the long form. Steps 5 and 6 show questions and key notions as numbered rows; "Suggest" is a secondary
  action that says it calls the model.
**Why.** The page had grown into long columns of colored banners, emoji buttons and two-line step names with "MOMo n"
tags; the evaluation, the repair tools, the CQ tests and the editors of step 9 were one scroll of about ten screens.
The team found the measurement figures hard to read at a glance - Evaluate 3x and the hierarchy target added more.
**Alternatives.** Restyling only the colors: leaves step 9's length and the scattered status. A framework (React,
Tailwind): a rewrite of 5,000 lines of page code for the same result, and a build step the tool does not have. Keeping
the dark theme: the mock-ups were reviewed in light; a dark variant can follow from the same variables.

### 127. A dark theme, switched in the header
**Decision.** A button in the header (sun / moon) switches between the light theme of DECISIONS 126 and a dark one.
The dark theme is a second set of the same CSS variables under `:root[data-theme="dark"]`, so every part of the page
built on them follows; the last colors still written as values (a neutral grey, row borders, white text on accent
buttons, the outline of empty run symbols) became variables first. Without a choice the page follows the system
setting (`prefers-color-scheme`); a choice is remembered in this browser (`localStorage`, guarded - without storage
it holds until the page is reloaded), and applied before the first paint, so the light theme does not flash. The
graph draws on a canvas, where CSS variables do not apply: it has its own colors per theme and is drawn again when
the theme changes. In the dark theme every text and status color has at least 6.3:1 contrast to its background.
**Why.** Asked for by the team; long sessions at the measurement runs.
**Alternatives.** Only following the system setting: no way to switch for one tool. A separate dark stylesheet:
two places to keep in step instead of one set of variables.

### 128. The tool is called LITMO
**Decision.** The tool is named **LITMO** – *LITerature-driven Modular Ontologies* – in the page header and title,
the landing page, the documentation export, the start script and the README. Internal identifiers stay as they are:
the project-file format `ontology-development-tool/project` (so exported projects keep importing), the repository
and file names.
**Why.** A name for the paper. LITMO says what the tool does (the literature inventory, MOMo's modules) and hints at
testing ("litmus"). A quick search (2026-10-30) found no ontology or knowledge-graph tool of that name.
**Alternatives.** TRACE: taken in the field (TRACE-KG, 2026, a text-to-schema knowledge-graph pipeline, and two other
TRACE knowledge-graph papers). OLIVE: taken (an LLM ontology-learning workflow, Applied Ontology 2025). MORTAR: a
building-analytics testbed built on the Brick schema. LITMOS: the name of a commercial learning-management system.
MOLIT: the usual acronym of the Korean Ministry of Land, Infrastructure and Transport. ARBOR and GROVE: free, but
common words that are hard to search for.

### 129. The logo: a book with a class tree and a ribbon
**Decision.** LITMO's mark is a closed book whose cover carries a small class hierarchy (a root and two children),
with a ribbon marker hanging out below. It replaces the three-node icon in the page header and the emoji on the
landing page, and is the favicon of both pages. In the page it is inline SVG coloured by the theme variables, so it
follows the light/dark toggle. `assets/litmo-logo.svg` is the full mark (for the README and the paper) and
`assets/litmo-icon.svg` a simplified drawing for 16 px (one node on the cover); both follow the system colour scheme.
The server mounts `assets/` at `/assets`.
**Why.** The book stands for the literature the tool starts from, the tree on it for the ontology it builds; the
ribbon joins in the bookmark idea and makes the mark distinct from a plain book icon. It keeps a solid silhouette at
favicon size.
**Alternatives.** Five concepts and four book variants were drawn (2026-10-30): a litmus strip (only says
"testing"), a bookmark with the tree (common in reading apps), an open book turning into a graph (too detailed for
small sizes), an L·O monogram (abstract without the wordmark), module tiles under a tree (no reference to
literature); and as book variants a thick book seen from the corner, an open book with the tree growing out of it,
and a tilted book.

### 130. Relation targets relative to the size of the ontology
**Decision.** The evaluation measures **top-level relations per class** (relations, one per inverse pair, that are below
no other property, divided by the number of classes) instead of the absolute number, with the guide value "about 0.3 or
fewer". The repair tool "Consolidate properties" is offered when the value is above 0.3 and there are at least 10
top-level relations (`TOP_LEVEL_PER_CLASS_MAX`, `TOP_LEVEL_MIN` in `relations.py`). The size of the core vocabulary it
proposes follows the same idea: 0.15-0.25 core relations per class, at least 3 to 5 (`core_relations_range`), shown in
the prompt and next to the vocabulary table. The scorecard shows the value per class with the absolute number below
it; `tools/compare_runs.py` reports both. The proposal before the generation (step 7, DECISIONS 89) keeps its ranges
(20-50 with literature, 5-15 without): the number of classes is not known yet.
**Why.** The old target, "about 70 top-level relations", and the core vocabulary of "40-70" came from DECISIONS 70 and
were set for the VA ontology without a stated reason. As absolute numbers they do not work for other domains: the wine
ontology (18 classes, 6 relations) would have been asked for 40-70 core relations, and a much larger ontology could
never reach 70. The problem DECISIONS 70 addressed is relative - 275 narrow relations for 345 classes (0.8 per class),
almost none below another. At the VA size 0.3 per class equals the old target (70 for about 240 planned classes), so
the measurement runs keep their verdicts: recomputed, raw generations had 0.83-1.17, the baseline after all repairs
0.32, runs 1-3c 0.35-0.41, 4a-4c 0.27-0.35, 5a-5c 0.25-0.33 (see `examples/va/RUNS.md`). The minimum of 10 keeps small
ontologies from being sent to a consolidation they do not need (wine 14: 6 relations, 0.33 per class).
**Alternatives.** The share of the ontology's own relations placed below a core relation (VA runs 15-62 %): measures the
structure directly, but in a small ontology one unplaced relation decides it (wine: 2 own relations, 0 %), and merged
relations, the best outcome, disappear from it. No target at all, only the number: the team would have nothing to
compare against, and the repair tool needs a trigger. Relations per class including those below a core relation: a
well-structured ontology with many specific subproperties would look worse. 0.3 is still a heuristic, not a value from
the literature; it should be checked against reference ontologies in the evaluation (EVALUATION.md, stage C).

### 131. Every exclusion of the plan gets a second look; "accounted for as X" is an assignment
**Decision.** Two changes to the completion of the plan (`complete_plan`, DECISIONS 104 and 110):
1. Every central concept the plan excludes goes to the completion again, marked REVIEW with the plan's reason - not
   only taxonomy categories and concepts named by a competency question. The completion places it or excludes it
   again with a reason; if it does neither, the plan's reason stands. The protected concepts keep their stricter rule
   (only "out of scope" or "the same as another concept"). Concepts the team excluded earlier are not asked again.
2. An exclusion whose reason names a planned class ("accounted for as ObjectiveUncertainty in the Uncertainty
   module", "the same as RedWine") is taken as an assignment to that class. Only exact names of planned classes count,
   and not when the name is followed by "module".
The report adds `reviewed_protected` and `accounted_as`; `reviewed` now counts all reviewed exclusions, and `by_plan`
counts what the plan placed, without its exclusions (so placed + completed + excluded + open = central; before, the
plan's exclusions were counted twice). Step 8 shows the reassigned exclusions.
**Why.** VA 4a-5c (`examples/va/RUNS.md`): with identical input - inventory, questions, key notions, context, model -
the planning call excluded 16, 16, 31, 51, 40 and 31 central concepts. The review re-examined only the protected ones
and placed nearly all of them, so the spread of one call decided how many concepts stayed excluded (9-26) and moved
"central concepts as a class" by several points (75.0-85.2 %). A second decision on every exclusion damps this, and
the completion batches 60 concepts per call, so with 16-51 exclusions it rarely needs a further call. Two of 5a's 26
exclusions were concepts the plan had modelled ("accounted for as ..."): bookkeeping, not decisions.
**Alternatives.** Asking for fewer exclusions in the planning prompt: the prompt already says every central concept
must be accounted for, and the spread came with an unchanged prompt. Running the plan several times and taking the
majority: two to three times the most expensive call of the generation. Reviewing only exclusions with weak reasons
("too specific"): the reasons vary as much as the decisions (5a: "a design-study-specific description", "beyond the
first-version scope"). Matching any class name in the reason: "not the general Interaction notion" names a class to
say the opposite.
**Effect:** to be measured in the next VA runs; the expected result is a smaller spread of "central concepts
excluded" and of "central concepts as a class".

### 132. Root classes follow links through vocabulary terms
**Decision.** A class is a root class only if it has no own class above it - neither as parent nor through a
vocabulary term: `User` below `prov:Person`, with `prov:Person SubClassOf Agent`, lies below `Agent` and is no root.
The evaluation also lists the classes that hang only below a vocabulary term, with no path to an own class
(`classes_below_vocabulary_only`), and the generation report's "outside the upper layer" counts them too. For round 6,
`tools/compare_runs.py` reports the plan's exclusions as DECISIONS 131 counts them: excluded by the plan, given a second
look, excluded again, and named a planned class.
**Why.** VA 5c had "8 root classes": the four upper classes and `User`, `DomainExpert`, `VisualizationResearcher`,
`DesignStudyCollaborator` below `prov:Person` - which the ontology itself puts below `Agent`. The count followed only
the parent field, so a correct link to PROV-O looked like four classes outside the hierarchy. Recomputed: 5c 8 -> 4,
run 1 5 -> 4, all other runs unchanged; 5a keeps 5, because `CollaboratorRole` hangs below `dcat:Role` only - a real
gap, now listed by name.
**Alternatives.** Putting such classes below their upper class as well (a second parent): the ontology already says
it, and a duplicate SubClassOf adds nothing. Counting classes below any vocabulary term as non-roots: `CollaboratorRole`
would vanish from the count although nothing connects it to the rest.

### 133. Hold-out questions chosen by their central concepts, stored, and reviewed by the team
**Decision.** The hold-out questions are chosen by the concepts of the inventory they name (`select_holdout_cqs`):
first questions that name at least two central concepts (two or more sources) and at most half as many that only one
paper uses, ranked by the number of central concepts and their sources; then questions with one central concept; the
rest only to fill up. The set is spread over the themes of the inventory (one question per theme first, then two) and
over the papers (as before, at most two per paper until the last pass). The selection is stored with the project
(`session["holdout"]`) and every evaluation tests the same questions; a question that is no longer eligible (one of
the team's questions became similar, the team removed it) is replaced by the next candidate. Step 9, tab Questions,
shows the set for the next evaluation with the central concepts each question names (as worded in the question), its
theme and its single-source terms; the team can remove a question or choose the set again
(`/api/holdout`, `/api/holdout/remove`, `/api/holdout/reset`; no model calls).
**Why.** VA: 415 of the 416 literature questions come from one paper, so the old order "most sources first" was the
order of the inventory - the hold-out set of 5a-5c contained "What components define a Vega-Lite unit
specification?" and "Which composition operators can construct a multi-view display, and what does each do?", whose
concepts appear in one paper each. These failed in nearly every run (5a-5c: hold-out 4.1 of 10), which measured the
detail of single papers, not whether the ontology answers what the field agrees on. The new set for VA names 3-7
central concepts per question and covers eight of the ten themes. Storing the set makes iterations comparable: before,
it was recomputed at every evaluation and changed with the team's questions. The team decides whether a question fits
the use case, as at every other step.
**Alternatives.** Letting a model pick or rewrite the questions: one more call, and a model choosing the questions it
will be tested on could choose easy ones. Requiring only central concepts: in VA common words ("component",
"problem", "system") are single-source concepts of the inventory, so 70 % of the questions would drop out. A larger
set (20 questions): twice the cost of every evaluation, with Evaluate 3x 30 more calls per run.
**Consequence for the measurements:** hold-out results from before this entry are not comparable with later ones.
VA run 5c is evaluated once more with the new set as a bridge (examples/va/RUNS.md).

### 134. Hold-out questions about what can or must be come last
**Decision.** The hold-out selection (DECISIONS 133) puts questions with modal, normative or exhaustive wording - can,
could, must, should, may, need, require, help, allow, enable, let, every, possible, best, suitable, appropriate,
effective - after the plain ones, ahead only of questions without a central concept. A set chosen by the older rules
is chosen again once (`HOLDOUT_SELECTION_VERSION`); questions the team removed stay removed. The review in step 9 marks
such a question ("asks what can be - sample data answer that only in part").
**Why.** The bridge on VA 5c (`examples/va/RUNS.md`): with the set of DECISIONS 133 every question was answered at
least partly, but only 2 of 10 in full, in all three runs. The check of partial answers said why, and it was the
wording: six questions asked what an analyst *can* do, what *must* be recorded, which views *can* be exported, which
tasks a graph *requires* - "the query identifies recorded actions, not every action an analyst could potentially
perform". An ontology with sample data shows what is recorded; possibility, necessity and completeness it can show
only in part, however well it models the concepts. A test that cannot be passed in full measures the wording. For 5c
the new set keeps four questions of the bridge set and names the same kind of central concepts; 124 of the 416 VA
questions have such wording.
**Alternatives.** Reporting "answered at least partly" as the main hold-out figure: it was already 10 of 10 and could
not show an improvement. Telling the check of partial answers to accept "what is recorded" for "what can be": the
check would then pass answers that really are incomplete. Rewriting the questions with a model: a model would choose
how the ontology is tested.
**Consequence:** the 5c bridge is repeated with the new set; round 6 is compared with that.

### 135. A query rdflib cannot evaluate fails only its own question
**Decision.** The CQ test reads the result rows of a query inside the error handling of that one question
(`_run_cq_test`). A query that rdflib parses but cannot evaluate is reported for its question as "Query failed: ..."
and counts like a query without a result (partly answered if it uses terms of the ontology, `cq_level`); the other
questions of the test, and the further runs of Evaluate 3x, go on.
**Why.** VA 5c, second bridge (DECISIONS 134): a hold-out query put `EXISTS { ... }` inside a SELECT expression.
rdflib accepts it and fails only when the rows are read ("What do I do with this CompValue?") - after the existing
`try` around `query()`, because rdflib evaluates lazily. The exception left the whole hold-out test, and Evaluate 3x
then skips the further runs of a test whose first run failed: no hold-out result at all, 7 calls spent.
**Alternatives.** Rejecting EXISTS in expressions before running the query: rdflib may fail on other constructs too,
and the guard has to be where the rows are read anyway. Asking the model to rewrite such a query: the correction step
for empty results could take it on later, but a failed query is already reported with its reason.

### 136. Three follow-ups of round 6: concepts the modules did not build, the previous evaluation, EXISTS in queries
**Decision.**
1. *Central concepts missing after the modules.* The module prompt lists each notion to be modelled as a property or
   individual with its concept ids ("[c12] Tannin level -> as property"), and the module gives the property or
   individual it creates for it `"concepts"`; the merge stores them as `inventory_concepts`, as for classes, and the
   evaluation's concept index finds a concept through them (also kept through the Turtle editor). After the modules,
   the hierarchy and the core relations, the generation looks for central concepts that the plan did not exclude and
   that are still not represented, and runs the step of "Add missing central concepts" for them (`missing_after_modules`,
   12 per call, only when something is missing). What the model declines is stored as a decision. Step 8 reports how
   many were missing, added and declined.
2. *The previous evaluation is kept.* When an iteration is evaluated whose predecessor evaluation belongs to another
   iteration, a summary of that one is kept (`evaluation_previous`: classes, properties, restrictions, central concepts
   as a class and represented, hierarchy decided, root classes, top-level relations per class, questions in full - the
   mean of Evaluate 3x where there is one - and the reasoner). The report carries it as `previous`, and step 9 shows a
   table "Compared with iteration N" with the change per figure. Evaluating the same iteration again keeps the
   comparison; a new generation or a loaded ontology removes it.
3. *EXISTS only in FILTER.* The prompts that write and correct test queries say: EXISTS and NOT EXISTS only inside
   FILTER, never in the SELECT list, BIND or IF; for a yes/no value use OPTIONAL and BOUND.
**Why.** (1) VA 6a-6c: 3-8 central concepts per run that the plan had placed were "missing". Some were built under
another name - "stability of the task" as `hasTaskStability`, "synthesis" as `synthesizesInformation` - which the
evaluation could not connect; others no module built (`chunking`, `feedback loop`, `scope of the task`). The repair
action existed but needed a separate round by the team. (2) The class-restrictions run of 2026-10-30 lost its
"before" results: the second evaluation overwrote the first. (3) The 5c bridges: the test model wrote EXISTS in a
SELECT expression for yes/no questions three times; rdflib cannot evaluate it there (DECISIONS 135), so the answer
counted as partial regardless of the ontology. Both alternatives the rule names were checked with rdflib.
**Alternatives.** (1) Adding the missing concepts from the plan without a model call: for a property or an individual
the plan has only a hint, no domain, range or class. Matching property names to concepts more loosely: "synthesis" in
`synthesizesInformation` is easy, `hasTaskStability` for "stability of the task" is not, and loose matching finds false
links. (2) Keeping every evaluation: the project file grows with each one, and the comparison needed is with the one
before. (3) Rewriting such queries automatically: the rule prevents them, DECISIONS 135 limits the damage of the rest.

### 137. The hold-out questions are set aside before the question suggestions see the literature
**Decision.** "Suggest questions" (step 5) first chooses the hold-out set (DECISIONS 133) and shows the model only the
other literature questions; those it saw are recorded as before. The hold-out set takes at most half of the literature
questions (at most 10), so the rest remain for the suggestions. When no hold-out question is left, step 9 (tab
Questions) says why: how many questions the sources have, how many the suggestions saw.
Also fixed in the walkthrough: a variable declared twice in `js/step8-generate.js` (from DECISIONS 136) made the
browser reject the whole script, so "Generate Ontology" did nothing; and "Evaluate" pressed in another tab of step 9
(e.g. Repair tools) now switches to Overview, where the progress and the result appear - before, nothing seemed to
happen. And if restoring a project in the page fails partway, the page saves nothing until it is reloaded and says so:
the script error above stopped the restore of the open project (VA 6c), the page held a half-empty state, and when
the model was changed in step 1 it saved that state over 6c's stored interface state (step, displayed evaluation,
usage counter; the ontology, the generation report and the evaluation on the server were not affected).
**Why.** v0.2 walkthrough (wine, five sources): the inventory had 37 literature questions, the suggestions saw up to
40 - all of them - and the hold-out test, which excludes every question a model has seen, had nothing left. In VA (416
questions, the first 40 shown) this never showed. Choosing the hold-out questions first keeps them unseen by
construction instead of by luck.
**Alternatives.** Showing the suggestions fewer questions in small projects: the hold-out set would still depend on
which questions happen to come first. Letting a seen question count for the hold-out test: it could have shaped the
ontology and flatter the result. No hold-out set for small corpora: the walkthrough's wine project is the typical
size of a first project.
**For existing projects:** where the suggestions already saw every literature question (the walkthrough project), the
hold-out set stays empty; new projects get one.

### 138. Importing class definitions; the core-relation proposal sized by the key notions
**Decision.**
1. *Import.* A class defined as an intersection (owl:intersectionOf, directly or under owl:equivalentClass) gets the
   named members as superclasses and the simple restrictions among them (some, only, min, max, exactly) as class
   restrictions - as necessary conditions; the model has no place for the definition as such. What the model cannot
   hold is counted and reported instead of dropped silently: hasValue restrictions, enumerations (owl:oneOf), unions,
   complements. Step 2 shows the count after loading and then waits for "Continue to step 9" instead of moving on.
2. *Step 7.* The core relations proposed before the generation are sized by the key notions: two to four per key
   notion (at least 3 to 5); without key notions as before (20-50 with literature, 5-15 without).
**Why.** v0.2 walkthrough, step 11: the W3C wine ontology defines 56 classes as intersections (RedWine = Wine and
hasColor value Red); the import kept only rdfs:subClassOf, so 62 of its 74 classes became root classes, and the
reference was tested on a flattened copy (1 of 9 questions in full). With the fix: 7 root classes, depth 4, 32
restrictions instead of 18; still not read: 115 hasValue restrictions, 31 enumerations, 1 union - now said. In step 7
the walkthrough's wine project (5 key notions) got 21 core relations from "about 20 to 50" - sized for VA - which
alone made 0.31 top-level relations per class and the consolidation necessary at once (DECISIONS 130). Two to four per
key notion gives 10-20 for wine and 20-40 for VA, which approved 39-41.
**Alternatives.** Supporting hasValue and enumerations in the model, the edit operations and the export: the complete
fix, planned after v0.2. Reading an intersection definition as EquivalentClasses with a class expression: the axiom
model holds named classes only. Sizing step 7 by the central concepts: in a small corpus they undercount the classes
(wine: 12 central concepts, 60 planned classes).
**Found but not fixed in v0.2:** a paper's own method leaks into the ontology (WineGraph: `Graph`, `GraphNode`,
`GraphLink`, `FlavorGraph`, `AromaVector` as classes of a wine shop's ontology) - the plan did not exclude them, so the
second look of DECISIONS 131 does not see them; as in VA's research-side concepts, a check whether a concept is about
the domain or about a paper's way of studying it is needed.

### 139. No credentials in the code; the public repository starts from a clean state
**Decision.** The RWTHgpt key is no longer in `js/step1-llm.js`: the server reads a key for RWTHgpt from the
environment variable `LITMO_RWTHGPT_KEY` and uses it when a request brings none; the page asks the server only whether
it has one (`/api/config`, yes or no) and then accepts an empty key field in step 1. `github_push.bat`, which held a
GitHub token, is no longer tracked (it stays on the developer's machine and is ignored). Two namespaces in
`patterns_catalog.json` that were a local file path are empty, and the catalog builder no longer writes such paths.
The repository is made public as a **new repository** whose history starts from this state; the development
repository with its full history stays private.
**Why.** For the ERCIM article the code has to be public. A scan of all 101 commits found exactly two credentials: the
GitHub token in every commit since the first (30 May) and the RWTHgpt key in earlier versions of `index.html` and
`js/step1-llm.js`. Removing them from the current files would leave them readable in the history. Both are revoked and
replaced by their owner.
**Alternatives.** Rewriting the history of this repository (git filter-repo) and publishing it: keeps the history but
changes every commit hash, including the version branches, and copies made earlier would still hold the credentials.
No default key at all: every member of the team would have to enter the KI:connect key in every session; a key on the
server keeps that convenience without putting it in a file.

## Open points (decided to do, not yet built, or deliberately postponed)

- **Raise the cap on key-notion suggestions** when an inventory exists (about the number of themes, at most about 12).
- **Split large modules across calls** (more than about 40 planned classes) so every call stays far below the output limit even with
  small models, and a **"Regenerate this module"** button, so one module can be redone after a conflict is resolved
  without touching the others.
- **Two-stage consolidation** (themes from names first, then conflicts per theme with all definitions) for models with
  small context windows, which probably also finds conflicts more reliably.
- **A UI selector for the modules in focus** of a feedback round (automatic detection from the text exists).
- **Manual Turtle edits** rebuild the ontology from the file (`rdf_graph_to_onto`) and may lose `sources` and module
  assignments; this predates the edit operations and has not been reworked.
- **Capturing decisions** from rejected patterns and feedback rounds in the project context (discussed, deliberately
  postponed until the context step has been used with real projects).
- **Hierarchy-aware generation**: the planning call sees broader terms and taxonomies and plans superclasses;
  every central concept must be assigned or explicitly excluded. Fewer inverse properties (prompt rule since 102).
- **Evaluation stages B-E** (grounding check, reference comparison, expert review, study design) - see
  [`EVALUATION.md`](EVALUATION.md).
- **Run the whole pipeline with real models** on the 56-paper corpus; everything so far was tested with scripted fake
  models and real PDFs. (Done for gap filling with gpt-6-sol on 2026-10-15, see 66 and 67.)
- **Alignment module for the upper layer** (68): map Process, Agent, InformationObject, Specification and Quality onto
  DOLCE/DUL (fits the ODP library) or BFO in a separate module, and list the classes that alignment would force to split
  (Visualization, User, Task, Uncertainty).
- **Reconsider for hierarchy and upper-layer decisions**, as for declined concepts (65), and for properties kept in
  a consolidation (70).
- ~~**Class restrictions (axiom step)**~~: built in DECISIONS 125 (class side only; scoped domain, i.e. a
  restriction on the left side of SubClassOf, is still open).
- ~~**Keep the previous evaluation**~~: built in DECISIONS 136.
