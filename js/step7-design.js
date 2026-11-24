// Schritt 7: Patterns, Standards und Vokabulare, Prefixe, Kernrelationen
// (PLAN.md Phase 4: eine Datei je Schritt; klassische Skripte - alle Funktionen sind global,
// sofort ausgefuehrt wird nur main.js, das zuletzt laedt)

// ── Step 5: Design Patterns (MOMo Step 4) ─────────────────────────────────────
async function proceedToPatterns() {
  // Vorschlaege gelten erst nach "+ Add" - nicht stillschweigend verlieren.
  if (notionSuggestions.length && !confirm(`${notionSuggestions.length} suggested key notion${notionSuggestions.length > 1 ? 's were' : ' was'} not added: ` +
      `${notionSuggestions.map(n => n.name).join(', ')}.\n\nOnly the key notions in your list are used. Continue without ` +
      `${notionSuggestions.length > 1 ? 'them' : 'it'}?`)) return;
  const { removed } = syncPatterns();
  await saveMomo();
  goTo(5);                                         // zeigt den Schritt (showPatternStep), ohne Modellaufruf
  if (removed.length) showPatternStep(removed);
  if (!state.suggestedStandards.length) loadStandards();
  // Modellaufrufe nur ueber "Continue", nicht beim Oeffnen ueber die Seitenleiste oder beim Laden der Seite
  const { missing } = syncPatterns();
  if (!state.momo.patterns.length && namedNotions().length) suggestPatterns();
  else if (missing.length) suggestPatterns(missing);
  // Kernrelationen sind voreingestellt (PLAN.md): vor der ersten Generierung von selbst vorschlagen, nicht bei
  // Projekten, die schon eine Ontologie haben (die verhalten sich wie bisher, bis das Team es anstoesst)
  if (!state.propertyVocab && !state.currentOntology && state.llmConfig &&
      (namedNotions().length || state.momo.competencyQuestions.length)) proposeCoreRelations();
}

// Schritt 7 anzeigen, auch ueber die Seitenleiste (Wein-Lauf 3): Pattern-Wahl der Key Notions angleichen, neue
// Notions ohne Wahl nennen. Gespeichert wird mit der naechsten Aenderung - nicht hier, denn goTo laeuft auch beim
// Wiederherstellen der Seite, bevor alle Felder gefuellt sind.
function showPatternStep(removedBefore) {
  const sync = syncPatterns();
  const removed = [...(removedBefore || []), ...sync.removed];
  const pending = state.momo.patterns.length ? sync.missing : [];
  document.getElementById('patternStatus').innerHTML =
    (removed.length ? `<div class="alert alert-info"><span>ℹ️</span><span>Removed the pattern choices for key notions
      that are no longer in your list: ${esc(removed.join(', '))}.</span></div>` : '') +
    (pending.length ? `<div class="alert alert-info"><span>🧩</span><span>No pattern choice yet for ${esc(pending.join(', '))}.
      <button class="btn btn-secondary btn-sm" onclick='suggestPatterns(${esc(JSON.stringify(pending))})'>✨ Suggest for
      ${pending.length > 1 ? 'them' : 'it'}</button></span></div>` : '');
  renderPatterns();
  renderCoreVocab();
}

// ODPA-Katalog (https://github.com/odpa/patterns-repository), einmal pro Seite geladen.
let patternCatalog = null;
async function loadPatternCatalog() {
  if (patternCatalog) return patternCatalog;
  try {
    const res = await fetch(API + '/api/patterns');
    const data = await res.json();
    patternCatalog = { ...data, byId: Object.fromEntries(data.patterns.map(p => [p.id, p])) };
  } catch (e) {
    patternCatalog = { source: '', commit: '', patterns: [], byId: {} };
  }
  document.getElementById('patternOptions').innerHTML = patternCatalog.patterns
    .map(p => `<option value="${esc(p.id)}">${esc((p.intent || '').slice(0, 90))}</option>`).join('');
  document.getElementById('patternSource').innerHTML = patternCatalog.patterns.length
    ? `📚 Patterns come from the <a href="${esc(patternCatalog.source)}" target="_blank" rel="noopener"
         style="color:var(--accent-light);">ODPA Patterns Repository</a> (${patternCatalog.patterns.length} patterns with an OWL
         formalization${patternCatalog.commit ? ', snapshot ' + esc(patternCatalog.commit.slice(0, 7)) : ''}).`
    : '⚠️ Pattern catalog unavailable — patterns can still be entered by name.';
  return patternCatalog;
}

function patternDetailHtml(id) {
  if (!id) return '';
  const pat = patternCatalog && patternCatalog.byId[id];
  if (!pat) return `<div class="pattern-warn">⚠️ "${esc(id)}" is not in the ODPA repository. It will be recorded as a
    comment in the OWL export, and no pattern structure is passed to the model.</div>`;
  const els = [...pat.classes, ...pat.properties];
  return `<div class="pattern-detail">
    ${pat.intent ? `<div>${esc(pat.intent)}</div>` : ''}
    ${els.length ? `<div class="elements">${esc(els.slice(0, 14).join(' · '))}${els.length > 14 ? ' · …' : ''}</div>` : ''}
    <div style="margin-top:6px;">
      <a href="${esc(pat.url)}" target="_blank" rel="noopener">View in ODPA ↗</a>
      <a href="${esc(pat.owl_url)}" target="_blank" rel="noopener">OWL file ↗</a>
      ${pat.diagram_url ? `<a href="${esc(pat.diagram_url)}" target="_blank" rel="noopener">Schema diagram ↗</a>` : ''}
    </div>
  </div>`;
}

