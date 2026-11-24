// Schritt 3: Literatur, Begriffsinventar, Begriffstabellen
// (PLAN.md Phase 4: eine Datei je Schritt; klassische Skripte - alle Funktionen sind global,
// sofort ausgefuehrt wird nur main.js, das zuletzt laedt)

// ── Schritt 3: Literatur (Panel 8) ─────────────────────────────────────────────
// Jedes Paper wird einzeln zu einer Paper Card verdichtet (mehrere Anfragen parallel, der Server haelt keinen
// Hintergrundjob), danach fuehrt der Server alle Cards zum Begriffsinventar zusammen.
const LIT_CONCURRENCY = 3;
const LIT_UPLOAD_BATCH = 4;
const LIT_TABLE_ROWS = 150;
let litRun = null;           // laufende Extraktion: { stop, total, done, failed }
const litOpen = new Set();   // aufgeklappte Paper Cards
let litTab = 'concepts', litFilter = '', litShowAll = false, litCover = 'all';
const litOpenConcepts = new Set();

function corpus() {
  state.corpus = state.corpus || { docs: [], inventory: null };
  return state.corpus;
}

async function proceedToLiterature() {
  if (!document.getElementById('domainDesc').value.trim()) {
    alert('Please describe the use case first — it tells the extraction which concepts are relevant.'); return;
  }
  await saveMomo();
  goTo(8);
  renderLiterature();
}

async function uploadPapers(fileList) {
  const files = Array.from(fileList || []);
  if (!files.length) return;
  const st = document.getElementById('litUploadStatus');
  const skipped = [];
  let added = 0;
  try {
    // In kleinen Paketen, damit bei 60 PDFs ein Fortschritt sichtbar ist
    for (let i = 0; i < files.length; i += LIT_UPLOAD_BATCH) {
      st.innerHTML = `<div class="alert alert-info"><div class="spinner"></div><span>Reading papers
        ${i + 1}–${Math.min(i + LIT_UPLOAD_BATCH, files.length)} of ${files.length}…</span></div>`;
      const fd = new FormData();
      files.slice(i, i + LIT_UPLOAD_BATCH).forEach(f => fd.append('files', f));
      const res = await fetch(`${API}/api/corpus/upload?session_id=${state.sessionId}`, { method: 'POST', body: fd });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Upload failed');
      corpus().docs = data.docs;
      added += data.added.length;
      skipped.push(...data.skipped);
      renderLitDocs();
    }
    st.innerHTML = `<div class="alert ${skipped.length ? 'alert-info' : 'alert-success'}" style="align-items:flex-start;">
      <span>${skipped.length ? 'ℹ️' : '✅'}</span><span>${added} paper${added !== 1 ? 's' : ''} added.
      ${skipped.length ? '<br>Not added: ' + skipped.map(s => `${escHtml(s.name)} — ${escHtml(s.reason)}`).join('; ') : ''}</span></div>`;
  } catch (e) {
    st.innerHTML = `<div class="alert alert-error"><span>❌</span><span>Error: ${escHtml(e.message)}</span></div>`;
  } finally {
    document.getElementById('litFileInput').value = '';
    renderLiterature();
  }
}

async function removePaper(id) {
  const doc = corpus().docs.find(d => d.id === id);
  if (!doc || !confirm(`Remove "${doc.name}" and its paper card from the corpus?`)) return;
  const res = await fetch(`${API}/api/corpus/remove`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: state.sessionId, doc_id: id }),
  });
  const data = await res.json();
  if (!res.ok) { alert('Error: ' + (data.detail || 'Request failed')); return; }
  corpus().docs = data.docs;
  litOpen.delete(id);
  renderLiterature();
}

function addSessionUsage(usage) {
  if (!usage) return;
  state.usageSession = state.usageSession || { input: 0, output: 0, calls: 0, unknown: 0 };
  state.usageSession.input += usage.input_tokens;
  state.usageSession.output += usage.output_tokens;
  state.usageSession.calls += usage.calls.length;
  state.usageSession.unknown += usage.unknown_calls;
  saveProject();
}

