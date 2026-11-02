// Schritt 9: Evaluieren und verfeinern - OOPS!, CQ-Tests, Evaluation, Reparaturwerkzeuge, Feedback, Turtle-Editor, SHACL, Export
// (PLAN.md Phase 4: eine Datei je Schritt; klassische Skripte - alle Funktionen sind global,
// sofort ausgefuehrt wird nur main.js, das zuletzt laedt)

// ── Feedback: Datei-Upload ─────────────────────────────────────────────────────
function onDragOver2(e) { e.preventDefault(); document.getElementById('fbDropZone').classList.add('drag-over'); }
function onDragLeave2(e) { document.getElementById('fbDropZone').classList.remove('drag-over'); }
function onDrop2(e) { e.preventDefault(); document.getElementById('fbDropZone').classList.remove('drag-over'); if (e.dataTransfer.files.length) handleFeedbackFiles(e.dataTransfer.files); }

async function handleFeedbackFiles(fileList) {
  if (!fileList || !fileList.length) return;
  const files = Array.from(fileList);
  const listEl = document.getElementById('fbFileList');
  listEl.innerHTML = files.map(f => {
    const ext = f.name.split('.').pop().toUpperCase();
    const size = f.size > 1024*1024 ? (f.size/1024/1024).toFixed(1)+'MB' : Math.round(f.size/1024)+'KB';
    return `<div style="display:flex;align-items:center;gap:8px;padding:2px 0;">
      <span style="background:var(--accent);color:#fff;font-size:0.65rem;font-weight:700;padding:1px 5px;border-radius:4px;">${ext}</span>
      <span style="font-size:0.82rem;">${f.name}</span>
      <span style="color:var(--text-muted);font-size:0.72rem;margin-left:auto;">${size}</span>
    </div>`;
  }).join('');
  listEl.style.display = 'block';
  const fd = new FormData();
  files.forEach(f => fd.append('files', f));
  try {
    const res = await fetch(`${API}/api/upload-feedback-files?session_id=${state.sessionId}`, { method: 'POST', body: fd });
    if (!res.ok) { const e = await res.json(); throw new Error(e.detail); }
  } catch(e) {
    alert('Error attaching files: ' + e.message);
  }
}