// Die Pattern-Wahl folgt den Key Notions: Eintraege fuer Notions, die nicht mehr in der Liste stehen, fallen weg;
// neue Notions ohne Eintrag werden gemeldet, damit nur fuer sie Vorschlaege geholt werden (Wein-Lauf 2).
function syncPatterns() {
  const key = s => String(s || '').toLowerCase().replace(/[^a-z0-9]/g, '');
  const names = new Set(namedNotions().map(n => key(n.name)));
  const removed = state.momo.patterns.filter(p => !names.has(key(p.notion))).map(p => p.notion);
  state.momo.patterns = state.momo.patterns.filter(p => names.has(key(p.notion)));
  const have = new Set(state.momo.patterns.map(p => key(p.notion)));
  const missing = state.momo.patterns.length ? namedNotions().filter(n => !have.has(key(n.name))).map(n => n.name) : [];
  return { removed, missing };
}

// only: nur fuer diese Key Notions (die uebrigen Eintraege bleiben); ohne: fuer alle, ersetzt die Liste.
async function suggestPatterns(only) {
  if (!namedNotions().length) { alert('Please name your key notions first (Step 6).'); return; }
  const status = document.getElementById('patternStatus').innerHTML;
  const data = await momoCall('suggest-patterns', 'patternStatus', only
    ? `Searching for design patterns for the new key notion${only.length > 1 ? 's' : ''} ${esc(only.join(', '))}…`
    : 'Searching for matching design patterns…', only ? { only } : null);
  if (!data) return;
  if (only) {
    // die Meldung von vorher behalten, nur den Hinweis auf die nun erledigten Notions nicht
    document.getElementById('patternStatus').innerHTML = status.includes('🧩') ? '' : status;
    const order = namedNotions().map(n => n.name);
    state.momo.patterns = [...state.momo.patterns, ...(data.patterns || [])]
      .sort((a, b) => order.indexOf(a.notion) - order.indexOf(b.notion));
  } else state.momo.patterns = data.patterns || [];
  renderPatterns(); saveMomo();
}

async function renderPatterns() {
  await loadPatternCatalog();
  const list = state.momo.patterns;
  document.getElementById('patternSelectRow').style.display = list.some(p => p.pattern) ? 'flex' : 'none';
  updatePatternSelection();
  document.getElementById('patternList').innerHTML = list.length ? list.map((p, i) => `
    <div class="momo-item ${p.pattern ? 'selectable' : ''} ${patternUsed(p) ? 'selected' : ''}">
      <div class="momo-item-head">
        ${p.pattern ? `<input type="checkbox" ${p.selected !== false ? 'checked' : ''}
          title="Use this pattern as the module template" onchange="togglePattern(${i}, this.checked)" />` : ''}
        <div style="font-weight:600;">${esc(p.notion)}
          ${!p.pattern ? '<span class="badge-scratch">built from scratch</span>'
            : p.selected !== false ? `<span class="badge-pattern">${esc(p.pattern)}</span>`
            : `<span class="badge-scratch">${esc(p.pattern)} — not used, built from scratch</span>`}
          ${p.pattern && FIT_LABEL[p.fit] ? `<span class="fit-badge fit-${p.fit}" title="${esc(FIT_LABEL[p.fit][1])}">${FIT_LABEL[p.fit][0]}</span>` : ''}
        </div>
      </div>
      ${p.pattern && p.fit === 'partial' && p.selected === false
        ? `<div class="meta" style="color:var(--warning);">Partial fit — not used unless you select it.</div>` : ''}
      ${p.rationale ? `<div class="meta">${esc(p.rationale)}</div>` : ''}
      ${p.pattern && p.keep ? `<div class="meta">✓ Keep: ${esc(p.keep)}</div>` : ''}
      ${p.pattern && p.change ? `<div class="meta">✎ Change: ${esc(p.change)}</div>` : ''}
      ${(p.alternatives && p.alternatives.length)
        ? `<div class="meta">Alternatives: ${p.alternatives.map((a, j) =>
            `<span class="alt-chip" title="Use this pattern instead" onclick="updatePattern(${i}, state.momo.patterns[${i}].alternatives[${j}], true)">${esc(a)}</span>`).join('')}</div>` : ''}
      <input type="text" list="patternOptions" value="${esc(p.pattern || '')}"
             onchange="updatePattern(${i}, this.value, true)"
             placeholder="Search the ODPA repository… (leave empty to build from scratch)" style="margin-top:8px;" />
      <div id="patternDetail${i}">${patternDetailHtml(p.pattern)}</div>
    </div>`).join('')
    : `<p style="color:var(--text-muted); font-size:0.85rem;">No patterns yet — use ✨ Suggest Design Patterns.</p>`;
}

// Passung laut Modell: nur starke Treffer sind vorausgewaehlt, Teiltreffer waehlt das Team bewusst.
const FIT_LABEL = {
  strong: ['strong fit', 'The pattern\'s core structure matches this notion; only small adaptations are needed.'],
  partial: ['partial fit', 'Only parts of the pattern are usable, or it needs substantial changes.'],
  manual: ['chosen by you', 'You picked this pattern yourself.'],
};

// Wie bei den Standards: nur ausgewaehlte Patterns gehen als Modul-Template in die Generierung.
function patternUsed(p) { return !!p.pattern && p.selected !== false; }