async function extractPapers(ids) {
  if (!state.llmConfig) { alert('Please configure the LLM first (Step 1).'); goTo(1); return; }
  if (litRun) return;
  // die Sperre vor dem ersten await setzen: sonst startet ein zweiter Klick einen zweiten Lauf
  const run = litRun = { stop: false, total: 0, done: 0, failed: 0, active: new Set() };
  await saveMomo();
  const queue = ids || corpus().docs.filter(d => isPaper(d) && d.status !== 'done').map(d => d.id);
  if (!queue.length) { litRun = null; return; }
  run.total = queue.length;
  renderLiterature();
  const worker = async () => {
    while (queue.length && !run.stop) {
      const id = queue.shift();
      run.active.add(id);
      renderLitDocs();
      try {
        const res = await fetch(`${API}/api/corpus/extract`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id: state.sessionId, doc_id: id, llm_config: state.llmConfig }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Request failed');
        const i = corpus().docs.findIndex(d => d.id === id);
        if (i >= 0) corpus().docs[i] = data.doc;
        addSessionUsage(data.usage);
        run.done++;
      } catch (e) {
        const doc = corpus().docs.find(d => d.id === id);
        if (doc) { doc.status = 'error'; doc.error = e.message; }
        run.failed++;
      }
      run.active.delete(id);
      renderLiterature();
    }
  };
  await Promise.all(Array.from({ length: Math.min(LIT_CONCURRENCY, queue.length) }, worker));
  litRun = null;
  if (run.done) markDone(8);
  renderLiterature();
  document.getElementById('litProgress').innerHTML = `<div class="alert ${run.failed ? 'alert-error' : 'alert-success'}">
    <span>${run.failed ? '⚠️' : '✅'}</span><span>${run.done} paper card${run.done !== 1 ? 's' : ''} extracted${run.failed ?
    `, ${run.failed} failed — retry them with ✨ Extract paper cards` : ''}${run.stop ? ' (stopped)' : ''}.</span></div>`;
}

function stopExtraction() {
  if (!litRun) return;
  litRun.stop = true;
  document.getElementById('litStopBtn').disabled = true;
  renderLitProgress();
}

function renderLiterature() {
  renderLitDocs();
  renderLitProgress();
  renderInventory();
}

function litTokens() {
  const c = corpus();
  const parts = [...c.docs.map(d => d.usage), c.inventory && c.inventory.usage].filter(Boolean);
  return { input: parts.reduce((a, u) => a + (u.input_tokens || 0), 0), output: parts.reduce((a, u) => a + (u.output_tokens || 0), 0) };
}

function renderLitProgress() {
  const docs = corpus().docs;
  const done = docs.filter(d => d.status === 'done').length;
  const failed = docs.filter(d => d.status === 'error').length;
  const pending = docs.filter(d => isPaper(d) && d.status !== 'done').length;
  const btn = document.getElementById('litExtractBtn');
  btn.style.display = litRun ? 'none' : '';
  btn.disabled = !pending;
  btn.textContent = pending ? `Extract paper cards (${pending})` : 'Extract paper cards';
  const stop = document.getElementById('litStopBtn');
  stop.style.display = litRun ? '' : 'none';
  if (!litRun) stop.disabled = false;
  const tok = litTokens();
  document.getElementById('litCount').textContent = docs.length
    ? `· ${docs.length} · ${done} extracted${failed ? ` · ${failed} failed` : ''}` +
      (tok.input ? ` · ${tok.input.toLocaleString('en-US')} input / ${tok.output.toLocaleString('en-US')} output tokens` : '')
    : '';
  if (!litRun) return;
  const r = litRun;
  const pct = Math.round(100 * (r.done + r.failed) / r.total);
  document.getElementById('litProgress').innerHTML = `
    <div class="lit-progress"><div style="width:${pct}%"></div></div>
    <p class="ctx-hint">${r.done + r.failed} of ${r.total} papers processed${r.failed ? ` (${r.failed} failed)` : ''} ·
    ${r.stop ? 'stopping after the papers in progress…' : `${r.active.size} in progress`}</p>`;
}

