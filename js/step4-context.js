// Schritt 4: Projektkontext, widerspruechliche Definitionen
// (PLAN.md Phase 4: eine Datei je Schritt; klassische Skripte - alle Funktionen sind global,
// sofort ausgefuehrt wird nur main.js, das zuletzt laedt)

// ── Schritt 3: Projektkontext (Panel 7) ───────────────────────────────────────
// Entwurf aus Use Case, Daten und ggf. vorhandener Kontextdatei; das Team bestaetigt, korrigiert und beantwortet
// gezielte Rueckfragen. Das Dokument und die Konventionen gehen an jeden spaeteren Prompt.
async function proceedToContext() {
  if (!document.getElementById('domainDesc').value.trim()) {
    alert('Please describe the use case first.'); return;
  }
  await saveMomo();
  goTo(7);
  renderContext();
  if (!(state.context && state.context.markdown) && state.llmConfig) draftContext();
}

async function contextRequest(endpoint, body, busyText) {
  const st = document.getElementById('contextStatus');
  if (busyText) st.innerHTML = `<div class="alert alert-info"><div class="spinner"></div><span>${busyText}</span></div>`;
  try {
    const res = await fetch(`${API}/api/context/${endpoint}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: state.sessionId, ...body }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Request failed');
    st.innerHTML = '';
    return data;
  } catch (e) {
    st.innerHTML = `<div class="alert alert-error"><span>❌</span><span>Error: ${escHtml(e.message)}</span></div>`;
    return null;
  }
}

async function draftContext() {
  if (!state.llmConfig) { alert('Please configure the LLM first (Step 1).'); goTo(1); return; }
  await saveMomo();
  await flushContextSave();
  const redraft = state.context && state.context.markdown;
  const data = await contextRequest('draft', {
    llm_config: state.llmConfig, extra_requirements: document.getElementById('extraReqs').value,
  }, redraft ? 'Improving the draft — confirmed items are kept…'
             : 'Drafting the project context from your use case and data…');
  if (!data) return;
  state.context = data;
  renderContext();
  markDone(7);
}

async function uploadContextFile(file) {
  if (!file) return;
  const fd = new FormData();
  fd.append('file', file);
  const st = document.getElementById('contextStatus');
  st.innerHTML = `<div class="alert alert-info"><div class="spinner"></div><span>Reading ${escHtml(file.name)}…</span></div>`;
  try {
    const res = await fetch(`${API}/api/context/upload?session_id=${state.sessionId}`, { method: 'POST', body: fd });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Upload failed');
    state.context = data;
    st.innerHTML = `<div class="alert alert-success"><span>✅</span><span>${escHtml(file.name)} loaded. Use
      ✨ ${state.context.markdown ? 'Improve draft' : 'Draft project context'} to take its content over into the document.</span></div>`;
    renderContext();
  } catch (e) {
    st.innerHTML = `<div class="alert alert-error"><span>❌</span><span>Error: ${escHtml(e.message)}</span></div>`;
  } finally {
    document.getElementById('contextFileInput').value = '';
  }
}

async function removeContextSource() {
  const data = await contextRequest('save', { clear_source: true });
  if (data) { state.context = data; renderContext(); }
}

function renderContext() {
  const ctx = state.context || { markdown: '', questions: [], conventions: {}, source_name: '', source_chars: 0 };
  const conv = ctx.conventions || {};
  const set = (id, v) => { const el = document.getElementById(id); if (el && document.activeElement !== el) el.value = v || ''; };
  set('contextMarkdown', ctx.markdown);
  set('convNamespace', conv.namespace);
  set('convPrefix', conv.prefix);
  set('convLabelLanguages', conv.label_languages || 'en');
  set('convLicense', conv.license);
  document.getElementById('convOwlProfile').value = conv.owl_profile || 'OWL 2 DL';

  document.getElementById('contextSourceInfo').innerHTML = ctx.source_name
    ? `Context file: ${escHtml(ctx.source_name)} (${(ctx.source_chars || 0).toLocaleString('en-US')} characters)
       <button class="momo-del" onclick="removeContextSource()" title="Remove" aria-label="Remove the context file">✕</button>` : '';
  document.getElementById('draftContextBtn').textContent = ctx.markdown ? 'Improve the draft' : 'Draft project context';
  updateConfirmCount();

  const qs = ctx.questions || [];
  document.getElementById('contextQuestionsCard').style.display = qs.length ? 'block' : 'none';
  document.getElementById('contextQuestionCount').textContent = qs.length ? `(${qs.length})` : '';
  setTimeout(updateContextTabs, 0);
  document.getElementById('contextQuestions').innerHTML = qs.map((q, i) => `
    <div class="ctx-question" data-q="${i}">
      <div class="q-head">
        <div style="flex:1">
          ${q.section ? `<div class="q-section">${escHtml(q.section)}</div>` : ''}
          ${escHtml(q.question)}
        </div>
        <button class="momo-del" onclick="dismissContextQuestion(${i})" title="Dismiss this question">✕</button>
      </div>
      ${(q.options || []).map((o, j) => `
        <label class="q-opt"><input type="radio" name="ctxq${i}" value="${escHtml(o)}" />
          ${escHtml(o)} ${q.recommended === j ? '<span class="q-rec">recommended</span>' : ''}</label>`).join('')}
      <input type="text" class="q-other" placeholder="Other answer…" oninput="if (this.value) document.querySelectorAll('input[name=ctxq${i}]').forEach(r => r.checked = false)" />
    </div>`).join('');
  if (ctx.markdown && ctx.markdown.trim()) markDone(7);
  renderUpperLayer();
}

// Obere Schicht (DECISIONS 69): die Zeilen sind der Arbeitsstand; gespeichert wird separat, damit ein ungueltiger
// Zwischenstand beim Tippen (leerer Name) nicht die anderen Kontextaenderungen blockiert
// Zeilen tragen eine feste _id, die Oberklasse als _parentId: so bleibt der Verweis auch beim Umbenennen erhalten
let upperRows = null, _upperTimer = null, _upperNextId = 0;
function renderUpperLayer(keepRows) {
  const ctx = state.context || {};
  if (!upperRows || (!keepRows && !document.getElementById('upperLayerRows').contains(document.activeElement))) {
    upperRows = (ctx.upper_layer || []).map(r => ({ ...r, _id: _upperNextId++ }));
    upperRows.forEach(r => { const p = upperRows.find(x => x.name === r.parent); r._parentId = p ? p._id : null; });
  }
  document.getElementById('upperLayerState').textContent = (ctx.upper_layer_default === false ? '— adjusted for this project' : '— default') +
    (ctx.use_upper_layer === false ? ', not used by the generation' : '');
  document.getElementById('useUpperLayer').checked = ctx.use_upper_layer !== false;
  document.getElementById('upperLayerRows').innerHTML = upperRows.map((r, i) => `
    <div style="display:grid; grid-template-columns:minmax(120px,180px) minmax(120px,170px) auto 1fr auto; gap:8px; align-items:start; margin-bottom:8px;">
      <input type="text" value="${escHtml(r.name)}" placeholder="ClassName" oninput="editUpper(${i}, 'name', this.value)" onchange="renderUpperLayer(true)" />
      <select onchange="editUpper(${i}, 'parent', this.value)" title="Superclass within the layer">
        <option value="">(top level)</option>
        ${upperRows.filter(x => x._id !== r._id && x.name).map(x => `<option value="${x._id}" ${x._id === r._parentId ? 'selected' : ''}>${escHtml(x.name)}</option>`).join('')}
      </select>
      <label class="ctx-hint" style="white-space:nowrap; margin:6px 0 0;" title="${r._parentId !== null ? 'Only top-level classes can be disjoint' : 'Disjoint with the other disjoint top-level classes'}">
        <input type="checkbox" ${r.disjoint && r._parentId === null ? 'checked' : ''} ${r._parentId !== null ? 'disabled' : ''} onchange="editUpper(${i}, 'disjoint', this.checked)" /> disjoint</label>
      <textarea rows="2" placeholder="Definition: what belongs here" oninput="editUpper(${i}, 'definition', this.value)">${escHtml(r.definition)}</textarea>
      <button class="momo-del" onclick="removeUpperClass(${i})" title="Remove">✕</button>
    </div>`).join('');
}
function editUpper(i, field, value) {
  if (field === 'parent') {
    upperRows[i]._parentId = value === '' ? null : +value;
    if (value !== '') upperRows[i].disjoint = false;
  } else upperRows[i][field] = value;
  if (field === 'parent' || field === 'disjoint') renderUpperLayer(true);
  clearTimeout(_upperTimer);
  _upperTimer = setTimeout(saveUpperLayer, 800);
}
function addUpperClass() {
  upperRows.push({ name: '', disjoint: true, definition: '', _id: _upperNextId++, _parentId: null });
  renderUpperLayer(true);
}
function removeUpperClass(i) {
  const id = upperRows[i]._id;
  upperRows.splice(i, 1);
  upperRows.forEach(r => { if (r._parentId === id) r._parentId = null; });
  renderUpperLayer(true);
  saveUpperLayer();
}
async function saveUseUpperLayer(on) {
  const res = await fetch(`${API}/api/context/save`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: state.sessionId, use_upper_layer: on }),
  });
  if (res.ok) state.context = await res.json();
  renderUpperLayer(true);
}
async function resetUpperLayer() {
  if (!confirm('Replace this project\'s upper layer with the default?')) return;
  upperRows = null;
  await saveUpperLayer({ reset_upper_layer: true });
}
async function saveUpperLayer(body) {
  clearTimeout(_upperTimer);
  const err = document.getElementById('upperLayerError');
  if (!body && upperRows.some(r => !r.name.trim())) { err.textContent = 'Every upper class needs a name.'; return; }
  const layer = () => upperRows.map(r => ({ name: r.name.trim(), disjoint: r.disjoint, definition: r.definition,
    parent: (upperRows.find(x => x._id === r._parentId) || {}).name || '' }));
  try {
    const res = await fetch(`${API}/api/context/save`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: state.sessionId, ...(body || { upper_layer: layer() }) }),
    });
    const data = await res.json();
    if (!res.ok) { err.textContent = data.detail || 'Could not save'; return; }
    err.textContent = '';
    state.context = data;
    if (body) upperRows = null;
    // waehrend getippt wird, die Eingabefelder stehen lassen (sonst springt der Cursor heraus)
    if (body || !document.getElementById('upperLayerRows').contains(document.activeElement)) renderUpperLayer(!body);
    else document.getElementById('upperLayerState').textContent = data.upper_layer_default === false ? '— adjusted for this project' : '— default';
  } catch (e) { err.textContent = 'Could not save: ' + e.message; }
}

// ── Widerspruechliche Definitionen entscheiden (PLAN.md Phase 1, DECISIONS 83) ──
// defDrafts: der Bearbeitungsstand je Konflikt (aus Entscheidung oder Empfehlung), gespeichert erst mit "Save decision"
let defDrafts = {}, defOpen = new Set();
const toClassName = s => String(s || '').split(/[^A-Za-z0-9]+/).filter(Boolean).map(w => w[0].toUpperCase() + w.slice(1)).join('');
const plainDecision = d => d ? { choice: d.choice, position: d.position, reason: d.reason || '',
                                 parts: (d.parts || []).map(p => ({ name: p.name, definition: p.definition })) } : null;

async function loadDefinitions() {
  if (!state.sessionId) return;
  try {
    const res = await fetch(`${API}/api/definitions?session_id=${state.sessionId}`);
    const d = await res.json();
    if (!res.ok) throw new Error(d.detail || 'Request failed');
    state.definitions = d;
  } catch (e) { state.definitions = null; }
  defDrafts = {};
  renderDefinitions();
}

async function definitionsRequest(endpoint, body, busyText) {
  const st = document.getElementById('definitionsStatus');
  if (busyText) st.innerHTML = `<div class="alert alert-info"><div class="spinner"></div><span>${busyText}</span></div>`;
  try {
    const res = await fetch(`${API}/api/definitions/${endpoint}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: state.sessionId, ...body }),
    });
    const d = await res.json();
    if (!res.ok) throw new Error(d.detail || 'Request failed');
    st.innerHTML = '';
    state.definitions = d;
    return d;
  } catch (e) {
    st.innerHTML = `<div class="alert alert-error"><span>❌</span><span>${escHtml(e.message)}</span></div>`;
    return null;
  }
}