function togglePattern(i, on) {
  state.momo.patterns[i].selected = on;
  renderPatterns(); saveMomo();
}

function toggleAllPatterns(on) {
  state.momo.patterns.forEach(p => { if (p.pattern) p.selected = on; });
  renderPatterns(); saveMomo();
}

function updatePatternSelection() {
  const withPattern = state.momo.patterns.filter(p => p.pattern);
  const n = withPattern.filter(patternUsed).length;
  document.getElementById('patternSelectedCount').textContent =
    n === 0 ? 'None selected' : `${n} of ${withPattern.length} selected`;
  document.getElementById('selectAllPatterns').checked = withPattern.length > 0 && n === withPattern.length;
}

function updatePattern(i, v, rerender) {
  const p = state.momo.patterns[i];
  const prev = p.pattern;
  p.pattern = v.trim() || null;
  if (p.pattern !== prev) {
    p.selected = true;  // ein neu gewaehltes Pattern soll auch verwendet werden
    // Bewertung und Anpassungshinweise des Modells galten fuer das alte Pattern
    p.fit = p.pattern ? 'manual' : 'none';
    delete p.keep; delete p.change;
    p.rationale = '';
  }
  // Bei Wechsel auf eine Alternative die bisherige Wahl als Alternative behalten.
  if (p.alternatives && p.alternatives.includes(p.pattern)) {
    p.alternatives = p.alternatives.filter(a => a !== p.pattern);
    if (prev) p.alternatives.push(prev);
  }
  if (rerender) { renderPatterns(); saveMomo(); }
}

// ── Step 5: Standards (shown alongside MOMo Step 4 design patterns) ───────────
async function loadStandards() {
  if (!state.llmConfig) { alert('Please configure the LLM first (Step 1).'); goTo(1); return; }
  const domain = document.getElementById('domainDesc').value.trim();
  const extra = document.getElementById('extraReqs').value.trim();
  const combined = domain + (extra ? '\n\nAdditional requirements:\n' + extra : '');

  document.getElementById('standardsContent').style.display = 'none';
  document.getElementById('reloadStandardsBtn').style.display = 'none';
  document.getElementById('standardsStatus').innerHTML = `
    <div class="alert alert-info">
      <div class="spinner"></div>
      <span>The LLM is analysing the domain and finding suitable standards and ontologies…</span>
    </div>`;

  try {
    const res = await fetch(`${API}/api/suggest-standards`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: state.sessionId,
        domain_description: combined,
        llm_config: state.llmConfig,
      }),
    });
    const text = await res.text();
    let data;
    try { data = JSON.parse(text); } catch(_) {
      throw new Error(`Server-Antwort ist kein JSON (HTTP ${res.status}):\n${text.slice(0, 300)}`);
    }
    if (!res.ok) throw new Error(data.detail || JSON.stringify(data));
    state.suggestedStandards = data.standards;
    state.selectedStandards = [...data.standards];

    document.getElementById('standardsStatus').innerHTML =
      `<div class="alert alert-success">✅ ${data.standards.length} suggestions found. Select the relevant standards.</div>`;

    renderStandards(data.standards);
    document.getElementById('standardsContent').style.display = 'block';
    document.getElementById('reloadStandardsBtn').style.display = 'inline-block';
    markDone(5);
  } catch(e) {
    document.getElementById('standardsStatus').innerHTML =
      `<div class="alert alert-error"><div style="white-space:pre-wrap">❌ Error: ${escHtml(e.message)}</div></div>`;
    document.getElementById('reloadStandardsBtn').style.display = 'inline-block';
  }
}