function isPaper(d) { return (d.source_type || 'paper') === 'paper'; }
const LIT_ICON = { paper: '📄', ontology: '🧬', glossary: '📋' };

function litDocMeta(d) {
  const bits = [];
  if (!isPaper(d)) {
    const s = (d.card && d.card.stats) || {};
    if (d.source_type === 'ontology') bits.push(`${s.classes || 0} classes · ${s.properties || 0} properties`);
    else if (s.rows != null) bits.push(`${s.rows.toLocaleString('en-US')} rows`);
    if (s.truncated) bits.push('⚠ only the first 1,500 concepts are used');
    return bits.join(' · ') || 'concept table';
  }
  if (d.pages) bits.push(`${d.pages} p.`);
  bits.push(`${Math.round(d.chars / 1000)}k chars`);
  if (d.truncated) bits.push('⚠ only the first 200k chars are read');
  return bits.join(' · ');
}

function renderLitDocs() {
  const docs = corpus().docs;
  const el = document.getElementById('litDocs');
  if (!docs.length) { el.innerHTML = '<p class="ctx-hint">No papers yet.</p>'; return; }
  el.innerHTML = `<div class="lit-scroll">${docs.map(d => {
    const active = litRun && litRun.active.has(d.id);
    const card = d.card;
    let status;     // als Text: die Liste ist auch ohne Farben lesbar (DECISIONS 126)
    if (active) status = '<span class="pill neutral" style="display:inline-flex; gap:6px; align-items:center;"><span class="spinner" style="width:11px;height:11px;"></span>reading</span>';
    else if (d.status === 'done') status = '<span class="pill ok">extracted</span>';
    else if (d.status === 'error') status = '<span class="pill bad">failed</span>';
    else if (d.status === 'mapping') status = '<span class="pill warn">columns</span>';
    else status = '<span class="pill neutral">pending</span>';
    const nQuotes = card ? card.concepts.filter(c => c.quote).length : 0;
    const okQuotes = card ? card.concepts.filter(c => c.quote_ok).length : 0;
    let summary;
    if (d.status === 'mapping') summary = 'confirm the columns below';
    else if (!card) summary = litDocMeta(d);
    else if (isPaper(d)) summary = `${card.concepts.length} concepts · ${okQuotes}/${nQuotes} quotes found in the text`;
    else summary = `${card.concepts.length} concepts${card.relations.length ? ` · ${card.relations.length} relations` : ''}`;
    const title = card && card.title ? card.title : d.name;
    const type = d.source_type || 'paper';
    const showMapping = type === 'glossary' && d.mapping && (d.status === 'mapping' || litRemap.has(d.id));
    return `<div class="lit-doc">
      <div class="lit-row">
        <span style="width:86px; flex-shrink:0;">${status}</span>
        <span class="lit-type" style="width:64px; flex-shrink:0;">${{ paper: 'paper', ontology: 'ontology', glossary: 'table' }[type]}</span>
        <span class="lit-name" title="${escHtml(d.name)}">${escHtml(title)}${card && card.year ? ` <span class="lit-meta">(${escHtml(card.year)})</span>` : ''}</span>
        <span class="lit-meta">${escHtml(summary)}</span>
        ${card ? `<button onclick="toggleLitCard('${d.id}')">${litOpen.has(d.id) ? '▼ Card' : '▶ Card'}</button>` : ''}
        ${type === 'paper' && !active && !litRun && d.status === 'done' ? `<button title="Extract again" onclick="extractPapers(['${d.id}'])">↻</button>` : ''}
        ${type === 'glossary' && d.status === 'done' ? `<button title="Change the column assignment" onclick="toggleRemap('${d.id}')">Columns</button>` : ''}
        ${!active ? `<button title="Remove from the corpus" aria-label="Remove ${escHtml(d.name)}" onclick="removePaper('${d.id}')">✕</button>` : ''}
      </div>
      ${d.status === 'error' && !active ? `<div class="lit-card" style="color:var(--error)">${escHtml(d.error)}</div>` : ''}
      ${showMapping ? renderColumnMapping(d) : ''}
      ${card && litOpen.has(d.id) ? renderLitCard(d) : ''}
    </div>`;
  }).join('')}</div>`;
}