function describeDecision(d, c) {
  if (!d) return '';
  if (d.choice === 'open') return 'left open';
  if (d.choice === 'split') return `split into ${d.parts.map(p => p.name).join(', ')}`;
  return (d.choice === 'position' ? `position ${d.position + 1}` : 'own definition') + ` → ${d.parts[0].name}`;
}

function renderDefinitions() {
  const card = document.getElementById('definitionsCard');
  const d = state.definitions;
  if (!d || !d.conflicts.length) { card.style.display = 'none'; updateContextTabs(); return; }
  card.style.display = 'block';
  setTimeout(updateContextTabs, 0);
  const s = d.summary;
  document.getElementById('definitionsCount').textContent =
    `— ${s.decided} of ${s.conflicts} decided${s.open ? ` (${s.open} left open)` : ''}${s.recommended ? ` · ${s.recommended} recommendations to review` : ''}`;
  const accept = document.getElementById('acceptDefsBtn');
  accept.style.display = s.recommended ? '' : 'none';
  accept.textContent = `Accept all ${s.recommended} recommendations`;
  const filter = document.getElementById('definitionsFilter').value;
  const shown = d.conflicts.filter(c => filter === 'all' || (filter === 'decided') === !!c.decision);
  document.getElementById('definitionsList').innerHTML = shown.length ? shown.map(c => {
    const i = d.conflicts.indexOf(c);
    if (!defDrafts[c.key]) defDrafts[c.key] = plainDecision(c.decision) || plainDecision(c.recommendation) ||
                                              { choice: '', position: null, parts: [], reason: '' };
    const draft = defDrafts[c.key];
    const st = c.decision ? `<span class="def-state decided">✓ ${escHtml(describeDecision(c.decision))}${c.decision.accepted_recommendation ? ' (recommended)' : ''}</span>`
      : c.recommendation ? `<span class="def-state recommended">recommended: ${escHtml(describeDecision(c.recommendation))}</span>`
      : '<span class="def-state todo">undecided</span>';
    const radio = (value, text, extra = '') => `<label class="q-opt"><input type="radio" name="defc${i}" value="${value}"
        ${(draft.choice === 'position' ? 'position:' + draft.position : draft.choice) === value ? 'checked' : ''}
        onchange="chooseDefinition(${i}, '${value}')" /><span>${text}${extra}</span></label>`;
    return `<details class="def-item" data-key="${escHtml(c.key)}" ${defOpen.has(c.key) ? 'open' : ''} ontoggle="toggleDefinition(this)">
      <summary><strong>${escHtml(c.concept)}</strong> <span class="lit-meta">${c.orphan ? 'no longer a conflict in the inventory'
        : `${c.papers} sources · ${c.positions.length} positions`}</span>${st}</summary>
      <div class="def-body">
        ${c.issue ? `<div style="margin-bottom:6px;">${escHtml(c.issue)}</div>` : ''}
        ${c.recommendation && !c.decision ? `<div class="def-rec"><strong>Recommended:</strong> ${escHtml(describeDecision(c.recommendation))}
          — ${escHtml(c.recommendation.reason || '')}
          <button class="oops-toggle" onclick="acceptDefinitions([state.definitions.conflicts[${i}].key])">✓ Accept</button></div>` : ''}
        ${c.positions.map((p, j) => radio('position:' + j, escHtml(p.view),
            p.sources.length ? ` <span class="lit-meta">(${escHtml(p.sources.slice(0, 4).join('; '))})</span>` : '')).join('')}
        ${radio('own', 'Own definition')}
        ${radio('split', 'Split into separate classes')}
        ${radio('open', 'Leave open — the model decides during generation')}
        ${c.definitions.length ? `<details style="margin:6px 0;"><summary class="lit-meta" style="cursor:pointer;">Definitions in the sources (${c.definitions.length})</summary>
          <ul class="lit-sources">${c.definitions.map(x => `<li>${escHtml(x.definition)} <span class="lit-meta">— ${escHtml(x.source)}</span></li>`).join('')}</ul></details>` : ''}
        <div id="defEdit${i}">${definitionEditor(i)}</div>
      </div></details>`;
  }).join('') : `<p class="ctx-hint">${filter === 'decided' ? 'Nothing decided yet.' : 'Every conflict is decided.'}</p>`;
}