// ── Step 6: Feedback ───────────────────────────────────────────────────────────
async function submitFeedback() {
  const feedback = document.getElementById('feedbackText').value.trim();
  if (!feedback) { alert('Please enter your feedback.'); return; }
  if (!state.llmConfig) { alert('LLM not configured.'); return; }

  document.getElementById('feedbackBtn').disabled = true;
  document.getElementById('feedbackStatus').innerHTML = `
    <div class="alert alert-info">
      <div class="spinner"></div>
      <span>Refining ontology…</span>
    </div>`;

  try {
    const res = await fetch(`${API}/api/feedback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: state.sessionId,
        feedback,
        llm_config: state.llmConfig,
      }),
    });

    const text = await res.text();
    let data;
    try { data = JSON.parse(text); } catch(_) {
      throw new Error(`Server response is not JSON (HTTP ${res.status}):\n${text.slice(0, 400)}`);
    }
    if (!res.ok) throw new Error(data.detail || JSON.stringify(data));

    document.getElementById('feedbackStatus').innerHTML =
      `<div class="alert alert-success">✅ Refinement complete (iteration ${data.iteration})!</div>` + renderEditReport(data.edit_report);
    recordUsage(data.usage, true);

    computeAndShowDiff(state.currentOntology, data.ontology);
    state.currentOntology = data.ontology;
    state.currentTurtle   = data.turtle;
    state.iteration       = data.iteration;
    renderValidationBadge(data.oops_report?.validation);
    renderOopsReport(data.oops_report);
    renderOntology(data.ontology, data.turtle, data.iteration);
    document.getElementById('feedbackText').value = '';
    document.getElementById('fbFileList').innerHTML = '';
    document.getElementById('fbFileList').style.display = 'none';
    markDone(6);
    runCQTests();
    renderEvaluation(state.evaluation);

  } catch(e) {
    document.getElementById('feedbackStatus').innerHTML =
      `<div class="alert alert-error">❌ Error: ${escHtml(e.message)}</div>`;
  } finally {
    document.getElementById('feedbackBtn').disabled = false;
  }
}

// ── Diff ───────────────────────────────────────────────────────────────────────
function computeAndShowDiff(oldOnto, newOnto) {
  if (!oldOnto) { document.getElementById('diffView').style.display = 'none'; return; }

  function byName(arr) {
    const m = {};
    (arr || []).forEach(x => { m[x.name] = x; });
    return m;
  }

  function diffSection(label, oldMap, newMap, descFn) {
    const added = [], removed = [], changed = [];
    Object.keys(newMap).forEach(k => {
      if (!oldMap[k]) added.push(k);
      else {
        const chg = descFn(oldMap[k], newMap[k]);
        if (chg) changed.push({ name: k, detail: chg });
      }
    });
    Object.keys(oldMap).forEach(k => { if (!newMap[k]) removed.push(k); });

    if (!added.length && !removed.length && !changed.length) return '';
    let html = `<div class="diff-section"><h4>${label}</h4>`;
    added.forEach(k   => html += `<div class="diff-item diff-added"><span class="diff-badge add">+</span><span><code>${escHtml(k)}</code></span></div>`);
    removed.forEach(k => html += `<div class="diff-item diff-removed"><span class="diff-badge rem">−</span><span><code>${escHtml(k)}</code></span></div>`);
    changed.forEach(c => html += `<div class="diff-item diff-changed"><span class="diff-badge chg">~</span><span><code>${escHtml(c.name)}</code> — ${escHtml(c.detail)}</span></div>`);
    return html + '</div>';
  }

  function classDiff(a, b) {
    const parts = [];
    if (a.parent !== b.parent) parts.push('superclass: ' + (a.parent||'–') + ' → ' + (b.parent||'–'));
    if (ontoLabel(a) !== ontoLabel(b)) parts.push('Label: "' + ontoLabel(a) + '" → "' + ontoLabel(b) + '"');
    if ((a.description||'') !== (b.description||'')) parts.push('description changed');
    return parts.join(', ');
  }

  function propDiff(a, b) {
    const parts = [];
    if (a.type   !== b.type)   parts.push('type: ' + a.type + ' → ' + b.type);
    if (a.domain !== b.domain) parts.push('domain: ' + (a.domain||'–') + ' → ' + (b.domain||'–'));
    if (a.range  !== b.range)  parts.push('range: ' + (a.range||'–') + ' → ' + (b.range||'–'));
    if (ontoLabel(a) !== ontoLabel(b)) parts.push('label changed');
    return parts.join(', ');
  }

  function indDiff(a, b) {
    if (a.class !== b.class) return 'class: ' + (a.class||'–') + ' → ' + (b.class||'–');
    return '';
  }

  let html = '';
  html += diffSection('Classes',    byName(oldOnto.classes),     byName(newOnto.classes),     classDiff);
  html += diffSection('Properties', byName(oldOnto.properties),  byName(newOnto.properties),  propDiff);
  html += diffSection('Individuals', byName(oldOnto.individuals),  byName(newOnto.individuals), indDiff);

  const diffEl = document.getElementById('diffView');
  const contentEl = document.getElementById('diffContent');
  if (!html) {
    contentEl.innerHTML = '<div class="diff-empty">No structural changes detected.</div>';
  } else {
    contentEl.innerHTML = html;
  }
  diffEl.style.display = 'block';
  diffEl.querySelector('.oops-toggle').textContent = '▼ hide';
}

function toggleDiff() {
  const content = document.getElementById('diffContent');
  const btn = document.getElementById('diffView').querySelector('.oops-toggle');
  const hidden = content.style.display === 'none';
  content.style.display = hidden ? 'block' : 'none';
  btn.textContent = hidden ? '▼ ausblenden' : '▶ anzeigen';
}

// ── Turtle Editor ──────────────────────────────────────────────────────────────
let turtleEditorDirty = false;
let turtleEditorBase = '';     // das Turtle, auf dem die Aenderungen im Editor beruhen
let lastTurtleError = '';

function toggleTurtleEditor() {
  const wrap = document.getElementById('turtleEditorWrap');
  const btn  = document.getElementById('turtleEditorToggleBtn');
  const hidden = wrap.style.display === 'none';
  wrap.style.display = hidden ? 'block' : 'none';
  btn.textContent = hidden ? '▼ Close editor' : '▶ Open editor';
  if (hidden) loadTurtleIntoEditor();
}

function loadTurtleIntoEditor() {
  if (!state.currentTurtle) return;
  document.getElementById('turtleEditor').value = state.currentTurtle;
  document.getElementById('turtleEditor').style.borderColor = 'var(--border)';
  document.getElementById('turtleEditorHint').textContent = '';
  document.getElementById('turtleEditorStatus').innerHTML = '';
  turtleEditorDirty = false;
  turtleEditorBase = state.currentTurtle;
}

// Beim Wechsel in Schritt 9: ein unveraenderter Editor zeigt den aktuellen Stand; ungespeicherte Aenderungen bleiben,
// mit Hinweis, wenn sich die Ontologie inzwischen geaendert hat
function refreshTurtleEditor() {
  if (!turtleEditorDirty) { loadTurtleIntoEditor(); return; }
  if (state.currentTurtle !== turtleEditorBase)
    document.getElementById('turtleEditorHint').textContent =
      'Unsaved — the ontology changed since you started editing; "Reset" loads the current version';
}

function resetTurtleEditor() {
  loadTurtleIntoEditor();
}

function onTurtleEditorInput() {
  turtleEditorDirty = true;
  document.getElementById('turtleEditorHint').textContent = 'Unsaved — click "Save & Apply"';
  document.getElementById('turtleEditorHint').style.color = 'var(--warning)';
  document.getElementById('turtleEditor').style.borderColor = 'var(--warning)';
}

async function saveTurtle() {
  const turtle = document.getElementById('turtleEditor').value;
  if (!turtle.trim()) return;

  document.getElementById('saveTurtleBtn').disabled = true;
  document.getElementById('turtleEditorStatus').innerHTML =
    '<div class="alert alert-info"><div class="spinner"></div><span>Validating and saving…</span></div>';

  try {
    const res = await fetch(`${API}/api/update-turtle`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: state.sessionId, turtle }),
    });
    const text = await res.text();
    let data;
    try { data = JSON.parse(text); } catch(_) { throw new Error(text.slice(0, 300)); }
    if (!res.ok) throw new Error(data.detail);

    // Diff anzeigen und State updaten
    computeAndShowDiff(state.currentOntology, data.ontology);
    state.currentOntology = data.ontology;
    state.currentTurtle   = data.turtle;     // was der Server gespeichert hat, nicht der Text des Editors
    state.iteration       = data.iteration;

    renderOntology(data.ontology, data.turtle, data.iteration);
    document.getElementById('turtleEditor').value = data.turtle;
    if (document.getElementById('shaclEditorWrap').style.display !== 'none')
      buildShaclTable(data.ontology);

    document.getElementById('turtleEditor').style.borderColor = 'var(--success)';
    document.getElementById('turtleEditorHint').textContent = '✔ Saved';
    document.getElementById('turtleEditorHint').style.color = 'var(--success)';
    document.getElementById('turtleEditorStatus').innerHTML =
      '<div class="alert alert-success">✅ Turtle applied — ontology view updated.</div>';
    turtleEditorDirty = false;

  } catch(e) {
    lastTurtleError = e.message;
    document.getElementById('turtleEditor').style.borderColor = 'var(--error)';
    document.getElementById('turtleEditorHint').textContent = '❌ Syntax error';
    document.getElementById('turtleEditorHint').style.color = 'var(--error)';
    document.getElementById('turtleEditorStatus').innerHTML =
      `<div class="alert alert-error" style="white-space:pre-wrap">❌ ${escHtml(e.message)}</div>
       <button class="btn btn-secondary" style="margin-top:8px;" onclick="llmFixTurtle()">🤖 Let LLM fix the error</button>`;
  } finally {
    document.getElementById('saveTurtleBtn').disabled = false;
  }
}

async function llmFixTurtle() {
  const errorMsg = lastTurtleError;
  if (!state.llmConfig) { alert('Please configure the LLM first (Step 1).'); return; }
  const brokenTurtle = document.getElementById('turtleEditor').value;

  document.getElementById('turtleEditorStatus').innerHTML =
    '<div class="alert alert-info"><div class="spinner"></div><span>LLM is fixing the syntax error…</span></div>';

  try {
    const res = await fetch(`${API}/api/fix-turtle`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: state.sessionId,
        turtle: brokenTurtle,
        error: errorMsg,
        llm_config: state.llmConfig,
      }),
    });
    const text = await res.text();
    let data;
    try { data = JSON.parse(text); } catch(_) { throw new Error(text.slice(0, 300)); }
    if (!res.ok) throw new Error(data.detail);

    // Korrigierten Turtle in Editor laden
    document.getElementById('turtleEditor').value = data.turtle;
    document.getElementById('turtleEditor').style.borderColor = 'var(--warning)';
    document.getElementById('turtleEditorHint').textContent = 'Fixed by LLM — please review and save';
    document.getElementById('turtleEditorHint').style.color = 'var(--warning)';
    document.getElementById('turtleEditorStatus').innerHTML =
      '<div class="alert alert-success">✅ LLM fixed the Turtle. Please review and click "Save & Apply".</div>';
    turtleEditorDirty = true;
  } catch(e) {
    document.getElementById('turtleEditorStatus').innerHTML =
      '<div class="alert alert-error">❌ LLM fix failed: ' + escHtml(e.message) + '</div>';
  }
}

// ── SHACL ──────────────────────────────────────────────────────────────────────
let shaclTurtle = '';

const XSD_TYPES = ['','xsd:string','xsd:integer','xsd:decimal','xsd:float','xsd:boolean',
  'xsd:date','xsd:dateTime','xsd:anyURI','xsd:langString'];
const NODE_KINDS = ['','sh:IRI','sh:Literal','sh:BlankNode'];

function toggleShaclEditor() {
  const wrap = document.getElementById('shaclEditorWrap');
  const btn  = document.getElementById('shaclEditorToggleBtn');
  const hidden = wrap.style.display === 'none';
  wrap.style.display = hidden ? 'block' : 'none';
  btn.textContent = hidden ? '▼ Close editor' : '▶ Open editor';
  if (hidden && state.currentOntology) buildShaclTable(state.currentOntology);
}

function buildShaclTable(onto) {
  const tbody = document.getElementById('shaclTableBody');
  const rows = [];
  (onto.properties || []).forEach(p => {
    const xsdOpts = XSD_TYPES.map(t => `<option value="${t}"${t===''?' selected':''}>${t||'–'}</option>`).join('');
    const nkOpts  = NODE_KINDS.map(t => `<option value="${t}"${t===''?' selected':''}>${t||'–'}</option>`).join('');
    rows.push(`<tr>
      <td style="text-align:center;"><input type="checkbox" class="shacl-cb" checked style="accent-color:var(--accent);"></td>
      <td><code>${p.name}</code><input type="hidden" class="shacl-prop" value="${p.name}"></td>
      <td>
        <select class="shacl-class" style="font-size:0.8rem; padding:4px 6px;">
          ${(onto.classes||[]).map(c=>`<option value="${c.name}"${c.name===p.domain?' selected':''}>${c.name}</option>`).join('')}
        </select>
      </td>
      <td><input type="number" class="shacl-min" min="0" style="padding:4px 6px; font-size:0.85rem; width:80px;" placeholder="–"></td>
      <td><input type="number" class="shacl-max" min="0" style="padding:4px 6px; font-size:0.85rem; width:80px;" placeholder="–"></td>
      <td><select class="shacl-dt" style="font-size:0.8rem; padding:4px 6px;">${xsdOpts}</select></td>
      <td><select class="shacl-nk" style="font-size:0.8rem; padding:4px 6px;">${nkOpts}</select></td>
    </tr>`);
  });
  tbody.innerHTML = rows.join('') || '<tr><td colspan="7" style="color:var(--text-muted);text-align:center;padding:12px;">No properties yet</td></tr>';
}

function shaclToggleAll(el) {
  document.querySelectorAll('.shacl-cb').forEach(cb => cb.checked = el.checked);
}

function collectConstraints() {
  const rows = document.querySelectorAll('#shaclTableBody tr');
  const result = [];
  rows.forEach(row => {
    const cb = row.querySelector('.shacl-cb');
    if (!cb || !cb.checked) return;
    result.push({
      property_name: row.querySelector('.shacl-prop').value,
      target_class:  row.querySelector('.shacl-class').value,
      min_count: row.querySelector('.shacl-min').value || null,
      max_count: row.querySelector('.shacl-max').value || null,
      datatype:  row.querySelector('.shacl-dt').value,
      node_kind: row.querySelector('.shacl-nk').value,
    });
  });
  return result;
}

async function generateShacl() {
  const constraints = collectConstraints();
  if (!constraints.length) { alert('Please select at least one property.'); return; }
  const adjust = document.getElementById('shaclAdjustOnto').checked;

  document.getElementById('shaclStatus').innerHTML =
    '<div class="alert alert-info"><div class="spinner"></div><span>Generating SHACL' +
    (adjust ? ' and adjusting ontology' : '') + '…</span></div>';
  document.getElementById('shaclResult').style.display = 'none';

  try {
    const res = await fetch(`${API}/api/generate-shacl`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: state.sessionId,
        constraints,
        adjust_ontology: adjust,
        llm_config: adjust ? state.llmConfig : null,
      }),
    });
    const text = await res.text();
    let data;
    try { data = JSON.parse(text); } catch(_) { throw new Error(text.slice(0,300)); }
    if (!res.ok) throw new Error(data.detail);

    shaclTurtle = data.shacl;
    document.getElementById('shaclCode').textContent = shaclTurtle;
    document.getElementById('shaclResult').style.display = 'block';

    let msg = '✅ SHACL generated.';
    if (data.ontology_adjusted) {
      state.currentOntology = data.ontology;
      state.currentTurtle   = data.turtle;
      if (data.iteration != null) state.iteration = data.iteration;   // eine Aenderung ist eine neue Iteration
      renderOntology(data.ontology, data.turtle, state.iteration);
      buildShaclTable(data.ontology);
      msg += ' Ontology adjusted and view updated.';
    }
    if (data.adjust_error) msg += ' ⚠️ Ontology adjustment failed: ' + escHtml(data.adjust_error);
    document.getElementById('shaclStatus').innerHTML = '<div class="alert alert-success">' + msg + '</div>';

  } catch(e) {
    document.getElementById('shaclStatus').innerHTML =
      '<div class="alert alert-error">❌ ' + escHtml(e.message) + '</div>';
  }
}

function downloadShacl() {
  const name = (state.currentOntology?.ontology_name || 'ontology').replace(/\s+/g,'_');
  const blob = new Blob([shaclTurtle], { type: 'text/turtle' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = name + '.shacl.ttl';
  a.click();
}

function copyShacl() {
  navigator.clipboard.writeText(shaclTurtle).then(() => alert('SHACL copied to clipboard!'));
}

// ── OOPS! Report ───────────────────────────────────────────────────────────────
function renderOopsReport(report) {
  state.oopsReport = report || null;
  saveProject();
  renderAttention(state.currentOntology ? state.evaluation : null, state._tools);
  const el = document.getElementById('oopsReport');
  if (!report) { el.style.display = 'none'; return; }

  const pitfalls = (report.pitfalls || []).filter(p => !['TIMEOUT','ERROR','UNREACHABLE'].includes(p.code));
  const errors   = (report.pitfalls || []).filter(p => ['TIMEOUT','ERROR','UNREACHABLE'].includes(p.code));
  const total    = pitfalls.length;
  const count    = imp => pitfalls.filter(p => p.importance === imp).length;
  const nCrit = count('critical'), nImp = count('important'), nMinor = count('minor');
  const plural   = n => `${n} pitfall${n !== 1 ? 's' : ''}`;
  const breakdown = [nCrit && `${nCrit} critical`, nImp && `${nImp} important`, nMinor && `${nMinor} minor`]
    .filter(Boolean).join(', ');
  const fixedList = (report.fixed || []).map(f => f.code).join(', ');

  let bannerClass, bannerIcon, bannerText;
  if (errors.length) {
    // Ein Fehler heisst "nicht geprueft" — nie als "sauber" darstellen.
    bannerClass = 'info'; bannerIcon = '⚠️';
    bannerText = `OOPS! check could not be completed: ${errors[0].description}`;
  } else if (total === 0) {
    bannerClass = 'clean'; bannerIcon = '✅';
    bannerText = report.fix_applied
      ? `OOPS! quality check: pitfalls ${fixedList} were fixed automatically; no pitfalls remain.`
      : 'OOPS! quality check: no pitfalls found.';
  } else if (report.fix_applied) {
    bannerClass = 'fixed'; bannerIcon = '🔧';
    bannerText = `OOPS! check: ${report.fixed_count ? `pitfall${report.fixed_count !== 1 ? 's' : ''} ${fixedList} fixed automatically` : 'automatic fix attempted'}. `
      + `After the fix, ${plural(total)} remain (${breakdown}).`
      + (report.still_unfixed ? ' Some critical or important pitfalls could not be fixed automatically — please review them.' : '');
  } else {
    bannerClass = 'info'; bannerIcon = '📋';
    bannerText = `OOPS! check: ${plural(total)} found (${breakdown}).`
      + (report.fix_error ? ` Automatic fix failed: ${report.fix_error}`
         : (nCrit || nImp) ? '' : ' Only critical and important pitfalls are fixed automatically; minor ones are for you to review.');
  }

  const impOrder = {critical: 0, important: 1, minor: 2};
  const sorted = [...pitfalls].sort((a, b) => (impOrder[a.importance] ?? 3) - (impOrder[b.importance] ?? 3));

  const pitfallsHtml = sorted.length === 0 ? '' : `
    <div class="oops-pitfall-list" id="oopsList" style="display:none">
      ${sorted.map(p => `
        <div class="oops-pitfall">
          <div class="pf-header">
            <span class="pf-code">${escHtml(p.code)}</span>
            <span class="pf-name">${escHtml(p.name)}</span>
            <span class="pf-imp ${escHtml(p.importance)}">${escHtml(p.importance)}</span>
          </div>
          ${p.description ? `<div class="pf-desc">${escHtml(p.description)}</div>` : ''}
          ${p.affected && p.affected.length ? `<div class="pf-affected">Affected${p.count > p.affected.length ? ` (${p.affected.length} of ${p.count})` : ''}: ${p.affected.map(a => escHtml(a.split(/[#/]/).pop() || a)).join(', ')}</div>` : ''}
        </div>`).join('')}
    </div>
    <button class="oops-toggle" id="oopsToggleBtn" onclick="toggleOopsList()">▶ Show details</button>`;

  el.innerHTML = `
    <div class="oops-banner ${bannerClass}">
      <div style="font-weight:700; margin-bottom:4px;">${bannerIcon} OOPS! Ontology Quality Check</div>
      <div>${escHtml(bannerText)}</div>
      ${(report.fix_changes || []).length ? `<details style="margin-top:6px;"><summary style="cursor:pointer;">
        ${report.fix_changes.length} change${report.fix_changes.length !== 1 ? 's' : ''} made by the automatic fix${report.fix_rejected ? ` (${report.fix_rejected} not applicable)` : ''}</summary>
        <ul class="lit-sources">${report.fix_changes.map(c => `<li>${escHtml(c)}</li>`).join('')}</ul></details>` : ''}
      ${pitfallsHtml}
    </div>`;
  el.style.display = 'block';
}

// Was die letzte Feedback-Runde geaendert hat (Edit-Operationen des Modells, vom Server angewendet)
function renderEditReport(r) {
  if (!r) return '';
  const applied = r.applied || [], rejected = r.rejected || [];
  const list = (applied.length ? `<ul class="lit-sources">${applied.map(a => `<li>${escHtml(a.summary)}</li>`).join('')}</ul>` : '')
    + (rejected.length ? `<div style="margin-top:6px; color:var(--warning);">Not applied:</div>
       <ul class="lit-sources">${rejected.map(x => `<li>${escHtml(x.op)} — ${escHtml(x.reason)}</li>`).join('')}</ul>` : '');
  return `<div class="alert alert-info" style="align-items:flex-start; flex-direction:column; gap:4px;">
    <div>${r.summary ? escHtml(r.summary) : (applied.length ? '' : 'The model made no change.')}</div>
    ${list ? `<details ${rejected.length ? 'open' : ''}><summary style="cursor:pointer;">${applied.length} change${applied.length !== 1 ? 's' : ''} applied${rejected.length ? `, ${rejected.length} not applied` : ''}</summary>${list}</details>` : ''}
    ${(r.dropped_provenance || []).length ? `<div style="color:var(--warning);">⚠️ Not taken over because they occur neither
      in the ontology, the literature corpus nor your request: ${escHtml(r.dropped_provenance.slice(0, 5).join('; '))}${r.dropped_provenance.length > 5 ? ' …' : ''}</div>` : ''}
    ${(r.new_issues || []).length ? `<div style="color:var(--warning);">⚠️ Check: ${escHtml(r.new_issues.slice(0, 3).join('; '))}</div>` : ''}
  </div>`;
}

// ── Competency Questions als Testfaelle ────────────────────────────────────────
// Abgedeckt ist eine CQ nur, wenn ihre SPARQL-Abfrage parst, nur existierende Terme nutzt und auf
// Beispieldaten ein Ergebnis liefert — geprueft vom Server mit rdflib, nicht vom LLM selbst.
async function runCQTests(fresh) {
  const el = document.getElementById('cqReport');
  if (!state.momo.competencyQuestions.some(c => (c.question || '').trim())) { el.style.display = 'none'; return; }
  if (!state.llmConfig) {        // auch nach einer Aktion aufgerufen: Hinweis statt alert
    el.innerHTML = '<div class="alert alert-info"><span>ℹ️</span><span>Configure the LLM first (Step 1) to run the CQ tests.</span></div>';
    el.style.display = 'block';
    return;
  }
  el.innerHTML = `<div class="alert alert-info"><div class="spinner"></div>
    <span>Testing competency questions: writing a SPARQL query per CQ and running it against the ontology…</span></div>`;
  el.style.display = 'block';
  try {
    await saveMomo();
    const res = await fetch(`${API}/api/momo/test-cqs`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: state.sessionId, llm_config: state.llmConfig, fresh: !!fresh }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Request failed');
    state.cqTests = data;
    recordUsage(data.usage, false);
    renderCQReport(data);
  } catch (e) {
    el.innerHTML = `<div class="oops-banner info">
      <div style="font-weight:700; margin-bottom:4px;">⚠️ Competency Question Tests</div>
      <div>The CQ tests could not be run: ${escHtml(e.message)}</div>
      <button class="oops-toggle" onclick="runCQTests()">↻ Retry</button></div>`;
  }
}

function renderCQReport(data) {
  saveProject();
  const el = document.getElementById('cqReport');
  const tests = data.tests || [];
  const failed = tests.filter(t => t.status !== 'passed');
  const label = { passed: 'covered', partial: 'partly covered', failed: 'failed', not_answerable: 'not answerable' };
  const bannerClass = !failed.length ? 'clean' : data.passed ? 'fixed' : 'failed';
  const icon = !failed.length ? '✅' : data.passed ? '⚠️' : '❌';

  const items = tests.map(t => `
    <div class="oops-pitfall">
      <div class="pf-header">
        <span class="pf-code">CQ ${t.cq}</span>
        <span class="pf-name">${escHtml(t.question)}</span>
        <span class="pf-imp ${escHtml(t.status)}">${label[t.status] || escHtml(t.status)}</span>
      </div>
      ${t.reused ? `<div class="pf-desc">Same query as in the last test - it still passes on this version of the ontology.</div>` : ''}
      ${t.error ? `<div class="pf-desc">${escHtml(t.error)}</div>` : ''}
      ${t.first_error ? `<div class="pf-desc">The first query found nothing on its sample data; a correction round
        ${t.corrected ? 'rewrote the query' : 'added sample data'}${t.status === 'failed' ? ', without success' : ''}.</div>` : ''}
      ${t.gap_check && t.gap_check.verdict === 'beyond' ? `<div class="pf-desc">The query's author noted: "${escHtml(t.leaves_out)}"
        — the check counts this as going beyond the question${t.gap_check.reason ? ` (${escHtml(t.gap_check.reason)})` : ''}.</div>` : ''}
      ${t.sparql ? `<div class="cq-pre">${escHtml(t.sparql)}</div>` : ''}
      ${t.rows && t.rows.length ? `<div class="pf-affected">Result${t.row_count > t.rows.length ? ` (first ${t.rows.length} of ${t.row_count})` : ''}:
        ${t.rows.map(r => escHtml(Object.entries(r).map(([k, v]) => `${k} = ${v}`).join(', '))).join(' · ')}</div>` : ''}
      ${t.expected ? `<div class="pf-desc" style="margin-top:4px;">Expected: ${escHtml(t.expected)}</div>` : ''}
    </div>`).join('');

  const sample = data.sample_triples
    ? `<div style="margin-top:10px; font-weight:600;">Sample data (${data.sample_triples} triples)</div>
       <div class="cq-pre">${escHtml(data.sample_data)}</div>` : '';
  const issues = (data.sample_issues || []).length
    ? `<div class="pf-desc" style="margin-top:8px;">Sample data triples dropped (terms the ontology does not declare, schema
       changes, or individuals of the wrong class for a property's domain or range):
       ${data.sample_issues.map(escHtml).join(' · ')}</div>` : '';

  el.innerHTML = `
    <div class="oops-banner ${bannerClass}">
      <div style="font-weight:700; margin-bottom:4px;">${icon} Competency Question Tests</div>
      <div>${data.passed} of ${data.total} competency questions covered. A CQ counts as covered only if its SPARQL query
        parses, uses only terms the ontology declares, returns a result on the generated sample data, and answers the
        whole question; a query that answers only part of it counts as partly covered.
        ${data.reused ? `${data.reused} passing ${data.reused === 1 ? 'query was' : 'queries were'} kept from the last test; the sample
          data is kept between tests and only extended, so results stay comparable across iterations.` : ''}</div>
      <div class="oops-pitfall-list" id="cqTestList" style="display:none">${items}${sample}${issues}</div>
      <div style="display:flex; gap:16px; flex-wrap:wrap;">
        <button class="oops-toggle" id="cqTestToggleBtn" onclick="toggleCQList()">▶ Show details</button>
        <button class="oops-toggle" onclick="runCQTests()">↻ Re-run tests</button>
        <button class="oops-toggle" onclick="confirm('Discard the stored sample data and queries and let the model write all tests anew? Results then are not comparable with earlier iterations.') && runCQTests(true)"
          title="Kept sample data and queries make iterations comparable; start over when they no longer fit the ontology">⟲ Test from scratch</button>
        ${failed.length ? `<button class="oops-toggle" onclick="cqFailuresToFeedback()">✎ Use failed CQs as feedback</button>` : ''}
      </div>
    </div>`;
  el.style.display = 'block';
}

function toggleCQList() {
  const list = document.getElementById('cqTestList');
  const btn  = document.getElementById('cqTestToggleBtn');
  const hidden = list.style.display === 'none';
  list.style.display = hidden ? 'flex' : 'none';
  btn.textContent = hidden ? '▼ Hide details' : '▶ Show details';
}

function cqFailuresToFeedback() {
  const failed = (state.cqTests?.tests || []).filter(t => t.status !== 'passed');
  showRefineTab('edit');
  const box = document.getElementById('feedbackText');
  box.value = 'The ontology cannot answer these competency questions. Extend it so that it can:\n' +
    failed.map(t => `- CQ ${t.cq}: ${t.question}\n  Problem: ${t.error}`).join('\n');
  box.scrollIntoView({ behavior: 'smooth', block: 'center' });
  box.focus();
}

// ── Schritt 9: Evaluate & Refine (PLAN.md Phase 4; Reiter und Uebersicht DECISIONS 126) ──
function showRefineTab(name) {
  state.refineTab = name;
  document.querySelectorAll('#panel9 .subtab').forEach(t => {
    const on = t.id === 'tab-' + name;
    t.classList.toggle('active', on);
    t.setAttribute('aria-selected', on ? 'true' : 'false');
  });
  document.querySelectorAll('#panel9 .subtab-panel').forEach(p => p.classList.toggle('active', p.id === 'refine-' + name));
}

function renderRefineView() {
  const onto = state.currentOntology;
  document.getElementById('refineEmpty').style.display = onto ? 'none' : 'flex';
  document.getElementById('refineView').style.display = onto ? 'block' : 'none';
  if (!onto) return;
  const ev = state.evaluation;
  document.getElementById('refineSummary').innerHTML = `<strong>${escHtml(onto.ontology_name || 'Ontology')}</strong> ·
    ${(onto.classes || []).length} classes · ${(onto.properties || []).length} properties${(onto.restrictions || []).length
      ? ` · ${onto.restrictions.length} class restrictions` : ''} · ${(onto.individuals || []).length} individuals${
      state.ontologyImported ? ' · loaded from a file' : ''}${ev && ev.evaluated_at
      ? ` · evaluated ${escHtml(new Date(ev.evaluated_at).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }))}` : ''} ·
    <a href="#" onclick="goTo(6); return false;">view in step 8</a>`;
  showRefineTab(state.refineTab || 'overview');
}

// Symbole fuer die Laeufe einer Frage: voll, teilweise, nicht - durch die Form unterscheidbar, nicht nur die Farbe
const RUN_ICON = {
  full: '<svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><circle cx="7" cy="7" r="6" fill="var(--success)"/></svg>',
  partial: '<svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><circle cx="7" cy="7" r="5.25" fill="none" stroke="var(--warning)" stroke-width="1.5"/><path d="M7 1.75a5.25 5.25 0 0 1 0 10.5z" fill="var(--warning)"/></svg>',
  none: '<svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><circle cx="7" cy="7" r="5.25" fill="none" stroke="var(--faint)" stroke-width="1.5"/></svg>',
};
const ATT_ICON = {
  bad: '<svg class="att-icon" viewBox="0 0 20 20" role="img" aria-label="Problem"><path d="M10 2l8.5 15h-17z" fill="var(--error)"/><path d="M10 8v4M10 14.4v.1" stroke="#fff" stroke-width="1.8" stroke-linecap="round"/></svg>',
  warn: '<svg class="att-icon" viewBox="0 0 20 20" role="img" aria-label="Warning"><circle cx="10" cy="10" r="8.5" fill="var(--warning)"/><path d="M10 5.5v5.2M10 13.6v.1" stroke="#fff" stroke-width="1.8" stroke-linecap="round"/></svg>',
  tool: '<svg class="att-icon" viewBox="0 0 20 20" role="img" aria-label="Repair tool"><rect x="2" y="2" width="16" height="16" rx="4" fill="var(--accent-soft)"/><path d="M6 10h8M10 6v8" stroke="var(--accent)" stroke-width="1.8" stroke-linecap="round"/></svg>',
  info: '<svg class="att-icon" viewBox="0 0 20 20" role="img" aria-label="Note"><circle cx="10" cy="10" r="8.5" fill="none" stroke="var(--text-muted)" stroke-width="1.5"/><path d="M10 9v5M10 6.2v.1" stroke="var(--text-muted)" stroke-width="1.8" stroke-linecap="round"/></svg>',
};

function openEvalDetails() {
  showRefineTab('overview');
  const d = document.getElementById('evalDetails');
  if (d) { d.open = true; d.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
}

function scrollToOops() {
  showRefineTab('overview');
  const el = document.getElementById('oopsReport');
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ── Evaluation (Stufe A aus EVALUATION.md) ─────────────────────────────────────
// Nur deterministische Masse; Modellaufrufe nur, um CQs in SPARQL zu uebersetzen. Das Ergebnis haengt an der
// Iteration - nach einer Aenderung der Ontologie ist es als veraltet markiert.
function renderEvaluation(rep) {
  const el = document.getElementById('evalReport');
  document.getElementById('evalDownloadBtn').style.display = rep ? '' : 'none';
  if (!state.currentOntology) { el.style.display = 'none'; renderRepairTools(null); renderAttention(null, null); return; }
  el.style.display = 'block';
  if (state.currentStep === 9) renderRefineView();
  if (!rep) {
    el.innerHTML = `<div class="panel-card" style="padding:16px 20px;">
      <div style="font-weight:600; margin-bottom:4px;">Not evaluated yet</div>
      <div class="lit-meta">Evaluate measures how well your and the literature's competency questions are answered, how much of the
        concept inventory became classes, how traceable every class is, the structure, and a logical check with the
        HermiT reasoner – measured, not judged by a model. Evaluate 3× tests the questions three times for the spread.</div></div>`;
    document.getElementById('evalQuestions').innerHTML = '';
    renderRepairTools(null);
    renderAttention(null, null);
    return;
  }
  const outdated = rep.iteration !== state.iteration;
  const m = rep.metrics, cov = rep.coverage, tr = rep.traceability, rs = rep.reasoner || {};
  const pct = v => v == null ? '–' : `${v}`;
  const level = (x, good, ok) => x == null ? '' : x >= good ? '' : x >= ok ? 'warn' : 'bad';
  const pill = (cls, text) => cls && text ? `<span class="pill ${cls}">${escHtml(text)}</span>` : '';
  const score = (title, value, unit, sub, p = '') => `<div class="score">
      <div class="score-head"><span class="score-title">${title}</span>${p}</div>
      <div class="score-value">${value}${unit ? ` <small>${unit}</small>` : ''}</div>
      ${sub ? `<div class="score-sub">${sub}</div>` : ''}</div>`;
  const scores = [];
  // Evaluate 3x: Mittel und Streuung der unabhaengigen Laeufe statt des einen Ergebnisses
  const cqScore = (c, r, title, good, ok) => {
    if (r) {
      const lv = level(100 * r.full.mean / (r.total || 1), good, ok);
      return score(title, r.full.mean, `/ ${r.total} in full`, `${r.runs} runs: ${r.full.runs.join(' · ')} · sd ${r.full.sd}`,
                   r.varying ? pill('warn', `${r.varying} vary`) : pill(lv, lv === 'bad' ? 'low' : lv ? 'check' : ''));
    }
    const lv = level(c.full_pct, good, ok);
    return score(title, c.full, `/ ${c.total} in full`, `${c.partial} partly · one test run`, pill(lv, lv === 'bad' ? 'low' : lv ? 'check' : ''));
  };
  if (rep.cq) scores.push(cqScore(rep.cq, rep.cq_repeats, 'Your questions', 90, 60));
  if (rep.holdout) scores.push(cqScore(rep.holdout, rep.holdout_repeats, 'Hold-out questions', 70, 40));
  if (cov.available) scores.push(score('Central concepts as a class', pct(cov.central_covered_pct), '%',
    `${cov.central_covered} of ${cov.central_concepts}${cov.central_decided ? ` · ${cov.central_decided} decided` : ''}${
      cov.central_missing ? ` · ${cov.central_missing} missing` : ''}`, pill(level(cov.central_covered_pct, 80, 50), 'check')));
  const hi = rep.hierarchy;
  if (hi && hi.available && hi.relations) scores.push(hi.realized_or_declined_pct != null && hi.declined_count
    ? score('Literature hierarchy', pct(hi.realized_or_declined_pct), '% decided',
            `${hi.realized} of ${hi.relations} realized · ${hi.declined_count} declined with a reason`)
    : score('Literature hierarchy', `${hi.realized}`, `/ ${hi.relations} realized`, 'broader/narrower relations of the sources',
            pill(level(hi.realized_pct, 80, 50), 'check')));
  const df = rep.definitions;
  if (df && df.available && df.classes) scores.push(score('Decided definitions', df.ok, `/ ${df.classes} carried`,
    df.undecided ? `${df.undecided} conflicts undecided` : 'as the team decided them',
    df.missing.length ? pill('bad', `${df.missing.length} missing`) : df.deviating.length ? pill('warn', `${df.deviating.length} differ`) : ''));
  if (m.top_level_relations !== undefined) scores.push(score('Top-level relations', topLevelPerClass(m).toFixed(2), 'per class',
    `${m.top_level_relations} for ${m.classes} classes · target: about ${TOP_LEVEL_PER_CLASS_MAX} or fewer`,
    tooManyTopLevel(m) ? pill('warn', 'above') : pill('ok', 'met')));
  if (rs.available) {
    const o = rs.ontology || {}, d = rs.with_sample_data, nOutside = Object.keys(rs.datatypes_outside_owl2 || {}).length;
    const v = o.error ? 'Not checked' : !o.consistent ? 'Inconsistent' : o.unsatisfiable.length ? `${o.unsatisfiable.length} unsatisfiable` : 'Consistent';
    const sub = o.error ? 'the reasoner refused the ontology'
      : d ? (d.consistent === false ? 'the sample data contradict the axioms' : d.consistent ? 'also with the sample data' : '')
      : nOutside ? `${nOutside} datatype${nOutside > 1 ? 's' : ''} outside OWL 2 replaced` : '';
    scores.push(score('Reasoner (HermiT)', v, '', sub,
      o.error ? pill('bad', 'error') : (!o.consistent || o.unsatisfiable.length) ? pill('bad', 'problem')
        : (d && d.consistent === false) ? pill('warn', 'sample data') : pill('ok', 'ok')));
  } else scores.push(score('Reasoner (HermiT)', 'Not run', '', escHtml(rs.reason || ''), pill('warn', 'off')));
  if (tr.basis === 'none') scores.push(score('Traceable classes', '–', '', 'not measured: no literature and no tested questions'));
  else scores.push(score('Traceable classes', pct(tr.untraceable_pct == null ? null : Math.round((100 - tr.untraceable_pct) * 10) / 10), '%',
    tr.basis === 'competency questions' ? `${tr.untraceable.length} without a passing question (no literature)`
      : `${tr.untraceable.length} without source, concept or passing question`, pill(level(100 - (tr.untraceable_pct || 0), 90, 75), 'check')));
  if (m.restrictions || rep.restriction_candidates) scores.push(score('Class restrictions', m.restrictions || 0,
    m.restrictions ? `on ${m.classes_with_restriction} classes` : '',
    rep.restriction_candidates ? `${rep.restriction_candidates} more class pairs with evidence` : 'no further pairs with evidence'));
  if (m.sibling_groups) scores.push(score('Sibling groups with disjointness', m.sibling_groups_with_disjointness, `/ ${m.sibling_groups}`,
    'classes on one level that cannot share instances', pill(level(100 * m.sibling_groups_with_disjointness / m.sibling_groups, 80, 40), 'check')));

  const list = (items, empty = '—') => items && items.length ? items.map(x => escHtml(x)).join(', ') : empty;
  const reasonerDetail = !rs.available ? '' : Object.entries({ 'ontology alone': rs.ontology, 'ontology + CQ sample data': rs.with_sample_data })
    .filter(([, r]) => r).map(([k, r]) => `<div><strong>${k}:</strong> ${r.error ? escHtml(r.error)
      : `${r.consistent ? 'consistent' : 'INCONSISTENT'}${r.unsatisfiable && r.unsatisfiable.length ? `; unsatisfiable classes: ${list(r.unsatisfiable)}` : ''}`}</div>`).join('');
  const details = `
    <div class="eval-section">
      ${rep.holdout && rep.holdout_excluded ? `<div class="lit-meta">${rep.holdout_excluded} literature questions were not eligible for the
        hold-out test: the competency-question suggestions in step 5 had already seen them.</div>` : ''}
      ${cov.available ? `<h4>Concept inventory</h4>
        <div>${cov.covered} of ${cov.concepts} concepts represented by a class (${pct(cov.covered_pct)}%); central concepts: ${cov.central_covered} of ${cov.central_concepts}.</div>
        <table class="lit-table" style="margin:6px 0;"><thead><tr><th>Theme</th><th>Concepts</th><th>Covered</th></tr></thead><tbody>
        ${cov.themes.map(t => `<tr><td>${escHtml(t.name)}</td><td>${t.concepts}</td><td>${pct(t.covered_pct)}%</td></tr>`).join('')}</tbody></table>
        <div><strong>Central concepts missing:</strong> ${list(cov.missing_central.map(x => `${x.label} (${x.sources})`), 'none')}</div>
        ${(cov.other_central || []).length ? `<div><strong>Represented other than as a class</strong> (estimated from names — check):
          ${list(cov.other_central.map(x => `${x.label} → ${x.kind === 'individual' ? 'individual' : 'in property'} ${x.as}`))}</div>` : ''}
        ${(cov.decided_central || []).length ? `<div><strong>Deliberately not modeled</strong> (decided by the model
          while filling gaps — reconsider to have it proposed again):
          <button class="oops-toggle" onclick="reconsiderDeclined(null)">↺ Reconsider all ${cov.central_decided}</button>
          <ul class="lit-sources">${cov.decided_central.map((x, i) => `<li><strong>${escHtml(x.label)}</strong>: ${escHtml(x.as)}
            <button class="oops-toggle" onclick="reconsiderDeclined(${i})">↺ Reconsider</button></li>`).join('')}</ul></div>` : ''}` : ''}
      ${decisionsSection(rep.decisions)}
      ${df && df.available ? `<h4>Decided definitions</h4>
        <div>${df.decided} of ${df.conflicts} conflicting definitions decided${df.open ? ` (${df.open} left open)` : ''}${df.undecided
          ? ` · ${df.undecided} undecided — decide them in step 4 (Project Context)` : ''}. ${df.ok} of ${df.classes} decided classes carry their definition.</div>
        ${df.deviating.length ? `<div><strong>Description differs from the decision:</strong>
          <ul class="lit-sources">${df.deviating.map(r => `<li><strong>${escHtml(r.found)}</strong>${r.found !== r.class ? ` (decided as ${escHtml(r.class)})` : ''}:
            ${escHtml(r.actual || '(none)')} <span class="lit-meta">— decided: ${escHtml(r.expected)}</span></li>`).join('')}</ul></div>` : ''}
        ${df.missing.length ? `<div><strong>Missing classes:</strong> ${list(df.missing.map(r => `${r.class} (${r.concept})`))}</div>` : ''}` : ''}
      ${hi && hi.available ? `<h4>Hierarchy against the literature</h4>
        <div>${hi.realized} of ${hi.relations} broader/narrower relations stated by the sources between classes of the
          ontology are realized (${pct(hi.realized_pct)}%)${hi.declined_count ? `; ${hi.declined_count} were declined with a reason
          (realized or declined: ${pct(hi.realized_or_declined_pct)}%)` : ''}. ${hi.attachable_count} missing central concepts have a broader
          term that already is a class; ${hi.open_taxonomies ?? hi.relevant_taxonomies} taxonomies from the papers are not yet applied or decided.</div>
        ${hi.unrealized.length ? `<div><strong>Not realized:</strong> ${list(hi.unrealized.slice(0, 40).map(u => `${u.narrower} ⊂ ${u.broader}`))}${hi.unrealized_count > 40 ? ' …' : ''}</div>` : ''}` : ''}
      <h4>Traceability</h4>
      <div>With sources: ${pct(tr.with_sources_pct)}% · linked to the inventory: ${pct(tr.linked_to_inventory_pct)}% ·
        used or reached (domain, range) by a passing CQ query: ${pct(tr.used_by_passing_cq_pct)}% · properties used by any CQ query: ${pct(tr.properties_used_by_cq_pct)}%</div>
      ${tr.basis === 'competency questions' ? `<div class="lit-meta">There is no literature, so a class can only be traced to a
        competency question whose query passes, or to a key notion.</div>` : ''}
      ${tr.basis === 'none' ? `<div class="lit-meta">Not measured: without literature only a passing competency-question
        query can trace a class, and no questions were tested.</div>` : `<div><strong>Untraceable classes</strong> (candidates for
        superfluous elements — review, a helper class can be legitimate): ${list(tr.untraceable, 'none')}</div>`}
      <h4>Structure</h4>
      <div>${m.classes} classes, ${m.object_properties} object and ${m.datatype_properties} datatype properties, ${m.individuals} individuals,
        ${m.axioms} axioms${m.restrictions ? `, ${m.restrictions} class restrictions on ${m.classes_with_restriction} classes` : ''} in ${m.modules} modules · hierarchy depth max ${m.max_depth}, mean ${m.avg_depth} · ${m.root_classes} root classes ·
        relationship richness ${m.relationship_richness} · attribute richness ${m.attribute_richness}${m.external_links !== undefined
        ? ` · ${m.external_links} links to reused vocabularies${(m.linked_vocabularies || []).length ? ` (${escHtml(m.linked_vocabularies.join(', '))})` : ''}` : ''}</div>
      <div>Classes with a description: ${pct(m.classes_with_description_pct)}% · labelled in all languages (${escHtml(m.label_languages.join(', '))}): ${pct(m.entities_labelled_in_all_languages_pct)}%</div>
      <div><strong>Unconnected classes:</strong> ${list(m.orphan_classes, 'none')}</div>
      <div><strong>Properties without domain or range:</strong> ${list(m.properties_without_domain_or_range, 'none')}</div>
      ${(m.inverse_conflicts || []).length ? `<div><strong>Second inverses</strong> (a property with two inverses makes them
        equivalent): ${list(m.inverse_conflicts)}</div>` : ''}
      ${reasonerDetail ? `<h4>Reasoner (HermiT)</h4>${reasonerDetail}` : ''}
      ${Object.keys(rs.datatypes_outside_owl2 || {}).length ? `<div><strong>Datatypes outside OWL 2 DL</strong> (replaced by
        rdfs:Literal for the reasoner; the ontology itself keeps them): ${list(Object.entries(rs.datatypes_outside_owl2)
        .map(([dt, ps]) => dt + (ps.length ? ` (${ps.join(', ')})` : ' (in the sample data)')))}</div>` : ''}
      ${(rep.notes || []).length ? `<h4>Notes</h4>${rep.notes.map(n => `<div>${escHtml(n)}</div>`).join('')}` : ''}
    </div>`;
  el.innerHTML = `
    <div class="eval-status">Iteration ${rep.iteration} · ${escHtml(new Date(rep.evaluated_at).toLocaleString())}
      ${outdated ? '<span class="pill warn">outdated – the ontology has changed since</span>' : ''}</div>
    <div class="score-grid">${scores.join('')}</div>
    ${comparisonHtml(rep)}
    <details id="evalDetails" class="panel-card" style="padding:12px 20px;"><summary style="cursor:pointer; font-weight:600;">All measurements</summary>${details}</details>`;
  renderEvalQuestions(rep);
  markDone(9);
  const tools = improve(cov, hi, rep.upper_candidates !== undefined ? rep.upper_candidates
    : m.root_classes > 1 ? m.root_classes : 0, m, rep.align_candidates, df, rep.restriction_candidates);   // Berichte von vor der oberen Schicht: Zahl der Wurzelklassen
  state._tools = tools;
  renderRepairTools(tools);
  renderAttention(rep, tools);
}

// Vergleich mit der vorigen Evaluation einer anderen Iteration (DECISIONS 136): was eine Reparatur geaendert hat
const COMPARE_ROWS = [
  ['classes', 'Classes', 0, 1], ['object_properties', 'Object properties', 0, 0], ['restrictions', 'Class restrictions', 0, 1],
  ['central_as_class_pct', 'Central concepts as a class (%)', 1, 1], ['central_represented_pct', 'Central concepts represented (%)', 1, 1],
  ['hierarchy_decided_pct', 'Literature hierarchy decided (%)', 1, 1], ['root_classes', 'Root classes', 0, -1],
  ['top_level_relations_per_class', 'Top-level relations per class', 2, -1],
  ['cq_full', 'Your questions in full', 1, 1], ['holdout_full', 'Hold-out questions in full', 1, 1]];
function comparisonHtml(rep) {
  const p = rep.previous;
  if (!p || !p.figures) return '';
  const cur = {
    classes: rep.metrics.classes, object_properties: rep.metrics.object_properties, restrictions: rep.metrics.restrictions,
    root_classes: rep.metrics.root_classes, top_level_relations_per_class: rep.metrics.top_level_relations_per_class,
    central_as_class_pct: (rep.coverage || {}).central_covered_pct, central_represented_pct: (rep.coverage || {}).central_represented_pct,
    hierarchy_decided_pct: (rep.hierarchy || {}).realized_or_declined_pct,
    cq_full: rep.cq_repeats ? rep.cq_repeats.full.mean : (rep.cq || {}).full,
    holdout_full: rep.holdout_repeats ? rep.holdout_repeats.full.mean : (rep.holdout || {}).full };
  const rows = COMPARE_ROWS.filter(([k]) => p.figures[k] != null && cur[k] != null).map(([k, label, digits, better]) => {
    const a = Number(p.figures[k]), b = Number(cur[k]), d = b - a;
    const cls = Math.abs(d) < 1e-9 ? 'neutral' : (d > 0) === (better > 0) ? 'ok' : better ? 'warn' : 'neutral';
    return `<tr><td>${label}</td><td>${a.toFixed(digits)}</td><td>${b.toFixed(digits)}</td>
      <td>${Math.abs(d) < 1e-9 ? '–' : `<span class="pill ${cls}">${d > 0 ? '+' : ''}${d.toFixed(digits)}</span>`}</td></tr>`;
  }).join('');
  return `<details class="panel-card" style="padding:12px 20px;" open><summary style="cursor:pointer; font-weight:600;">
      Compared with iteration ${p.iteration} (${escHtml(new Date(p.evaluated_at).toLocaleString())})</summary>
    <table class="compare-table"><thead><tr><th></th><th>Iteration ${p.iteration}</th><th>Iteration ${rep.iteration}</th><th>Change</th></tr></thead>
    <tbody>${rows}</tbody></table>
    <div class="lit-meta">Question results vary between test runs by up to two or three of ten; Evaluate 3× shows whether a change is real.</div></details>`;
}

// Je Frage die Laeufe als Symbole (Evaluate 3x) oder das eine Ergebnis; der Grund aus jedem Lauf, wo es ihn gibt
function renderEvalQuestions(rep) {
  const el = document.getElementById('evalQuestions');
  if (!rep || (!rep.cq && !rep.holdout)) {
    el.innerHTML = '<div class="lit-meta" style="margin-bottom:16px;">Evaluate to see how each question is answered.</div>'
      + '<div id="holdoutReview"></div>';
    loadHoldout();
    return;
  }
  const section = (c, r, title) => {
    if (!c) return '';
    const rows = c.questions.map((q, i) => {
      const rq = r && r.questions.find(x => x.question === q.question);
      const levels = rq ? rq.levels : [q.level];
      const same = levels.every(l => l === levels[0]);
      const result = !same ? pill('warn', `varies · ${levels.filter(l => l === 'full').length} of ${levels.length}`)
        : levels[0] === 'full' ? pill('ok', rq ? `full in all ${levels.length}` : 'full')
        : pill('neutral', levels[0] === 'partial' ? (rq ? `partly in all ${levels.length}` : 'partly') : (rq ? `not in all ${levels.length}` : 'not answered'));
      const errs = rq && rq.errors ? rq.errors.map((e, k) => e ? `Run ${k + 1}: ${e}` : '').filter(Boolean)
        : (q.level !== 'full' && q.error ? [(rq ? 'Run 1: ' : '') + q.error] : []);
      return `<div class="q-row"><span class="q-num">${i + 1}</span>
        <div class="q-text">${escHtml(q.question)}${errs.length ? `<div class="q-why">${errs.map(escHtml).join('<br>')}</div>` : ''}</div>
        <span class="q-runs" role="img" aria-label="${escHtml(levels.join(', '))}">${levels.map(l => RUN_ICON[l] || RUN_ICON.none).join('')}</span>
        <span class="q-result">${result}</span></div>`;
    }).join('');
    const summary = r ? `in full: ${r.full.runs.join(' · ')} – mean ${r.full.mean}, sd ${r.full.sd}${r.varying ? ` · ${r.varying} vary` : ''}`
      : `${c.full} of ${c.total} in full · ${c.partial} partly`;
    return `<div class="panel-card"><div class="panel-card-head"><h3>${title}</h3><span class="lit-meta">${summary}</span></div>${rows}</div>`;
  };
  const pill = (cls, text) => `<span class="pill ${cls}">${escHtml(text)}</span>`;
  el.innerHTML = `<div class="run-legend">
      <span>${rep.cq_repeats || rep.holdout_repeats ? 'Each run wrote new sample data and SPARQL queries; the first is kept as this iteration’s test.' : 'One test run - Evaluate 3× shows the spread.'}</span>
      <span>${RUN_ICON.full} answered in full</span><span>${RUN_ICON.partial} partly</span><span>${RUN_ICON.none} not answered</span></div>
    ${section(rep.cq, rep.cq_repeats, 'Your competency questions')}
    ${section(rep.holdout, rep.holdout_repeats, 'Questions from the literature the generation did not see (hold-out)')}
    <div id="holdoutReview"></div>`;
  loadHoldout();
}

// Die Hold-out-Fragen der naechsten Evaluation: gespeichert, vom Team durchzusehen (DECISIONS 133)
async function loadHoldout() {
  if (!state.sessionId) return;
  try {
    const r = await fetch(`${API}/api/holdout`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: state.sessionId }) });
    if (r.ok) renderHoldoutReview(await r.json());
  } catch (e) { /* ohne Server bleibt der Abschnitt leer */ }
}
async function holdoutAction(path, question) {
  const r = await fetch(`${API}/api/holdout${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: state.sessionId, question: question || '' }) });
  const d = await r.json();
  if (!r.ok) { alert(d.detail || 'Request failed'); return; }
  renderHoldoutReview(d);
}
function removeHoldout(i) { holdoutAction('/remove', state.holdoutSet.questions[i].question); }
function resetHoldout() {
  if (confirm('Choose the hold-out questions again? Removed questions can be chosen again.')) holdoutAction('/reset');
}
function renderHoldoutReview(d) {
  state.holdoutSet = d;
  const el = document.getElementById('holdoutReview');
  if (!el) return;
  if (!d.questions.length) {      // sagen, warum (DECISIONS 137)
    el.innerHTML = !d.pool ? '' : `<div class="panel-card"><div class="panel-card-head"><h3>No hold-out questions</h3></div>
      <div class="lit-meta">None of the ${d.pool} questions from the sources is left for a hold-out test: ${d.shown} of them
      were shown to the question suggestions in step 5 - a question a model has seen can shape the ontology, so it cannot
      test it - and the rest are similar to your own questions or were removed.</div></div>`;
    return;
  }
  const rows = d.questions.map((q, i) => `<div class="q-row"><span class="q-num">${i + 1}</span>
      <div class="q-text">${escHtml(q.question)}<div class="q-why">${q.central.length
        ? `central concepts: ${escHtml(q.central.join(', '))}${q.theme ? ` · theme: ${escHtml(q.theme)}` : ''}`
        : 'names no central concept of the literature'}${q.single_source.length
        ? ` · only in one source: ${escHtml(q.single_source.join(', '))}` : ''}${(q.modal || []).length
        ? ` · asks what ${escHtml(q.modal.join('/'))} be - sample data answer that only in part` : ''}</div></div>
      <button class="oops-toggle" onclick="removeHoldout(${i})" title="Take this question out of the hold-out set; the next candidate takes its place">✕ Remove</button></div>`).join('');
  el.innerHTML = `<div class="panel-card"><div class="panel-card-head"><h3>Hold-out questions for the next evaluation</h3>
      <button class="oops-toggle" onclick="resetHoldout()">Choose again</button></div>
    <div class="lit-meta" style="margin-bottom:8px;">Chosen from the questions of the papers by the central concepts they name
      (two or more sources), spread over the themes of the inventory. Remove a question that does not fit the use case:
      the next candidate takes its place from the next evaluation on${d.removed.length ? ` · ${d.removed.length} removed` : ''}.</div>
    ${rows}</div>`;
}

// "Needs attention": Probleme und Reparaturwerkzeuge in einer Liste, das Wichtigste zuerst, je mit einer Aktion
function renderAttention(rep, tools) {
  const el = document.getElementById('attention');
  if (!el) return;
  const items = [];
  const btn = (label, onclick, primary) => `<button class="btn ${primary ? 'btn-primary' : 'btn-secondary'} btn-sm" onclick="${onclick}">${escHtml(label)}</button>`;
  if (rep) {
    const rs = rep.reasoner || {}, o = rs.ontology || {}, d = rs.with_sample_data || {};
    if (rep.iteration !== state.iteration)
      items.push(['warn', 'The evaluation is outdated', `It measured iteration ${rep.iteration}; the ontology has changed since.`, btn('Evaluate', 'runEvaluation()', true)]);
    if (rs.available && o.error)
      items.push(['bad', 'The reasoner could not check this ontology', String(o.error).split('\n').slice(-1)[0].slice(0, 220), btn('Show details', 'openEvalDetails()')]);
    else if (rs.available && o.consistent === false)
      items.push(['bad', 'The ontology is inconsistent', 'No individual can satisfy all axioms together.', btn('Show details', 'openEvalDetails()')]);
    else if (rs.available && (o.unsatisfiable || []).length)
      items.push(['bad', `${o.unsatisfiable.length} class${o.unsatisfiable.length !== 1 ? 'es are' : ' is'} unsatisfiable`,
        `They can have no instances: ${o.unsatisfiable.slice(0, 6).join(', ')}${o.unsatisfiable.length > 6 ? ' …' : ''}`, btn('Show details', 'openEvalDetails()')]);
    if (rs.available && d.consistent === false)
      items.push(['warn', 'The sample data contradict the axioms', 'An "only" restriction or a disjointness rules out what the test data state.', btn('Show details', 'openEvalDetails()')]);
    const vary = (rep.cq_repeats || {}).varying || 0;
    if (vary) items.push(['warn', 'Your questions vary between test runs', `${vary} of ${rep.cq_repeats.total} questions got different results in the ${rep.cq_repeats.runs} runs – compare them before judging a change.`, btn('Compare runs', "showRefineTab('questions')")]);
    else if (rep.cq && !rep.cq_repeats && rep.cq.full < rep.cq.total)
      items.push(['info', `${rep.cq.total - rep.cq.full} of ${rep.cq.total} questions not answered in full`, 'One test run; Evaluate 3× shows whether that is the ontology or the test.', btn('See questions', "showRefineTab('questions')")]);
  }
  const oops = state.oopsReport;
  if (oops) {
    const real = (oops.pitfalls || []).filter(p => !['TIMEOUT', 'ERROR', 'UNREACHABLE'].includes(p.code));
    const serious = real.filter(p => ['critical', 'important'].includes(p.importance)).length;
    if (serious) items.push(['warn', `OOPS! reports ${serious} critical or important pitfall${serious !== 1 ? 's' : ''}`, 'The automatic fix could not resolve them.', btn('Show pitfalls', 'scrollToOops()')]);
    else if ((oops.pitfalls || []).some(p => ['TIMEOUT', 'ERROR', 'UNREACHABLE'].includes(p.code)))
      items.push(['info', 'The OOPS! check could not run', 'The service was not reachable; it is tried again after the next change.', '']);
  }
  (tools && tools.list || []).forEach(t => items.push(['tool', t.why, 'Repair tool · ' + t.what, `<button class="btn btn-secondary btn-sm" onclick="${t.onclick}" title="${escHtml(t.title || '')}">${escHtml(t.label)}</button>`]));
  if (rep && rep.traceability && rep.traceability.basis !== 'none' && (rep.traceability.untraceable || []).length)
    items.push(['info', `${rep.traceability.untraceable.length} class${rep.traceability.untraceable.length !== 1 ? 'es cannot' : ' cannot'} be traced`,
      'No source, no concept of the literature and no passing question – a helper class can still be right.', btn('Show list', 'openEvalDetails()')]);
  if (!rep && !items.length) { el.innerHTML = ''; return; }
  el.innerHTML = `<div class="panel-card"><div class="panel-card-head"><h3>Needs attention</h3>
      <span class="lit-meta">${items.length ? `${items.length} item${items.length !== 1 ? 's' : ''} · most important first` : ''}</span></div>
    ${items.length ? items.map(([sev, title, sub, action]) => `<div class="att-row">${ATT_ICON[sev]}
      <div class="att-text"><div class="att-title">${escHtml(title.charAt(0).toUpperCase() + title.slice(1))}</div><div class="att-sub">${escHtml(sub)}</div></div>
      ${action}</div>`).join('') : '<div class="att-row"><div class="att-text att-sub">Nothing needs attention: the evaluation found no gap a repair tool addresses.</div></div>'}</div>`;
}

// Richtwerte relativ zur Groesse der Ontologie, wie in relations.py (DECISIONS 130)
const TOP_LEVEL_PER_CLASS_MAX = 0.3, TOP_LEVEL_MIN = 10, CORE_PER_CLASS = [0.15, 0.25];
// aeltere Berichte kennen den Wert je Klasse nicht: dann aus Anzahl und Klassen
const topLevelPerClass = m => m.top_level_relations_per_class ?? (m.classes ? m.top_level_relations / m.classes : 0);
const tooManyTopLevel = m => m.top_level_relations >= TOP_LEVEL_MIN && topLevelPerClass(m) > TOP_LEVEL_PER_CLASS_MAX;
function coreRelationsRange(nClasses) {
  const lo = Math.max(3, Math.round(CORE_PER_CLASS[0] * nClasses));
  return [lo, Math.max(lo + 2, Math.round(CORE_PER_CLASS[1] * nClasses))];
}
// Luecken schliessen und Struktur verbessern: die Aktionen, mit dem Umfang aus der Evaluation - als Liste, aus der
// der Reiter "Repair tools" und die Liste "Needs attention" entstehen
function improve(cov, hi, nUpper, m, nAlign, df, nRestr) {
  const nDefs = df && df.available ? df.deviating.length + df.missing.length : 0;
  const nConcepts = cov && cov.available ? cov.central_missing || 0 : 0;
  const openTax = hi && hi.available ? hi.open_taxonomies ?? hi.relevant_taxonomies : 0;   // aeltere Berichte ohne Feld
  const nHier = hi && hi.available ? hi.unrealized_count + openTax : 0;
  // aeltere Berichte kennen top_level_relations nicht: dann grob die Haelfte der Object Properties (Inversenpaare)
  const nRel = m ? (m.top_level_relations !== undefined ? m.top_level_relations : Math.round((m.object_properties || 0) / 2)) : 0;
  const vocab = state.propertyVocab;
  // ein Vokabular aus Schritt 7 (basis plan) wird dort geprueft, nicht hier
  const pending = vocab && vocab.basis !== 'plan' && ['proposed', 'approved'].includes(vocab.status);
  const relM = { top_level_relations: nRel, classes: m ? m.classes : 0,
                 top_level_relations_per_class: m && m.top_level_relations !== undefined ? m.top_level_relations_per_class : undefined };
  const showProps = (m && tooManyTopLevel(relM)) || pending;
  // An Standards ausrichten: nur mit geladenen Vokabularen (Schritt 7); aeltere Berichte kennen die Zahl nicht
  const loaded = (state.suggestedStandards || []).filter(s => s.vocabulary).map(s => s.prefix);
  const showAlign = loaded.length && (nAlign === undefined || nAlign > 0);
  // je Werkzeug der Messwert der Evaluation, der es zeigt (PLAN.md Phase 4)
  const list = [];
  if (nDefs) list.push({ label: `Apply decided definitions (${nDefs})`, onclick: 'applyDefinitions()',
    title: "Replace differing descriptions with the team's decided definitions and add missing classes of a split - no model call",
    why: `${nDefs} class${nDefs !== 1 ? 'es differ' : ' differs'} from the decided definitions`, what: 'no model call' });
  if (nConcepts) list.push({ label: `Add missing central concepts (${nConcepts})`, onclick: "startGapRun('concepts')",
    why: `${nConcepts} central concept${nConcepts !== 1 ? 's' : ''} of the literature neither modelled nor decided`, what: 'adds each as a class, an individual or a property, or records why not' });
  if (nHier) list.push({ label: 'Build hierarchy from the literature', onclick: "startGapRun('hierarchy')",
    why: `${hi.unrealized_count ? `${hi.unrealized_count} broader term${hi.unrealized_count !== 1 ? 's' : ''} neither realized nor declined` : ''}${
      hi.unrealized_count && openTax ? '; ' : ''}${openTax ? `${openTax} taxonomies of the literature not yet applied or decided` : ''}`,
    what: 'arranges classes by the broader terms and taxonomies of the sources' });
  if (nUpper) list.push({ label: `Group root classes (${nUpper})`, onclick: "startGapRun('upper')",
    title: 'Process, Agent, InformationObject (with Specification) and Quality - created if missing, disjoint',
    why: `${nUpper} root class${nUpper !== 1 ? 'es' : ''} outside an upper layer`, what: 'places root classes below an upper layer' });
  if (showProps) list.push({ label: pending ? 'Review core relations' : `Consolidate properties`, onclick: 'openPropertyConsolidation()',
    title: 'A small vocabulary of general relations, reviewed by you; every property is then merged into one, placed below one, or kept',
    why: pending ? 'core relations proposed for this ontology wait for your review'
      : `${nRel} top-level relations for ${relM.classes} classes, more than about ${TOP_LEVEL_PER_CLASS_MAX} per class`,
    what: 'merges or places properties below a reviewed set of core relations' });
  if (showAlign) list.push({ label: `Align with ${loaded.join(', ')}`, onclick: "startGapRun('align')",
    title: "Link own classes and properties to terms of the loaded vocabularies (SubClassOf, EquivalentClasses, subPropertyOf), checked by the reasoner together with the vocabularies' axioms",
    why: nAlign ? `${nAlign} own term${nAlign !== 1 ? 's have' : ' has'} candidates in ${loaded.join(', ')}` : `vocabularies loaded: ${loaded.join(', ')}`,
    what: "links checked by the reasoner together with the vocabulary's axioms" });
  if (nRestr) list.push({ label: 'Add class restrictions', onclick: "startGapRun('restrictions')",
    title: 'Every A has some p to a B, only, or a number - decided per class pair, checked against domain, range and the reasoner',
    why: `${nRestr} class pair${nRestr !== 1 ? 's' : ''} could get a restriction`, what: "evidence from merged properties, the literature's relations and passing questions" });
  return { list, count: list.length };
}

// Reparaturwerkzeuge (PLAN.md Phase 4): ein Reiter mit der Zahl der Werkzeuge, die die Evaluation verlangt;
// welche es sind, steht auch unter "Needs attention"
function renderRepairTools(tools) {
  const box = document.getElementById('repairTools');
  if (!box) return;
  const n = tools ? tools.count : 0;
  const badge = document.getElementById('repairCount');
  badge.style.display = n ? '' : 'none';
  badge.textContent = n;
  const why = [];
  if (state.ontologyImported) why.push('the ontology was loaded from a file');
  if (n) why.push(`the evaluation found ${n} gap${n !== 1 ? 's' : ''} they address`);
  document.getElementById('repairReason').textContent = (why.length ? 'Shown because ' + why.join('; ') + '. '
    : tools ? 'The evaluation found no gap these tools address. ' : 'Evaluate the ontology to see which apply. ')
    + 'They change this ontology with edit operations in small packages - nothing is regenerated; what the model leaves out is recorded with its reason and not proposed again.';
  document.getElementById('repairBody').innerHTML = n ? tools.list.map(t => `<div class="repair-tool">
      <button class="btn btn-secondary btn-sm" onclick="${t.onclick}" title="${escHtml(t.title || '')}">${escHtml(t.label)}</button>
      <span class="lit-meta">${escHtml(t.why)}</span></div>`).join('') : '';
  if (state.ontologyImported && !state.refineTab) state.refineTab = 'repair';
}

function openRepairTools() {
  showRefineTab('repair');
}

// Reparaturaktion: entschiedene Definitionen in eine bestehende Ontologie uebernehmen (DECISIONS 83), ohne Modell
async function applyDefinitions() {
  openRepairTools();
  if (!confirm("Apply the team's decided definitions to this ontology? Differing descriptions are replaced and missing classes of a split are added next to the class of the concept. No model call.")) return;
  const el = document.getElementById('gapRun');
  try {
    const before = JSON.parse(JSON.stringify(state.currentOntology));
    const res = await fetch(`${API}/api/definitions/apply`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: state.sessionId }),
    });
    const d = await res.json();
    if (!res.ok) throw new Error(d.detail || 'Request failed');
    state.currentOntology = d.ontology;
    state.currentTurtle = d.turtle;
    state.iteration = d.iteration;
    computeAndShowDiff(before, d.ontology);
    renderOntology(d.ontology, d.turtle, d.iteration);
    el.innerHTML = `<div class="alert alert-success" style="flex-direction:column; align-items:flex-start; gap:4px;">
      <div>✅ Decided definitions applied: ${d.summary.applied.length} change${d.summary.applied.length !== 1 ? 's' : ''}. Evaluate again to see the effect.</div>
      ${d.summary.rejected.length ? `<div style="color:var(--error);">Not applied: ${d.summary.rejected.map(escHtml).join('; ')}</div>` : ''}
      <details><summary style="cursor:pointer;">Changes</summary><ul class="lit-sources">${d.summary.applied.map(a => `<li>${escHtml(a)}</li>`).join('')}</ul></details>
    </div>`;
    renderEvaluation(state.evaluation);
    saveProject();
  } catch (e) {
    el.innerHTML = `<div class="alert alert-error"><span>❌</span><span>Error: ${escHtml(e.message)}</span></div>`;
  }
}

// ── Properties konsolidieren (DECISIONS 70) ──
// 1. Das Modell schlaegt ein Kernvokabular vor, 2. das Team prueft und gibt frei, 3. die Zuordnung laeuft als Aktion.
const CHARACTERISTICS = ['transitive', 'symmetric', 'asymmetric', 'functional', 'inverse_functional'];
let _vocabTimer = null;

async function openPropertyConsolidation() {
  openRepairTools();
  if (state.propertyVocab && state.propertyVocab.status !== 'off') {   // auch ein angewendetes wieder oeffnen: verbleibende Properties zuordnen
    state.vocabPanelOpen = true;
    renderPropertyVocab();
    document.getElementById('propVocab').scrollIntoView({ behavior: 'smooth' });
    return;
  }
  if (!state.llmConfig) { alert('Please configure the LLM first (Step 1).'); goTo(1); return; }
  if (!confirm('Propose a vocabulary of general core relations for this ontology (one model call)? You review it before anything changes.')) return;
  const el = document.getElementById('propVocab');
  el.innerHTML = `<div class="alert alert-info"><div class="spinner"></div><span>Proposing core relations…</span></div>`;
  try {
    const res = await fetch(`${API}/api/properties/propose`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: state.sessionId, llm_config: state.llmConfig }),
    });
    const d = await res.json();
    if (!res.ok) throw new Error(d.detail || 'Request failed');
    recordUsage(d.usage, false);
    state.propertyVocab = d.property_vocab;
    renderPropertyVocab();
    renderEvaluation(state.evaluation);
    el.scrollIntoView({ behavior: 'smooth' });
  } catch (e) {
    el.innerHTML = `<div class="alert alert-error"><span>❌</span><span>Error: ${escHtml(e.message)}</span></div>`;
  }
}

// Dieselbe Tabelle an zwei Orten: in Schritt 7 vor der Generierung (mode 'plan', DECISIONS 89) und in der
// Evaluation als Reparatur einer fertigen Ontologie (mode 'repair', DECISIONS 70).
function renderPropertyVocab() {
  renderCoreVocab();
  const el = document.getElementById('propVocab');
  const v = state.propertyVocab;
  if (!el) return;
  if (!v || v.status === 'off' || ((v.status === 'applied' || v.basis === 'plan') && !state.vocabPanelOpen)) {
    if (!el.querySelector('.alert-error')) el.innerHTML = ''; return;
  }
  el.innerHTML = `<div class="oops-banner info" style="margin-top:10px;">
    <div style="font-weight:700; margin-bottom:4px;">🔗 Core relations — ${v.status === 'applied' ? 'applied; properties not mapped yet (new, or reconsidered) can be mapped again'
      : v.status === 'approved' ? 'approved' : 'proposed, please review'}</div>
    ${vocabTableHtml(v, 'repair')}
    <div style="display:flex; gap:10px; flex-wrap:wrap; margin-top:6px;">
      <button class="btn btn-primary btn-sm" onclick="approvePropertyVocab()">${v.status === 'applied' ? '▶ Map the remaining properties' : '✓ Approve and consolidate'}</button>
      <button class="btn btn-secondary btn-sm" onclick="addVocabRow()">＋ Add relation</button>
      <button class="btn btn-secondary btn-sm" onclick="reproposePropertyVocab()">↻ Propose again</button>
      <button class="btn btn-secondary btn-sm" onclick="discardPropertyVocab()">✕ Discard</button>
    </div></div>`;
}

function renderCoreVocab() {
  const el = document.getElementById('coreVocab');
  if (!el) return;
  const v = state.propertyVocab;
  const propose = `<button class="btn btn-secondary btn-sm" onclick="proposeCoreRelations()">✨ Propose core relations</button>`;
  if (!v || v.status === 'off') {
    el.innerHTML = `<div id="coreVocabStatus"></div><div class="lit-meta" style="margin-bottom:8px;">${v
      ? 'Core relations are switched off for this project: every module defines its own properties.'
      : 'No core relations yet.'}</div>
      <div style="display:flex; gap:10px; flex-wrap:wrap;">${propose}${v ? '' : `<button class="btn btn-secondary btn-sm"
        onclick="switchOffCoreRelations()">Don't use core relations</button>`}</div>`;
    return;
  }
  const state_ = v.status === 'proposed' ? 'proposed — please review and approve; the generation uses only approved core relations'
    : v.status === 'approved' ? 'approved — the next generation uses them'
    : 'approved and applied to the current ontology — the next generation uses them';
  el.innerHTML = `<div id="coreVocabStatus"></div>
    <div style="display:flex; flex-wrap:wrap; align-items:center; gap:8px; margin-bottom:4px;">
      <span class="pill ${v.status === 'proposed' ? 'warn' : 'ok'}">${v.status === 'proposed' ? 'to review' : 'approved'}</span>
      <span style="font-weight:600;">${v.relations.length} core relations</span><span class="lit-meta">${state_}</span></div>
    ${v.basis !== 'plan' ? `<div class="lit-meta">Derived from the properties of an earlier version of the ontology (consolidation).</div>` : ''}
    ${vocabTableHtml(v, 'plan')}
    <div style="display:flex; gap:10px; flex-wrap:wrap; margin-top:6px;">
      ${v.status === 'proposed' ? `<button class="btn btn-primary btn-sm" onclick="approveCoreRelations()">✓ Approve</button>` : ''}
      <button class="btn btn-secondary btn-sm" onclick="addVocabRow()">＋ Add relation</button>
      <button class="btn btn-secondary btn-sm" onclick="reproposeCoreRelations()">↻ Propose again</button>
      <button class="btn btn-secondary btn-sm" onclick="switchOffCoreRelations()">✕ Don't use core relations</button>
    </div>
    <div id="coreUsage">${state._coreUsage && state._coreUsage.iteration === state.iteration ? state._coreUsage.html : ''}</div>`;
  if (v.status !== 'proposed' && state.currentOntology) loadCoreUsage();
}

// Rueckmeldung nach einer Generierung (DECISIONS 119): welche Kernrelationen nichts unter sich haben, und worauf die
// Relationen ohne Kernrelation zeigen - ohne Modellaufruf; einmal je Iteration geholt
async function loadCoreUsage() {
  if (!state.sessionId || (state._coreUsage && state._coreUsage.iteration === state.iteration)) return;
  const iteration = state.iteration;
  let html = '';
  try {
    const res = await fetch(`${API}/api/properties/usage?session_id=${encodeURIComponent(state.sessionId)}`);
    const d = await res.json();
    if (res.ok && d.available) {
      const n = (state.propertyVocab.relations || []).length;
      html = `<div class="oops-banner info" style="margin-top:10px;">
        <div style="font-weight:700; margin-bottom:4px;">📈 How the current ontology uses them</div>
        <div>${Object.keys(d.below).length} of ${n} core relations have relations of the modules below them;
          ${d.without_core} relations of the modules are below none.</div>
        ${d.unused.length ? `<div style="margin-top:4px;"><strong>Nothing below:</strong> ${escHtml(d.unused.join(', '))} — a narrow
          one may belong in a module; a general one may still be used directly.</div>` : ''}
        ${d.groups.length ? `<div style="margin-top:4px;"><strong>Relations below no core relation, by the upper class they point to:</strong></div>
          ${d.groups.map(g => `<div>→ ${escHtml(g.upper)}: ${g.relations.length} (${escHtml(g.relations.slice(0, 8).join(', '))}${
            g.relations.length > 8 ? ' …' : ''})</div>`).join('')}
          <div class="lit-meta">A general core relation with that class as range (such as "has quality" for Quality) could take
            them in: add it with ＋ Add relation, approve, and generate again.</div>` : ''}
      </div>`;
    }
  } catch (e) { /* nur eine Rueckmeldung */ }
  state._coreUsage = { iteration, html };
  const el = document.getElementById('coreUsage');
  if (el) el.innerHTML = html;
}

function vocabTableHtml(v, mode) {
  const n = v.relations.length;
  const plan = v.basis === 'plan';
  // vor der Generierung: Domain und Range nur aus den Key Notions und entschiedenen Klassen (vom Server)
  const classes = plan ? (v.classes || []) : ((state.currentOntology || {}).classes || []).map(c => c.name);
  const list = `vocabClasses-${mode}`;
  const field = (i, key, value, ph, withList) => `<input type="text" value="${escHtml(value || '')}" placeholder="${ph}"
    ${withList ? `list="${list}"` : ''} oninput="editVocab(${i}, '${key}', this.value)" />`;
  const [lo, hi] = coreRelationsRange(classes.length);
  return `<div class="lit-meta">${n} relations${!plan && (n < lo || n > hi) ? ` (the target for ${classes.length} classes is about ${lo}–${hi})` : ''}. Name, domain and range,
      inverse and characteristics can be changed; empty domain or range means "any"${plan
        ? ` — domain and range can be a key notion or a decided class (${escHtml(classes.join(', ') || 'none yet')}).
           Every module may then use a relation between any classes within them, and creates its own properties only
           below a core relation, where a question needs it.`
        : `. After approval every existing property is merged into one of them, placed below one, or kept with a reason,
           and your competency questions are tested again.`}${v.summary ? `<br>${escHtml(v.summary)}` : ''}</div>
    ${(v.dropped || []).length ? `<details class="lit-meta"><summary style="cursor:pointer;">${v.dropped.length} proposed relations were invalid and left out</summary>
      <ul class="lit-sources">${v.dropped.map(x => `<li>${escHtml(x)}</li>`).join('')}</ul></details>` : ''}
    <datalist id="${list}">${classes.map(c => `<option value="${escHtml(c)}">`).join('')}</datalist>
    ${mode === 'plan' ? vocabGroups(v, row) : `<div style="overflow-x:auto;"><table class="lit-table" style="margin:8px 0; min-width:900px;">
      <thead><tr><th>Relation</th><th>Domain</th><th>Range</th><th>Inverse</th><th>Characteristics</th><th>Description</th><th></th></tr></thead>
      <tbody>${v.relations.map((r, i) => row(r, i)).join('')}</tbody></table></div>`}
    <div class="lit-meta vocab-error" style="color:var(--error);"></div>`;
  function row(r, i) { return `<tr>
        <td>${field(i, 'name', r.name, 'relationName')}${(r.covers || []).length ? `<div class="lit-meta" title="${escHtml(r.covers.join(', '))}">covers e.g. ${escHtml(r.covers.slice(0, 3).join(', '))}${r.covers.length > 3 ? ' …' : ''}</div>` : ''}</td>
        <td>${field(i, 'domain', r.domain, 'any', true)}</td>
        <td>${field(i, 'range', r.range, 'any', true)}</td>
        <td>${field(i, 'inverse', r.inverse ? r.inverse.name : '', 'none')}</td>
        <td style="white-space:nowrap; min-width:140px;">${CHARACTERISTICS.map(c => `<label class="lit-meta"
          style="display:flex; align-items:center; gap:6px; margin:0; text-transform:none; letter-spacing:0;">
          <input type="checkbox" style="width:auto; margin:0; padding:0;" ${(r.characteristics || []).includes(c) ? 'checked' : ''}
            onchange="toggleVocabChar(${i}, '${c}', this.checked)" /> ${c.replace('_', ' ')}</label>`).join('')}</td>
        <td style="min-width:220px;"><textarea rows="3" style="min-height:0;" oninput="editVocab(${i}, 'description', this.value)">${escHtml(r.description || '')}</textarea></td>
        <td><button class="momo-del" onclick="removeVocabRow(${i})" title="Remove" aria-label="Remove ${escHtml(r.name || 'relation')}">✕</button></td></tr>`; }
}

// Kernrelationen nach ihrer Domain gruppiert (DECISIONS 126): "zwischen beliebigen Klassen", dann die obere Schicht, dann
// die uebrigen. Offen, solange sie zu pruefen sind; nach der Freigabe zu, mit den Namen als Vorschau.
const UPPER_ORDER = ['Process', 'Agent', 'InformationObject', 'Specification', 'Quality', 'PhysicalObject'];
function vocabGroups(v, row) {
  const groups = new Map();
  v.relations.forEach((r, i) => {
    const key = (r.domain || '').trim();
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(i);
  });
  const rank = k => k === '' ? -1 : UPPER_ORDER.includes(k) ? UPPER_ORDER.indexOf(k) : 100;
  const keys = [...groups.keys()].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
  const open = v.status === 'proposed';
  return keys.map(k => {
    const idx = groups.get(k);
    const title = k ? `From ${escHtml(k)}` : 'Between any classes';
    return `<details class="rel-group"${open ? ' open' : ''}>
      <summary><span class="rel-title">${title}</span><span class="pill neutral">${idx.length}</span>
        <span class="rel-preview">${escHtml(idx.map(i => v.relations[i].name).join(', '))}</span></summary>
      <div style="overflow-x:auto;"><table class="lit-table" style="min-width:900px;">
        <thead><tr><th>Relation</th><th>Domain</th><th>Range</th><th>Inverse</th><th>Characteristics</th><th>Description</th><th></th></tr></thead>
        <tbody>${idx.map(i => row(v.relations[i], i)).join('')}</tbody></table></div></details>`;
  }).join('');
}

function showDesignTab(name) {
  state.designTab = name;
  document.querySelectorAll('#panel5 .subtab').forEach(t => {
    const on = t.id === 'dtab-' + name;
    t.classList.toggle('active', on);
    t.setAttribute('aria-selected', on ? 'true' : 'false');
  });
  document.querySelectorAll('#panel5 .subtab-panel').forEach(p => p.classList.toggle('active', p.id === 'design-' + name));
}

function editVocab(i, key, value) {
  const r = state.propertyVocab.relations[i];
  if (key === 'inverse') r.inverse = value.trim() ? { name: value.trim(), description: (r.inverse || {}).description || '' } : null;
  else r[key] = value;
  queueVocabSave();
}
function toggleVocabChar(i, c, on) {
  const r = state.propertyVocab.relations[i];
  r.characteristics = on ? [...new Set([...(r.characteristics || []), c])] : (r.characteristics || []).filter(x => x !== c);
  queueVocabSave();
}
function addVocabRow() {
  state.propertyVocab.relations.push({ name: '', domain: '', range: '', inverse: null, characteristics: [], description: '', covers: [] });
  renderPropertyVocab();
}
function removeVocabRow(i) {
  state.propertyVocab.relations.splice(i, 1);
  renderPropertyVocab();
  queueVocabSave();
}
function queueVocabSave() {
  clearTimeout(_vocabTimer);
  _vocabTimer = setTimeout(() => saveVocab(), 800);
}
async function saveVocab(extra) {
  clearTimeout(_vocabTimer);
  const err = text => document.querySelectorAll('.vocab-error').forEach(e => { e.textContent = text; });
  const rows = state.propertyVocab.relations;
  if (rows.some(r => !String(r.name || '').trim())) { err('Every relation needs a name.'); return false; }
  try {
    const res = await fetch(`${API}/api/properties/vocab`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: state.sessionId, relations: rows, ...(extra || {}) }),
    });
    const d = await res.json();
    if (!res.ok) { err(d.detail || 'Could not save'); return false; }
    err('');
    // die Zeilen behalten (Cursor), nur Status und bereinigte Werte uebernehmen, wenn nicht getippt wird
    const typing = ['propVocab', 'coreVocab'].some(id => (document.getElementById(id) || document.body).contains(document.activeElement)
                                                        && document.activeElement !== document.body);
    state.propertyVocab = typing ? { ...d.property_vocab, relations: rows } : d.property_vocab;
    if (!typing) renderCoreVocab();       // z.B. "approved" -> "proposed" nach einer Aenderung
    return true;
  } catch (e) { err('Could not save: ' + e.message); return false; }
}
async function approvePropertyVocab() {
  if (!await saveVocab({ approve: true })) return;
  renderPropertyVocab();
  await startGapRun('properties');
}
async function reproposePropertyVocab() {
  if (!confirm('Replace this vocabulary with a new proposal (one model call)? Your changes to it are lost.')) return;
  state.propertyVocab = null;
  await openPropertyConsolidation();
}
async function discardPropertyVocab() {
  if (!confirm('Discard the proposed core relations?')) return;
  await fetch(`${API}/api/properties/vocab`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: state.sessionId, discard: true }),
  });
  state.propertyVocab = null;
  renderPropertyVocab();
  renderEvaluation(state.evaluation);
}

// ── Export (MOMo Step 10 — the OWL file is the final translation) ──────────
function downloadTurtle() {
  const name = (state.currentOntology?.ontology_name || 'ontology').replace(/\s+/g, '_');
  const blob = new Blob([state.currentTurtle], { type: 'text/turtle' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `${name}.ttl`;
  a.click();
}

// Dokumentation je Modul fuer die Expertenpruefung (DECISIONS 114) - der Server baut sie ohne Modellaufruf
async function downloadDocumentation(format) {
  if (!state.sessionId) return;
  // ueber fetch: ein Fehler des Servers ersetzt sonst die Seite durch seine JSON-Antwort
  const r = await fetch(`${API}/api/session/${encodeURIComponent(state.sessionId)}/documentation?format=${format}`);
  if (!r.ok) { alert('Could not build the documentation: ' + ((await r.json().catch(() => ({}))).detail || r.status)); return; }
  const name = /filename="([^"]+)"/.exec(r.headers.get('content-disposition') || '');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(await r.blob());
  a.download = name ? name[1] : `ontology-documentation.${format === 'md' ? 'md' : 'html'}`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

function copyTurtle() {
  navigator.clipboard.writeText(state.currentTurtle).then(() => alert('Copied to clipboard!'));
}

function copyAndOpenEditor() {
  navigator.clipboard.writeText(state.currentTurtle).then(() => {
    window.open('https://felixlohmeier.github.io/turtle-web-editor/', '_blank');
    setTimeout(() => alert('Turtle copied to clipboard.\nIn the editor: Ctrl+A → Delete → Ctrl+V to paste.'), 300);
  }).catch(() => {
    window.open('https://felixlohmeier.github.io/turtle-web-editor/', '_blank');
  });
}