// ── Begriffstabellen: Spaltenzuordnung ──
const LIT_ROLES = [['term', 'Term *'], ['definition', 'Definition'], ['broader', 'Broader term'],
                   ['synonyms', 'Synonyms (separated by ; or |)'], ['uri', 'URI']];
const litRemap = new Set();
const litMapDraft = {};   // docId -> { sheet, columns }

function toggleRemap(id) { litRemap.has(id) ? litRemap.delete(id) : litRemap.add(id); renderLitDocs(); }

function mapDraft(d) {
  if (!litMapDraft[d.id]) {
    const chosen = d.mapping.chosen;
    const sheet = chosen ? chosen.sheet : Object.keys(d.mapping.sheets)[0];
    litMapDraft[d.id] = { sheet, columns: chosen ? { ...chosen.columns } : { ...d.mapping.sheets[sheet].guess } };
  }
  return litMapDraft[d.id];
}

function setMapSheet(id, sheet) {
  const d = corpus().docs.find(x => x.id === id);
  litMapDraft[id] = { sheet, columns: { ...d.mapping.sheets[sheet].guess } };
  renderLitDocs();
}

function setMapColumn(id, role, value) {
  litMapDraft[id].columns[role] = value === '' ? null : +value;
  renderLitDocs();
}

function renderColumnMapping(d) {
  const draft = mapDraft(d);
  const sheets = Object.keys(d.mapping.sheets);
  const s = d.mapping.sheets[draft.sheet];
  const opts = role => `<option value="">— none —</option>` + s.header.map((h, i) =>
    `<option value="${i}" ${draft.columns[role] === i ? 'selected' : ''}>${escHtml(h)}</option>`).join('');
  const roleOf = i => (LIT_ROLES.find(([r]) => draft.columns[r] === i) || [])[0];
  const sample = s.sample.map(r => `<tr>${r.map((v, i) => `<td style="${roleOf(i) ? '' : 'color:var(--text-muted)'}">${escHtml(v.length > 80 ? v.slice(0, 80) + '…' : v)}</td>`).join('')}</tr>`).join('');
  return `<div class="lit-card">
    <p class="ctx-hint">Which columns hold what? The suggestion comes from the column headers — check it against the example rows.</p>
    ${sheets.length > 1 ? `<div style="margin-bottom:8px;"><span class="ctx-field">Sheet</span>
      <select onchange="setMapSheet('${d.id}', this.value)">${sheets.map(n => `<option ${n === draft.sheet ? 'selected' : ''}>${escHtml(n)}</option>`).join('')}</select></div>` : ''}
    <div class="ctx-grid" style="margin-bottom:10px;">${LIT_ROLES.map(([role, label]) => `<div><span class="ctx-field">${label}</span>
      <select onchange="setMapColumn('${d.id}', '${role}', this.value)">${opts(role)}</select></div>`).join('')}</div>
    <div style="overflow:auto; margin-bottom:10px;"><table class="lit-table">
      <thead><tr>${s.header.map((h, i) => `<th>${escHtml(h)}${roleOf(i) ? ` <span class="lit-pill">${roleOf(i)}</span>` : ''}</th>`).join('')}</tr></thead>
      <tbody>${sample}</tbody></table></div>
    <span class="lit-meta">${s.total_rows.toLocaleString('en-US')} rows</span>
    <button class="btn btn-primary btn-sm" style="margin-left:10px;" onclick="applyColumnMapping('${d.id}')">Use these columns</button>
  </div>`;
}