function definitionEditor(i) {
  const c = state.definitions.conflicts[i], draft = defDrafts[c.key];
  if (!draft.choice) return '';
  const parts = draft.parts.map((p, j) => `<div class="def-part">
      <input type="text" value="${escHtml(p.name)}" placeholder="ClassName" oninput="editDefinition(${i}, ${j}, 'name', this.value)" />
      <textarea placeholder="Definition — the class description, used word for word" oninput="editDefinition(${i}, ${j}, 'definition', this.value)">${escHtml(p.definition)}</textarea>
      ${draft.choice === 'split' && draft.parts.length > 2 ? `<button class="momo-del" onclick="removeDefinitionPart(${i}, ${j})" title="Remove">✕</button>` : '<span></span>'}
    </div>`).join('');
  return `${parts}
    ${draft.choice === 'split' && draft.parts.length < 4 ? `<button class="oops-toggle" onclick="addDefinitionPart(${i})">＋ Add class</button>` : ''}
    <input type="text" value="${escHtml(draft.reason)}" placeholder="Reason (optional)" style="margin-top:6px;" oninput="defDrafts[state.definitions.conflicts[${i}].key].reason = this.value" />
    <div style="display:flex; gap:10px; margin-top:8px;">
      <button class="btn btn-primary btn-sm" onclick="saveDefinition(${i})">Save decision</button>
      ${c.decision ? `<button class="btn btn-secondary btn-sm" onclick="withdrawDefinition(${i})">Withdraw decision</button>` : ''}
    </div>`;
}