// Schritt 7 (DECISIONS 74): je Standard Namespace, Praefix, Entscheidung und das geladene Vokabular
const DECISION_LABELS = { align: 'align — keep own classes, link them', use_terms: 'use terms directly', reference: 'reference only' };
function renderStandards(standards) {
  const grid = document.getElementById('standardsGrid');
  const chosen = new Set(state.selectedStandards.map(s => s.name));
  const stop = 'onclick="event.stopPropagation()"';
  grid.innerHTML = standards.map((s, i) => {
    const sel = chosen.has(s.name), v = s.vocabulary;
    return `
    <div class="standard-card ${sel ? 'selected' : ''}" id="scard-${i}" onclick="toggleStandard(${i})">
      <input type="checkbox" ${sel ? 'checked' : ''} id="scb-${i}" onclick="event.stopPropagation(); toggleStandard(${i})" />
      <div class="standard-info">
        <div class="standard-name">${escHtml(s.name)}</div>
        <span class="standard-type">${escHtml(s.kind || s.type || 'ontology')}</span>
        <div class="standard-relevance">${escHtml(s.relevance || '')}</div>
        ${s.reuse_hint ? `<div class="standard-hint">💡 ${escHtml(s.reuse_hint)}</div>` : ''}
        <div style="display:grid; grid-template-columns:80px 1fr; gap:4px 8px; margin-top:8px; font-size:0.8rem;" ${stop}>
          <span class="lit-meta">Use</span>
          <select onchange="updateStandard(${i}, {decision: this.value})">${Object.entries(DECISION_LABELS).map(([k, l]) =>
            `<option value="${k}" ${s.decision === k ? 'selected' : ''}>${l}</option>`).join('')}</select>
          <span class="lit-meta">Prefix</span>
          <input type="text" value="${escHtml(s.prefix || '')}" placeholder="e.g. prov" onchange="updateStandard(${i}, {prefix: this.value.trim()})" />
          <span class="lit-meta">Namespace</span>
          <input type="text" value="${escHtml(s.namespace || '')}" placeholder="the IRI its terms live in, ending in # or /"
            onchange="updateStandard(${i}, {namespace: this.value.trim()})" />
          <span class="lit-meta">Download</span>
          <input type="text" value="${escHtml(s.download_url || '')}" placeholder="optional: direct link to a .ttl / .rdf file"
            onchange="updateStandard(${i}, {download_url: this.value.trim()})" />
        </div>
        <div style="margin-top:6px; font-size:0.8rem;" ${stop}>
          ${v ? `✅ Vocabulary loaded: ${v.classes} classes, ${v.properties} properties${v.truncated ? ' (truncated)' : ''}
                 <span class="lit-meta">from ${escHtml(v.source)}</span>`
              : s.decision === 'reference' ? '<span class="lit-meta">Reference only — nothing is loaded or used in the export.</span>'
              : `<span style="color:var(--warning);">Not loaded yet — later steps can only use terms of loaded vocabularies.</span>`}
          ${s.load_error && !v ? `<div style="color:var(--error);">${escHtml(s.load_error)}</div>` : ''}
          <div style="display:flex; gap:8px; margin-top:4px; flex-wrap:wrap;">
            ${s.decision !== 'reference' ? `<button class="oops-toggle" onclick="loadStandardVocabulary(${i})">${v ? '↻ Reload' : '⬇ Load vocabulary'}</button>
            <label class="oops-toggle" style="cursor:pointer;">⬆ Upload file<input type="file" accept=".ttl,.rdf,.owl,.xml,.jsonld,.nt" style="display:none"
              onchange="uploadStandardVocabulary(${i}, this.files[0])" /></label>` : ''}
            ${s.documentation_url || s.url ? `<a class="standard-url" href="${escHtml(s.documentation_url || s.url)}" target="_blank">🔗 documentation</a>` : ''}
            <button class="oops-toggle" onclick="removeStandard(${i})">✕ Remove</button>
          </div>
          <div id="sload-${i}" class="lit-meta"></div>
        </div>
      </div>
    </div>`; }).join('') + `
    <div class="standard-card" style="cursor:default; align-items:center;">
      <div class="standard-info">
        <div class="standard-name">Add a vocabulary</div>
        <div class="lit-meta">Upload an ontology or vocabulary file (Turtle, RDF/XML, JSON-LD); its namespace and terms are read from the file.</div>
        <label class="oops-toggle" style="cursor:pointer; display:inline-block; margin-top:6px;">⬆ Upload file<input type="file"
          accept=".ttl,.rdf,.owl,.xml,.jsonld,.nt" style="display:none" onchange="uploadStandardVocabulary(-1, this.files[0])" /></label>
        <div id="sload--1" class="lit-meta"></div>
      </div>
    </div>`;
  updateSelectedCount();
}