async function applyColumnMapping(id) {
  const draft = litMapDraft[id];
  if (draft.columns.term == null) { alert('Choose the column that holds the terms.'); return; }
  const res = await fetch(`${API}/api/corpus/map-columns`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: state.sessionId, doc_id: id, sheet: draft.sheet, columns: draft.columns }),
  });
  const data = await res.json();
  if (!res.ok) { alert('Error: ' + (data.detail || 'Request failed')); return; }
  const i = corpus().docs.findIndex(d => d.id === id);
  corpus().docs[i] = data.doc;
  litRemap.delete(id);
  litOpen.add(id);
  markDone(8);
  renderLiterature();
}

function toggleLitCard(id) {
  litOpen.has(id) ? litOpen.delete(id) : litOpen.add(id);
  renderLitDocs();
}

function litPage(p) { return p ? `p. ${p}` : ''; }

function renderLitCard(d) {
  const c = d.card;
  const quote = x => x.quote
    ? `<div class="lit-quote">“${escHtml(x.quote)}” ${x.quote_ok ? '<span class="lit-ok" title="Found verbatim in the paper">✓</span>'
        : '<span class="lit-warn" title="Not found verbatim in the paper — check the definition">⚠ not found in text</span>'}</div>` : '';
  const concepts = c.concepts.map(x => `<tr>
      <td><strong>${escHtml(x.term)}</strong>${x.synonyms.length ? `<div class="lit-meta">${escHtml(x.synonyms.join(', '))}</div>` : ''}
        ${x.uri ? `<div class="lit-meta" style="word-break:break-all;">${escHtml(x.uri)}</div>` : ''}</td>
      <td>${escHtml(x.definition)}${quote(x)}</td>
      <td>${escHtml(x.broader)}</td><td class="lit-meta">${litPage(x.page)}</td></tr>`).join('');
  return `<div class="lit-card">
    <div style="margin-bottom:6px;">${escHtml(c.authors)}${c.contribution ? ` <span class="lit-pill">${escHtml(c.contribution)}</span>` : ''}
      <span class="lit-meta">· ${escHtml(d.name)} · ${escHtml(litDocMeta(d))}</span></div>
    ${c.scope ? `<div style="margin-bottom:8px;">${escHtml(c.scope)}</div>` : ''}
    ${c.namespace ? `<div class="lit-meta" style="margin-bottom:8px;">Namespace: ${escHtml(c.namespace)}</div>` : ''}
    <h4>Concepts (${c.concepts.length})</h4>
    <table class="lit-table"><thead><tr><th style="width:22%">Term</th><th>Definition</th><th style="width:16%">Broader</th><th style="width:7%">Page</th></tr></thead>
      <tbody>${concepts || '<tr><td colspan="4">—</td></tr>'}</tbody></table>
    ${c.relations.length ? `<h4>Relations</h4>${c.relations.map(r =>
        `<div>${escHtml(r.subject)} <span style="color:var(--accent-light)">${escHtml(r.relation)}</span> ${escHtml(r.object)} <span class="lit-meta">${litPage(r.page)}</span></div>`).join('')}` : ''}
    ${c.taxonomies.length ? `<h4>Taxonomies</h4>${c.taxonomies.map(t =>
        `<div style="margin-bottom:4px;"><strong>${escHtml(t.name)}</strong> <span class="lit-meta">${litPage(t.page)}</span><br>${t.categories.map(x => `<span class="lit-pill">${escHtml(x)}</span>`).join('')}</div>`).join('')}` : ''}
    ${c.competency_questions.length ? `<h4>Candidate competency questions</h4>${c.competency_questions.map(q => `<div>• ${escHtml(q)}</div>`).join('')}` : ''}
    ${c.vocabularies.length ? `<h4>Vocabularies</h4>${c.vocabularies.map(v => `<span class="lit-pill" title="${escHtml(v.uri)}">${escHtml(v.name)}</span>`).join('')}` : ''}
  </div>`;
}