function toggleDefinition(el) { el.open ? defOpen.add(el.dataset.key) : defOpen.delete(el.dataset.key); }

function chooseDefinition(i, value) {
  const c = state.definitions.conflicts[i], draft = defDrafts[c.key];
  const name0 = (draft.parts[0] && draft.parts[0].name) || toClassName(c.concept);
  if (value.startsWith('position:')) {
    const j = +value.split(':')[1];
    Object.assign(draft, { choice: 'position', position: j, parts: [{ name: name0, definition: c.positions[j].view }] });
  } else if (value === 'own') {
    const keep = draft.choice === 'own' && draft.parts[0] ? draft.parts[0].definition : '';
    Object.assign(draft, { choice: 'own', position: null, parts: [{ name: name0, definition: keep }] });
  } else if (value === 'split') {
    const parts = draft.choice === 'split' ? draft.parts
      : c.positions.slice(0, 2).map((p, j) => ({ name: j === 0 ? name0 : '', definition: p.view }));
    while (parts.length < 2) parts.push({ name: '', definition: '' });
    Object.assign(draft, { choice: 'split', position: null, parts });
  } else Object.assign(draft, { choice: 'open', position: null, parts: [] });
  document.getElementById('defEdit' + i).innerHTML = definitionEditor(i);
}
function editDefinition(i, j, field, value) { defDrafts[state.definitions.conflicts[i].key].parts[j][field] = value; }
function addDefinitionPart(i) {
  defDrafts[state.definitions.conflicts[i].key].parts.push({ name: '', definition: '' });
  document.getElementById('defEdit' + i).innerHTML = definitionEditor(i);
}
function removeDefinitionPart(i, j) {
  defDrafts[state.definitions.conflicts[i].key].parts.splice(j, 1);
  document.getElementById('defEdit' + i).innerHTML = definitionEditor(i);
}