// Ein Vokabular behaelt seinen Prefix; nutzte das Projekt denselben, hat der Server den des Projekts geaendert
// (DECISIONS 99) - Konventionen in Schritt 4 nachziehen und sagen, was geschah.
function applyPrefixChange(d) {
  if (d.conventions && state.context) { state.context.conventions = d.conventions; renderContext(); }
  const c = d.prefix_change;
  if (!c || !c.new) return;
  document.getElementById('standardsStatus').innerHTML = `<div class="alert alert-info"><span>ℹ️</span><span>The prefix
    <strong>${escHtml(c.old)}</strong> belongs to a reused vocabulary, so your ontology's prefix changed from
    <strong>${escHtml(c.old)}</strong> to <strong>${escHtml(c.new)}</strong>. You can choose another one in step 4
    (Conventions).</span></div>`;
}
function applyStandards(list, selectNew) {
  const before = new Set(state.suggestedStandards.map(s => s.name));
  const chosen = new Set(state.selectedStandards.map(s => s.name));
  state.suggestedStandards = list;
  state.selectedStandards = list.filter(s => chosen.has(s.name) || (selectNew && !before.has(s.name)));
  renderStandards(list);
  document.getElementById('standardsContent').style.display = 'block';
  if (state.evaluation) renderEvaluation(state.evaluation);   // "Align with ..." haengt an den geladenen Vokabularen
}
async function standardsCall(path, body, i) {
  const out = document.getElementById('sload-' + i);
  try {
    const res = await fetch(`${API}/api/standards/${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: state.sessionId, ...body }) });
    const d = await res.json();
    if (!res.ok) throw new Error(d.detail || 'Request failed');
    applyStandards(d.standards, false);
    applyPrefixChange(d);
  } catch (e) {
    if (out) out.innerHTML = `<span style="color:var(--error);">${escHtml(e.message)}</span>`;
  }
}
function updateStandard(i, fields) { return standardsCall('update', { index: i, fields }, i); }
function removeStandard(i) {
  if (!confirm(`Remove ${state.suggestedStandards[i].name} and its loaded vocabulary?`)) return;
  return standardsCall('update', { index: i, remove: true }, i);
}
async function loadStandardVocabulary(i) {
  const out = document.getElementById('sload-' + i);
  if (out) out.innerHTML = '<span class="spinner" style="display:inline-block; width:12px; height:12px;"></span> Loading… (a large vocabulary can take a minute)';
  await standardsCall('load', { index: i }, i);
}
async function uploadStandardVocabulary(i, file) {
  if (!file) return;
  const out = document.getElementById('sload-' + i);
  if (out) out.textContent = 'Reading ' + file.name + '…';
  const fd = new FormData();
  fd.append('file', file);
  try {
    const res = await fetch(`${API}/api/standards/upload?session_id=${encodeURIComponent(state.sessionId)}&index=${i}`, { method: 'POST', body: fd });
    const d = await res.json();
    if (!res.ok) throw new Error(d.detail || 'Request failed');
    applyStandards(d.standards, true);
    applyPrefixChange(d);
  } catch (e) {
    const o = document.getElementById('sload-' + i);
    if (o) o.innerHTML = `<span style="color:var(--error);">${escHtml(e.message)}</span>`;
  }
}

function toggleStandard(i) {
  const card = document.getElementById('scard-' + i);
  const cb = document.getElementById('scb-' + i);
  const s = state.suggestedStandards[i];
  const idx = state.selectedStandards.findIndex(x => x.name === s.name);
  if (idx === -1) {
    state.selectedStandards.push(s);
    card.classList.add('selected');
    cb.checked = true;
  } else {
    state.selectedStandards.splice(idx, 1);
    card.classList.remove('selected');
    cb.checked = false;
  }
  updateSelectedCount();
}

// ── Custom Prefixes ────────────────────────────────────────────────────────────
async function addCustomPrefix() {
  const input = document.getElementById('customPrefixInput');
  const status = document.getElementById('prefixLookupStatus');
  const prefix = input.value.trim().toLowerCase();
  if (!prefix) return;
  if (state.customPrefixes && state.customPrefixes[prefix]) {
    status.textContent = `'${prefix}' already added.`;
    return;
  }
  status.textContent = '⏳ Looking up the URI…';
  try {
    const res = await fetch(`${API}/api/resolve-prefix?prefix=${encodeURIComponent(prefix)}`);
    if (!res.ok) {
      const err = await res.json();
      status.textContent = `❌ ${err.detail}`;
      return;
    }
    const data = await res.json();
    // In Session speichern
    const saved = await fetch(`${API}/api/session/add-prefix`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({session_id: state.sessionId, prefix: data.prefix, uri: data.uri})
    });
    const added = await saved.json();
    if (!saved.ok) { status.textContent = `❌ ${added.detail}`; return; }
    applyPrefixChange(added);
    if (!state.customPrefixes) state.customPrefixes = {};
    state.customPrefixes[data.prefix] = data.uri;
    input.value = '';
    status.textContent = '';
    renderCustomPrefixTags();
  } catch (e) {
    status.textContent = '❌ Network error';
  }
}

async function removeCustomPrefix(prefix) {
  await fetch(`${API}/api/session/remove-prefix?session_id=${state.sessionId}&prefix=${encodeURIComponent(prefix)}`, {method: 'DELETE'});
  delete state.customPrefixes[prefix];
  renderCustomPrefixTags();
}

function renderCustomPrefixTags() {
  saveProject();
  const container = document.getElementById('customPrefixTags');
  container.innerHTML = '';
  for (const [pfx, uri] of Object.entries(state.customPrefixes || {})) {
    const tag = document.createElement('div');
    tag.style.cssText = 'display:flex;align-items:center;gap:6px;background:var(--surface2);border:1px solid var(--border);border-radius:20px;padding:4px 10px;font-size:0.8rem;';
    tag.innerHTML = `<span style="color:var(--accent-light);font-weight:600;">${pfx}:</span><span style="color:var(--text-muted);max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${uri}">${uri}</span><button onclick="removeCustomPrefix('${pfx}')" style="background:none;border:none;color:var(--text-muted);cursor:pointer;padding:0;font-size:0.9rem;line-height:1;" title="Remove">✕</button>`;
    container.appendChild(tag);
  }
}

function toggleSelectAll(el) {
  state.suggestedStandards.forEach((s, i) => {
    const card = document.getElementById('scard-' + i);
    const cb = document.getElementById('scb-' + i);
    if (el.checked) {
      card.classList.add('selected');
      cb.checked = true;
    } else {
      card.classList.remove('selected');
      cb.checked = false;
    }
  });
  state.selectedStandards = el.checked ? [...state.suggestedStandards] : [];
  updateSelectedCount();
}

function updateSelectedCount() {
  saveProject();
  const n = state.selectedStandards.length;
  document.getElementById('selectedCount').textContent =
    n === 0 ? 'None selected' : `${n} selected`;
}

// ── Kernrelationen vor der Generierung (Schritt 7, DECISIONS 89) ──
async function proposeCoreRelations() {
  if (!state.llmConfig) { alert('Please configure the LLM first (Step 1).'); goTo(1); return; }
  await saveMomo();
  const st = () => document.getElementById('coreVocabStatus');
  if (st()) st().innerHTML = `<div class="alert alert-info"><div class="spinner"></div><span>Proposing core relations from your
    competency questions, key notions${state.corpus && state.corpus.inventory ? ' and the relations of the literature' : ''}…</span></div>`;
  try {
    const res = await fetch(`${API}/api/properties/propose`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: state.sessionId, llm_config: state.llmConfig, before_generation: true }),
    });
    const d = await res.json();
    if (!res.ok) throw new Error(d.detail || 'Request failed');
    recordUsage(d.usage, false);
    state.propertyVocab = d.property_vocab;
    renderPropertyVocab();
    renderMomoReadiness();
    saveProject();
  } catch (e) {
    if (st()) st().innerHTML = `<div class="alert alert-error"><span>❌</span><span>Error: ${escHtml(e.message)}</span></div>`;
  }
}
async function approveCoreRelations() {
  if (!await saveVocab({ approve: true })) return;
  renderPropertyVocab();
  renderMomoReadiness();
}
async function reproposeCoreRelations() {
  if (!confirm('Replace these core relations with a new proposal (one model call)? Your changes to them are lost.')) return;
  await proposeCoreRelations();
}
async function switchOffCoreRelations() {
  if (state.propertyVocab && state.propertyVocab.status !== 'off' &&
      !confirm('Generate without core relations? The current proposal is discarded; every module then defines its own properties.')) return;
  const res = await fetch(`${API}/api/properties/vocab`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: state.sessionId, off: true }),
  });
  if (res.ok) state.propertyVocab = (await res.json()).property_vocab;
  renderPropertyVocab();
  renderMomoReadiness();
}

function propertyRunSummary(sm) {
  const c = sm.core, b = c.before || {}, a = c.after || {}, cq = sm.cq;
  return `<div class="lit-meta">Object properties ${b.object_properties} → ${a.object_properties ?? '?'} ·
      relations ${b.relations} → ${a.relations ?? '?'} · top-level relations ${b.top_level_relations} → ${a.top_level_relations ?? '?'} ·
      ${a.properties_with_superproperty ?? 0} below a core relation · ${a.properties_with_characteristics ?? 0} with characteristics</div>
    ${(c.rejected || []).length ? `<div style="color:var(--warning);">⚠️ Core relations not created: ${escHtml(c.rejected.join('; '))}</div>` : ''}
    ${cq ? (cq.tested ? `<div>${(cq.regressions || []).length
        ? `<span style="color:var(--warning);">⚠️ ${cq.regressions.length} competency question${cq.regressions.length !== 1 ? 's' : ''} no longer pass —
           meaning may have been lost: ${escHtml(cq.regressions.join(' · '))}</span>`
        : `✓ Competency questions: ${cq.passed_after} of ${cq.total} pass${cq.passed_before != null ? ` (before: ${cq.passed_before})` : ''}, none lost.`}
        ${cq.translated ? `<span class="lit-meta"> ${cq.translated} sample triples and queries were carried over through ${cq.merged} merged properties.</span>` : ''}</div>`
      : `<div class="lit-meta">Competency questions not re-tested: ${escHtml(cq.reason || '')}</div>`) : ''}`;
}

// Entscheidungen der uebrigen Verbesserungsaktionen (DECISIONS 76): was das Modell nicht angewendet hat, mit Begruendung
const DECISION_TITLES = { hierarchy: 'Build hierarchy — relations and taxonomies not applied',
  upper: 'Group root classes — left at the top level', properties: 'Consolidate properties — kept as they are',
  align: 'Align with vocabularies — not linked' };
function decisionsSection(decisions) {
  const kinds = Object.keys(DECISION_TITLES).filter(k => decisions && (decisions[k] || []).length);
  if (!kinds.length) return '';
  return `<h4>Decisions of the improvement actions</h4>
    <div class="lit-meta">Made by the model while improving; not proposed again. Reconsider an entry to have it proposed by the next run.</div>
    ${kinds.map(k => `<details style="margin:4px 0;"><summary style="cursor:pointer;">${DECISION_TITLES[k]} (${decisions[k].length})</summary>
      <button class="oops-toggle" onclick="reconsiderDecision('${k}', null)">↺ Reconsider all ${decisions[k].length}</button>
      <ul class="lit-sources">${decisions[k].map((d, i) => `<li><strong>${escHtml(d.item)}</strong>${d.reason ? `: ${escHtml(d.reason)}` : ''}
        <button class="oops-toggle" onclick="reconsiderDecision('${k}', ${i})">↺ Reconsider</button></li>`).join('')}</ul></details>`).join('')}`;
}
async function reconsiderDecision(kind, index) {
  const list = (state.evaluation.decisions || {})[kind] || [];
  if (index === null && !confirm(`Reconsider all ${list.length} entries? The next run proposes them again.`)) return;
  try {
    const res = await fetch(`${API}/api/gaps/reconsider`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: state.sessionId, kind, all: index === null, keys: index === null ? [] : [list[index].key] }),
    });
    const d = await res.json();
    if (!res.ok) throw new Error(d.detail || 'Request failed');
    if (!d.evaluation) { alert(`${d.removed} decision(s) withdrawn. Evaluate again to see the updated counts.`); return; }
    const open = [...document.querySelectorAll('#evalReport details')].map(x => x.open);
    state.evaluation = d.evaluation;
    renderEvaluation(state.evaluation);
    [...document.querySelectorAll('#evalReport details')].forEach((x, i) => { if (open[i]) x.open = true; });
    saveProject();
  } catch (e) {
    alert('Error: ' + e.message);
  }
}

// Entscheidung "nicht modelliert" zuruecknehmen (index in decided_central, null = alle)
async function reconsiderDeclined(index) {
  const decided = (state.evaluation && state.evaluation.coverage.decided_central) || [];
  const all = index === null;
  if (all && !confirm(`Reconsider all ${state.evaluation.coverage.central_decided} declined concepts? They count as missing again and are proposed by the next "Add missing central concepts".`)) return;
  try {
    const res = await fetch(`${API}/api/gaps/reconsider`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: state.sessionId, all, labels: all ? [] : [decided[index].label] }),
    });
    const d = await res.json();
    if (!res.ok) throw new Error(d.detail || 'Request failed');
    if (!d.evaluation) { alert(`${d.removed} decision(s) withdrawn. Evaluate again to see the updated coverage.`); return; }
    state.evaluation = d.evaluation;
    renderEvaluation(state.evaluation);
    const det = document.querySelector('#evalReport details');
    if (det) det.open = true;   // die Liste nicht wegklappen, wenn man einzeln zuruecknimmt
    saveProject();
  } catch (e) {
    alert('Error: ' + e.message);
  }
}

let gapRun = null;   // laufende Aktion: { kind, total, done, stop }

async function startGapRun(kind) {
  openRepairTools();
  if (!state.llmConfig) { alert('Please configure the LLM first (Step 1).'); goTo(1); return; }
  if (gapRun) return;
  // die Sperre vor dem ersten await setzen; finally gibt sie wieder frei
  gapRun = { kind, total: 0, done: 0, stop: false, applied: 0, failed: 0, errors: [] };
  const el = document.getElementById('gapRun');
  const label = { concepts: 'Adding missing central concepts', hierarchy: 'Building the hierarchy from the literature',
                  upper: 'Grouping the root classes under the upper layer',
                  properties: 'Consolidating the properties into the core relations',
                  align: 'Aligning with the loaded vocabularies',
                  restrictions: 'Adding class restrictions' }[kind];
  try {
    await saveMomo();
    const call = async dry_run => {
      const res = await fetch(`${API}/api/gaps/start`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: state.sessionId, kind, dry_run }),
      });
      const d = await res.json();
      if (!res.ok) throw new Error(d.detail || 'Request failed');
      return d;
    };
    const preview = await call(true);
    if (!preview.batches && kind !== 'properties') { el.innerHTML = `<div class="alert alert-info"><span>ℹ️</span><span>Nothing left to do.</span></div>`; return; }
    if (!confirm(preview.batches ? `${label}: ${preview.items} items in ${preview.batches} model calls (plus an OOPS! check at the end${
      kind === 'properties' ? ' and a re-test of your competency questions' : ''}). Continue?`
      : `${label}: no properties left to assign; the core relations are created or updated, then an OOPS! check and a re-test of your competency questions. Continue?`)) return;
    const start = await call(false);
    const before = JSON.parse(JSON.stringify(state.currentOntology));
    state.iteration = start.iteration;
    gapRun.total = start.batches;
    const progress = () => {
      const pctDone = Math.round(100 * gapRun.done / gapRun.total);
      el.innerHTML = `<div class="alert alert-info" style="flex-direction:column; align-items:stretch;">
        <div style="display:flex; gap:10px; align-items:center;"><div class="spinner"></div><span>${label}: package ${Math.min(gapRun.done + 1, gapRun.total)} of ${gapRun.total}
          · ${gapRun.applied} changes so far${gapRun.failed ? ` · ${gapRun.failed} packages failed` : ''}${gapRun.stop ? ' · stopping after this package…' : ''}</span>
          <button class="oops-toggle" style="margin-left:auto;" onclick="gapRun && (gapRun.stop = true)">■ Stop</button></div>
        <div class="lit-progress"><div style="width:${pctDone}%"></div></div></div>`;
    };
    for (let i = 0; i < start.batches && !gapRun.stop; i++) {
      progress();
      try {
        const r = await fetch(`${API}/api/gaps/step`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id: state.sessionId, llm_config: state.llmConfig, index: i }),
        });
        const d = await r.json();
        if (!r.ok) { const err = new Error(d.detail || 'Request failed'); err.status = r.status; throw err; }
        recordUsage(d.usage, false);
        gapRun.applied += d.edit_report.applied.length;
        state.currentOntology = d.ontology;
        state.currentTurtle = d.turtle;
      } catch (e) {
        gapRun.failed++;
        gapRun.errors.push(`package ${i + 1}: ${e.message}`);   // show why, not only how many
        // a reached limit or a refused key will fail every further package too: stop instead of trying them all
        if (e.status === 429 || e.status === 401) { gapRun.stop = true; gapRun.errors.push('Stopped: the remaining packages were not sent.'); }
      }
      gapRun.done++;
    }
    el.innerHTML = `<div class="alert alert-info"><div class="spinner"></div><span>Finishing: OOPS! quality check…</span></div>`;
    const f = await fetch(`${API}/api/gaps/finish`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: state.sessionId, llm_config: state.llmConfig }),
    });
    const fin = await f.json();
    if (!f.ok) throw new Error(fin.detail || 'Request failed');
    recordUsage(fin.usage, false);
    state.currentOntology = fin.ontology;
    state.currentTurtle = fin.turtle;
    state.iteration = fin.iteration;
    computeAndShowDiff(before, fin.ontology);
    renderOntology(fin.ontology, fin.turtle, fin.iteration);
    if (fin.oops_report) { renderValidationBadge(fin.oops_report.validation); renderOopsReport(fin.oops_report); }
    const sm = fin.summary, run = gapRun;
    el.innerHTML = `<div class="alert ${run.failed ? 'alert-error' : 'alert-success'}" style="flex-direction:column; align-items:flex-start; gap:4px;">
      <div>${run.failed ? '⚠️' : '✅'} ${label}: ${sm.applied} changes applied in ${run.done} of ${run.total} packages${run.stop ? ' (stopped)' : ''}${run.failed ? `, ${run.failed} packages failed` : ''}.
        Evaluate again to see the effect.</div>
      ${run.errors.length ? `<div style="color:var(--error);">${run.errors.map(escHtml).join('<br>')}<br><span class="lit-meta">The items of failed packages were not decided; run the action again to retry them.</span></div>` : ''}
      ${sm.reverted.length ? `<div style="color:var(--warning);">⚠️ ${sm.reverted.length} package${sm.reverted.length !== 1 ? 's were' : ' was'} rolled back
        because the changes would have made classes unsatisfiable (and the model could not resolve it):
        ${sm.reverted.map(r => `package ${r.package}: ${escHtml(r.unsatisfiable.slice(0, 6).join(', '))}`).join('; ')}</div>` : ''}
      ${sm.reasoner_checked ? '' : `<div class="lit-meta">The changes were not checked with the reasoner (Java missing or the check failed).</div>`}
      ${sm.upper ? `<div class="lit-meta">Upper layer: ${sm.upper.created.length ? `created ${escHtml(sm.upper.created.join(', '))}` : 'nothing created'}${sm.upper.reused.length
        ? `; existing class${sm.upper.reused.length !== 1 ? 'es' : ''} ${escHtml(sm.upper.reused.join(', '))} used as ${sm.upper.reused.length !== 1 ? 'upper classes' : 'an upper class'}` : ''}.</div>` : ''}
      ${sm.kind === 'upper' && (sm.summaries || []).length ? `<details><summary style="cursor:pointer;">What the model says about each package (classes that mix two kinds are candidates for splitting)</summary>
        <ul class="lit-sources">${sm.summaries.map(s => `<li>${escHtml(s)}</li>`).join('')}</ul></details>` : ''}
      ${sm.core ? propertyRunSummary(sm) : ''}
      ${sm.skipped.length ? `<details><summary style="cursor:pointer;">${sm.skipped.length} ${kind === 'properties' ? 'kept as they are' : 'deliberately not modeled'} — recorded, not proposed again</summary>
        <ul class="lit-sources">${sm.skipped.map(s => `<li><strong>${escHtml(s.item)}</strong>: ${escHtml(s.reason)}</li>`).join('')}</ul></details>` : ''}
    </div>`;
    if (fin.cq_tests) { state.cqTests = fin.cq_tests; renderCQReport(fin.cq_tests); }   // already re-tested on the server
    else runCQTests();
    if (kind === 'properties') { state.propertyVocab = { ...(state.propertyVocab || {}), status: 'applied' }; state.vocabPanelOpen = false; renderPropertyVocab(); }
    renderEvaluation(state.evaluation);
    saveProject();
  } catch (e) {
    el.innerHTML = `<div class="alert alert-error"><span>❌</span><span>Error: ${escHtml(e.message)}</span></div>`;
  } finally {
    gapRun = null;
  }
}

// Evaluate 3x (DECISIONS 124): im leeren Zustand und unter einem Bericht derselbe Knopf
const EVAL_3X_TITLE = 'A single test varies by up to 2 of 10 questions; three runs show whether a change is real';
function evaluate3x() {
  if (confirm('Test your and the hold-out questions three times, each with new sample data and queries, for the mean and ' +
              'spread? This costs three times the tokens of one CQ test (for a large project several hundred thousand).'))
    runEvaluation(true, 3);
}

async function runEvaluation(fresh, repeats = 1) {
  // Fortschritt und Ergebnis stehen im Reiter Overview: dorthin wechseln, auch wenn der Knopf aus einem anderen
  // Reiter kam (v0.2-Durchlauf: aus "Repair tools" sah man nicht, dass die Evaluation lief)
  if (typeof showRefineTab === 'function') showRefineTab('overview');
  const el = document.getElementById('evalReport');
  el.style.display = 'block';
  el.innerHTML = `<div class="alert alert-info"><div class="spinner"></div><span>Evaluating: competency questions (yours and
    from the literature) as SPARQL tests${repeats > 1 ? `, ${repeats} times from scratch,` : ''} inventory coverage,
    traceability, structure and the HermiT reasoner…</span></div>`;
  try {
    await saveMomo();
    const res = await fetch(`${API}/api/evaluate`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: state.sessionId, llm_config: state.llmConfig || null, fresh: !!fresh, repeats }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Request failed');
    recordUsage(data.usage, false);
    if (data.cq_tests) { state.cqTests = data.cq_tests; renderCQReport(data.cq_tests); }
    const { cq_tests, usage, ...report } = data;
    state.evaluation = report;
    saveProject();
    renderEvaluation(report);
  } catch (e) {
    el.innerHTML = `<div class="oops-banner info"><div style="font-weight:700; margin-bottom:4px;">📊 Evaluation</div>
      <div>The evaluation could not be run: ${escHtml(e.message)}</div>
      <button class="oops-toggle" onclick="runEvaluation()">↻ Retry</button></div>`;
  }
}

function downloadEvaluation() {
  const name = (state.currentOntology?.ontology_name || 'ontology').replace(/\s+/g, '_');
  const blob = new Blob([JSON.stringify({ ontology: state.currentOntology?.ontology_name, ...state.evaluation }, null, 2)],
                        { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `${name}.evaluation-iteration-${state.evaluation.iteration}.json`;
  document.body.appendChild(a); a.click(); a.remove();
}

function toggleOopsList() {
  const list = document.getElementById('oopsList');
  const btn  = document.getElementById('oopsToggleBtn');
  if (!list) return;
  const hidden = list.style.display === 'none';
  list.style.display = hidden ? 'flex' : 'none';
  btn.textContent = hidden ? '▼ Hide details' : '▶ Show details';
}