async function buildInventory() {
  if (!state.llmConfig) { alert('Please configure the LLM first (Step 1).'); goTo(1); return; }
  if (!corpus().docs.some(d => d.status === 'done')) { alert('Extract paper cards first.'); return; }
  const st = document.getElementById('litInventoryStatus');
  const btn = document.getElementById('litInventoryBtn');
  btn.disabled = true;
  st.innerHTML = `<div class="alert alert-info"><div class="spinner"></div><span>Merging the paper cards: grouping synonyms,
    finding conflicting definitions and themes…</span></div>`;
  try {
    await saveMomo();
    const res = await fetch(`${API}/api/corpus/inventory`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: state.sessionId, llm_config: state.llmConfig }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Request failed');
    corpus().inventory = data.inventory;
    addSessionUsage(data.usage);
    st.innerHTML = '';
    litTab = 'concepts';
    markDone(8);
  } catch (e) {
    st.innerHTML = `<div class="alert alert-error"><span>❌</span><span>Error: ${escHtml(e.message)}</span></div>`;
  } finally {
    btn.disabled = false;
    renderLiterature();
  }
}

function litDocLabel(id) {
  const d = corpus().docs.find(x => x.id === id);
  if (!d) return id;
  const c = d.card || {};
  if (!isPaper(d)) return `${LIT_ICON[d.source_type]} ${c.title || d.name}`;
  const author = (c.authors || '').split(/[,;]| and /)[0].trim().split(/\s+/).pop();
  return author && c.year ? `${author} ${c.year}` : (c.title || d.name);
}

function litDocRefs(ids) {
  return (ids || []).map(id => `<span class="lit-pill" title="${escHtml((corpus().docs.find(x => x.id === id) || {}).name || id)}">${escHtml(litDocLabel(id))}</span>`).join('');
}

function setLitTab(t) { litTab = t; litShowAll = false; renderInventory(); }
function setLitFilter(v) {
  litFilter = v; renderInventory();
  const inp = document.getElementById('litFilter');
  if (inp) { inp.focus(); inp.setSelectionRange(v.length, v.length); }
}
function toggleLitConcept(id) { litOpenConcepts.has(id) ? litOpenConcepts.delete(id) : litOpenConcepts.add(id); renderInventory(); }