async function saveDefinition(i) {
  const c = state.definitions.conflicts[i];
  if (await definitionsRequest('decide', { key: c.key, decision: defDrafts[c.key] })) {
    delete defDrafts[c.key];
    renderDefinitions();
  }
}
async function withdrawDefinition(i) {
  const c = state.definitions.conflicts[i];
  if (await definitionsRequest('decide', { key: c.key, decision: null })) { delete defDrafts[c.key]; renderDefinitions(); }
}
async function acceptDefinitions(keys) {
  const d = await definitionsRequest('accept', { keys });
  if (!d) return;
  (keys || Object.keys(defDrafts)).forEach(k => delete defDrafts[k]);
  if (d.result.skipped.length) document.getElementById('definitionsStatus').innerHTML =
    `<div class="alert alert-error"><span>⚠️</span><span>Not accepted: ${d.result.skipped.map(escHtml).join('; ')}</span></div>`;
  renderDefinitions();
}
async function recommendDefinitions() {
  if (!state.llmConfig) { alert('Please configure the LLM first (Step 1).'); goTo(1); return; }
  const todo = state.definitions.conflicts.filter(c => !c.decision && !c.orphan).length;
  if (!todo) { alert('Every conflict is decided.'); return; }
  if (!confirm(`Recommend a decision for the ${todo} undecided conflicts (${Math.ceil(todo / 15)} model call${todo > 15 ? 's' : ''})? Nothing is decided until you accept.`)) return;
  await flushContextSave();
  document.getElementById('recommendDefsBtn').disabled = true;
  const d = await definitionsRequest('recommend', { llm_config: state.llmConfig },
                                     `Recommending decisions for ${todo} conflicts…`);
  document.getElementById('recommendDefsBtn').disabled = false;
  if (!d) return;
  recordUsage(d.usage, false);
  const r = d.result;
  defDrafts = {};
  document.getElementById('definitionsStatus').innerHTML = `<div class="alert ${r.failed_batches ? 'alert-error' : 'alert-success'}"><span>${r.failed_batches ? '⚠️' : '✅'}</span><span>
    ${r.recommended} of ${r.asked} conflicts have a recommendation${r.invalid ? `; ${r.invalid} unusable answers were dropped` : ''}${r.failed_batches
      ? `; ${r.failed_batches} package${r.failed_batches !== 1 ? 's' : ''} failed (${escHtml(r.error)}) — recommend again to retry them` : ''}.
    Review them below and accept, change or reject each.</span></div>`;
  renderDefinitions();
}

function updateConfirmCount() {
  const md = document.getElementById('contextMarkdown').value || '';
  const n = (md.match(/\[confirm\]/gi) || []).length;
  document.getElementById('contextConfirmCount').textContent = n ? `— ${n} item${n !== 1 ? 's' : ''} to confirm` : '';
  updateContextTabs();
}

async function answerContextQuestions() {
  if (!state.llmConfig) { alert('Please configure the LLM first (Step 1).'); goTo(1); return; }
  const qs = (state.context && state.context.questions) || [];
  const answers = [];
  document.querySelectorAll('#contextQuestions .ctx-question').forEach(el => {
    const q = qs[+el.dataset.q];
    const picked = el.querySelector('input[type=radio]:checked');
    const other = el.querySelector('input.q-other').value.trim();
    const answer = other || (picked ? picked.value : '');
    if (q && answer) answers.push({ question: q.question, answer });
  });
  if (!answers.length) { alert('Please answer at least one question.'); return; }
  await flushContextSave();
  const data = await contextRequest('answer', { llm_config: state.llmConfig, answers },
                                    `Adding ${answers.length} answer${answers.length !== 1 ? 's' : ''} to the document…`);
  if (data) { state.context = data; renderContext(); }
}

async function dismissContextQuestion(i) {
  const qs = [...((state.context && state.context.questions) || [])];
  qs.splice(i, 1);
  const data = await contextRequest('save', { questions: qs });
  if (data) { state.context = data; renderContext(); }
}

let _contextSaveTimer = null, _contextPending = null;
function onContextEdited() {
  updateConfirmCount();
  queueContextSave({ markdown: document.getElementById('contextMarkdown').value });
}
function onConventionsEdited() {
  queueContextSave({ conventions: {
    namespace: document.getElementById('convNamespace').value.trim(),
    prefix: document.getElementById('convPrefix').value.trim(),
    label_languages: document.getElementById('convLabelLanguages').value.trim(),
    license: document.getElementById('convLicense').value.trim(),
    owl_profile: document.getElementById('convOwlProfile').value,
  }});
}
function queueContextSave(part) {
  _contextPending = { ...(_contextPending || {}), ...part };
  clearTimeout(_contextSaveTimer);
  _contextSaveTimer = setTimeout(flushContextSave, 700);
}
async function flushContextSave() {
  clearTimeout(_contextSaveTimer);
  if (!_contextPending || !state.sessionId) return;
  const part = _contextPending;
  _contextPending = null;
  try {
    const res = await fetch(`${API}/api/context/save`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: state.sessionId, ...part }),
    });
    const err = document.getElementById('convError');
    if (!res.ok && err) err.textContent = (await res.json()).detail || 'Could not save';   // z.B. Prefix eines Vokabulars
    if (res.ok) {
      if (err) err.textContent = '';
      const data = await res.json();
      // Nur den Serverstand uebernehmen; die Eingabefelder nicht ueberschreiben, waehrend getippt wird
      state.context = data;
      updateConfirmCount();
      if (data.markdown && data.markdown.trim()) markDone(7);
    }
  } catch (e) { _contextPending = { ...part, ...(_contextPending || {}) }; }
}