function renderInventory() {
  const inv = corpus().inventory;
  const el = document.getElementById('litInventory');
  if (!inv) {
    el.innerHTML = `<p class="ctx-hint">Built from the extracted paper cards: concepts grouped across papers,
      conflicting definitions, and themes that could become modules.</p>`;
    return;
  }
  const doneIds = corpus().docs.filter(d => d.status === 'done').map(d => d.id).sort();
  const stale = JSON.stringify(doneIds) !== JSON.stringify([...inv.doc_ids].sort());
  const byId = Object.fromEntries(inv.concepts.map(c => [c.id, c]));
  const tabs = [['concepts', `Concepts (${inv.concepts.length})`], ['conflicts', `Conflicts (${inv.conflicts.length})`],
                ['themes', `Themes (${inv.themes.length})`], ['cqs', `CQ candidates (${inv.competency_questions.length})`],
                ['relations', `Relations (${inv.relations.length})`], ['taxonomies', `Taxonomies (${inv.taxonomies.length})`],
                ['vocabularies', `Vocabularies (${inv.vocabularies.length})`]];
  let body = '';
  if (litTab === 'concepts') {
    const f = litFilter.trim().toLowerCase();
    const docType = Object.fromEntries(corpus().docs.map(d => [d.id, d.source_type || 'paper']));
    const ontoSources = c => c.sources.filter(s => docType[s.doc] === 'ontology');
    const hasOnto = corpus().docs.some(d => d.source_type === 'ontology');
    const rows = inv.concepts.filter(c => (!f || [c.label, ...c.variants].some(v => v.toLowerCase().includes(f)))
      && (litCover === 'all' || (litCover === 'covered') === ontoSources(c).length > 0));
    const shown = litShowAll ? rows : rows.slice(0, LIT_TABLE_ROWS);
    body = `<div style="display:flex; gap:8px; margin-bottom:8px;">
        <input type="text" id="litFilter" placeholder="Filter concepts…" value="${escHtml(litFilter)}" oninput="setLitFilter(this.value)" />
        ${hasOnto ? `<select style="width:auto;" onchange="litCover=this.value; litShowAll=false; renderInventory()">
          <option value="all" ${litCover === 'all' ? 'selected' : ''}>All concepts</option>
          <option value="covered" ${litCover === 'covered' ? 'selected' : ''}>In an existing ontology</option>
          <option value="new" ${litCover === 'new' ? 'selected' : ''}>Not in any existing ontology</option></select>` : ''}
      </div>
      <div class="lit-scroll"><table class="lit-table"><thead><tr><th style="width:24%">Concept</th><th style="width:8%">Sources</th><th>Definition</th></tr></thead><tbody>
      ${shown.map(c => {
        const def = c.definition || (c.sources.find(s => s.definition) || {}).definition || '';
        const open = litOpenConcepts.has(c.id);
        const onto = ontoSources(c);
        return `<tr><td><strong>${escHtml(c.label)}</strong>${c.conflict ? ' <span class="lit-warn" title="Sources disagree — see Conflicts">⚠</span>' : ''}
            ${c.variants.length ? `<div class="lit-meta">${escHtml(c.variants.slice(0, 6).join(', '))}</div>` : ''}
            ${onto.map(s => `<div><span class="lit-pill" title="${escHtml(s.uri)}">🧬 ${escHtml(litDocLabel(s.doc).replace(/^🧬 /, ''))}: ${escHtml(s.term)}</span></div>`).join('')}</td>
          <td>${c.papers}</td>
          <td>${c.definition ? escHtml(def) : `<span class="lit-meta">${c.sources.length > 1 ? 'first of several: ' : ''}</span>${escHtml(def)}`}
            <div><button class="oops-toggle" style="margin:2px 0 0;" onclick="toggleLitConcept('${c.id}')">${open ? '▼' : '▶'} ${c.sources.length} source${c.sources.length !== 1 ? 's' : ''}</button></div>
            ${open ? `<ul class="lit-sources">${c.sources.map(s => `<li>${litDocRefs([s.doc])} <strong>${escHtml(s.term)}</strong>: ${escHtml(s.definition)}
              ${s.page ? `<span class="lit-meta">(p. ${s.page})</span>` : ''}${s.quote ? `<div class="lit-quote">“${escHtml(s.quote)}” ${s.quote_ok ? '<span class="lit-ok">✓</span>' : '<span class="lit-warn">⚠ not found in text</span>'}</div>` : ''}</li>`).join('')}</ul>` : ''}
          </td></tr>`;
      }).join('')}</tbody></table></div>
      ${rows.length > shown.length ? `<button class="oops-toggle" onclick="litShowAll=true; renderInventory()">Show all ${rows.length} concepts</button>` : ''}`;
  } else if (litTab === 'conflicts') {
    body = inv.conflicts.length ? inv.conflicts.map(x => `<div class="lit-conflict">
        <div style="font-weight:600; margin-bottom:4px;">${escHtml(x.label)}</div>
        <div style="margin-bottom:6px;">${escHtml(x.issue)}</div>
        ${x.positions.map(p => `<div style="margin:3px 0;">• ${escHtml(p.view)} ${litDocRefs(p.docs)}</div>`).join('')}
      </div>`).join('')
      : `<p class="ctx-hint">${inv.consolidated ? 'No conflicting definitions found.' : 'Conflicts are only found by the consolidation step.'}</p>`;
  } else if (litTab === 'themes') {
    body = inv.themes.length ? inv.themes.map(t => `<div class="lit-theme">
        <div style="font-weight:600;">${escHtml(t.name)} <span class="lit-meta">${t.concepts.length} concepts</span></div>
        <div class="lit-meta" style="margin:2px 0 6px;">${escHtml(t.description)}</div>
        ${t.concepts.map(id => byId[id] ? `<span class="lit-pill">${escHtml(byId[id].label)} · ${byId[id].papers}</span>` : '').join('')}
      </div>`).join('')
      : `<p class="ctx-hint">${inv.consolidated ? 'No themes proposed.' : 'Themes are only proposed by the consolidation step.'}</p>`;
  } else if (litTab === 'cqs') {
    body = `<div class="lit-scroll">${inv.competency_questions.map(q => `<div style="margin:4px 0;">• ${escHtml(q.question)} ${litDocRefs(q.docs)}</div>`).join('') || '<p class="ctx-hint">None.</p>'}</div>`;
  } else if (litTab === 'relations') {
    body = `<div class="lit-scroll"><table class="lit-table"><thead><tr><th>Subject</th><th>Relation</th><th>Object</th><th>Papers</th></tr></thead><tbody>
      ${inv.relations.map(r => `<tr><td>${escHtml(r.subject)}</td><td style="color:var(--accent-light)">${escHtml(r.relation)}</td><td>${escHtml(r.object)}</td><td>${litDocRefs(r.docs)}</td></tr>`).join('')}
      </tbody></table></div>`;
  } else if (litTab === 'taxonomies') {
    body = `<div class="lit-scroll">${inv.taxonomies.map(t => `<div class="lit-theme"><strong>${escHtml(t.name)}</strong> ${litDocRefs([t.doc])}<br>
      ${t.categories.map(x => `<span class="lit-pill">${escHtml(x)}</span>`).join('')}</div>`).join('') || '<p class="ctx-hint">None.</p>'}</div>`;
  } else {
    body = inv.vocabularies.map(v => `<div style="margin:4px 0;"><strong>${escHtml(v.name)}</strong>
      ${v.uri ? `<span class="lit-meta">${escHtml(v.uri)}</span>` : ''} ${litDocRefs(v.docs)}</div>`).join('') || '<p class="ctx-hint">None.</p>';
  }
  const central = inv.concepts.filter(c => c.papers > 1).length;
  const score = (title, value, sub) => `<div class="score"><span class="score-title">${title}</span>
    <div class="score-value">${value}</div>${sub ? `<div class="score-sub">${sub}</div>` : ''}</div>`;
  el.innerHTML = `
    ${stale ? `<div class="alert alert-info"><span>The paper cards changed since this inventory was built – rebuild it to include them.</span></div>` : ''}
    ${inv.warning ? `<div class="alert alert-error"><span>${escHtml(inv.warning)}</span></div>` : ''}
    <div class="score-grid" style="grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));">
      ${score('Sources', inv.doc_ids.length, `built ${escHtml(new Date(inv.built_at).toLocaleDateString())}`)}
      ${score('Concepts', inv.concepts.length, '')}
      ${score('Central concepts', central, 'named by two or more sources')}
      ${score('Conflicts', inv.conflicts.length, inv.consolidated ? 'definitions that disagree' : 'only after consolidation')}
      ${score('Themes', inv.themes.length, 'candidates for modules')}
    </div>
    <div class="tabs">${tabs.map(([k, label]) => `<button class="tab ${litTab === k ? 'active' : ''}" onclick="setLitTab('${k}')">${label}</button>`).join('')}</div>
    ${body}`;
}
