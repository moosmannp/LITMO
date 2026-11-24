// Schritt 2: Use Case, Datenquellen, bestehende Ontologie laden
// (PLAN.md Phase 4: eine Datei je Schritt; klassische Skripte - alle Funktionen sind global,
// sofort ausgefuehrt wird nur main.js, das zuletzt laedt)

// ── Step 2: Upload ─────────────────────────────────────────────────────────────
function onDragOver(e) { e.preventDefault(); document.getElementById('dropZone').classList.add('drag-over'); }
function onDragLeave(e) { document.getElementById('dropZone').classList.remove('drag-over'); }
function onDrop(e) {
  e.preventDefault();
  document.getElementById('dropZone').classList.remove('drag-over');
  if (e.dataTransfer.files.length) handleFiles(e.dataTransfer.files);
}

// Zeigt pro Datei, wie sie aufbereitet wurde (Spaltenprofil, Volltext, RDF-Uebersicht)
function renderUploadList(info) {
  const how = {
    table: 'column profile of all rows and sheets',
    rdf: 'summary of classes and properties',
    error: '⚠ could not be read',
  };
  document.getElementById('fileList').innerHTML = (info || []).map(f => `
    <div style="display:flex; align-items:center; gap:8px; padding:3px 0;">
      <span style="color:var(--text); font-size:0.85rem;">📄 ${escHtml(f.name)}</span>
      <span style="color:${f.kind === 'error' ? 'var(--warning)' : 'var(--text-muted)'}; font-size:0.75rem; margin-left:auto;">
        ${f.kind === 'text' ? `full text (${(f.chars || 0).toLocaleString('en-US')} characters) — read completely for the project context`
                            : (how[f.kind] || '')}</span>
    </div>`).join('');
  document.getElementById('fileList').style.display = 'block';
}

async function handleFiles(fileList) {
  if (!fileList || fileList.length === 0) return;
  const files = Array.from(fileList);

  // Dateiliste anzeigen
  const listEl = document.getElementById('fileList');
  listEl.innerHTML = files.map(f => {
    const ext = f.name.split('.').pop().toUpperCase();
    const size = f.size > 1024*1024 ? (f.size/1024/1024).toFixed(1)+'MB' : Math.round(f.size/1024)+'KB';
    return `<div style="display:flex;align-items:center;gap:8px;padding:3px 0;">
      <span style="background:var(--accent);color:var(--on-accent);font-size:0.65rem;font-weight:700;padding:1px 5px;border-radius:4px;">${ext}</span>
      <span style="color:var(--text);font-size:0.85rem;">${f.name}</span>
      <span style="color:var(--text-muted);font-size:0.75rem;margin-left:auto;">${size}</span>
    </div>`;
  }).join('');
  listEl.style.display = 'block';

  const fd = new FormData();
  files.forEach(f => fd.append('files', f));

  try {
    const res = await fetch(`${API}/api/upload?session_id=${state.sessionId}`, { method: 'POST', body: fd });
    if (!res.ok) { const e = await res.json(); throw new Error(e.detail); }
    const data = await res.json();
    state.upload = { files: files.map(f => f.name), info: data.files };
    renderUploadList(data.files);
    markDone(2);
    saveProject();
  } catch(e) {
    alert('Upload error: ' + e.message);
  }
}

// ── Bestehende Ontologie laden ─────────────────────────────────────────────────
function onDragOver3(e) { e.preventDefault(); document.getElementById('loadOntoZone').classList.add('drag-over'); }
function onDragLeave3(e) { document.getElementById('loadOntoZone').classList.remove('drag-over'); }
function onDrop3(e) { e.preventDefault(); document.getElementById('loadOntoZone').classList.remove('drag-over'); if (e.dataTransfer.files.length) handleLoadOntology(e.dataTransfer.files[0]); }

async function handleLoadOntology(file) {
  if (!file) return;
  if (!state.llmConfig) { alert('Please configure the LLM first (Step 1).'); return; }
  document.getElementById('loadOntoName').textContent = file.name;
  document.getElementById('loadOntoName').style.display = 'block';
  document.getElementById('loadOntoStatus').innerHTML = `<div class="alert alert-info"><div class="spinner"></div><span>Loading and parsing ontology…</span></div>`;

  const fd = new FormData();
  fd.append('file', file);
  try {
    const res = await fetch(`${API}/api/load-ontology?session_id=${state.sessionId}`, { method: 'POST', body: fd });
    const text = await res.text();
    let data;
    try { data = JSON.parse(text); } catch(_) { throw new Error('Server response is not JSON: ' + text.slice(0,200)); }
    if (!res.ok) throw new Error(data.detail);

    state.currentOntology = data.ontology;
    state.currentTurtle = data.turtle;
    state.iteration = 0;

    // was die Datei enthielt, das Werkzeug aber nicht lesen kann - sonst fehlte es still (DECISIONS 138)
    const rep = data.import_report || {}, unread = Object.entries(rep.not_read || {});
    document.getElementById('loadOntoStatus').innerHTML = `<div class="alert alert-success">✅ Ontology loaded: ${data.ontology.classes?.length||0} classes, ${data.ontology.properties?.length||0} properties, ${data.ontology.individuals?.length||0} individuals.${
      rep.definitions_read_as_superclasses ? ` ${rep.definitions_read_as_superclasses} class definitions (intersections) were read as superclasses and restrictions - as necessary conditions only.` : ''}</div>${
      unread.length ? `<div class="alert alert-info" style="margin-top:8px;"><span>Not read, because the tool's model has no place for them: ${
        unread.map(([k, n]) => `${n} ${escHtml(k)}`).join(', ')}. They are missing from the evaluation and the export.
        <button class="btn btn-primary btn-sm" style="margin-left:8px;" onclick="goTo(9)">Continue to step 9</button></span></div>` : ''}`;

    // eine geladene Ontologie wird geprueft und repariert, nicht generiert (PLAN.md Phase 4)
    state.ontologyImported = true;
    state.evaluation = null;
    state.cqTests = null;                                   // gehoerten zur vorigen Ontologie
    document.getElementById('cqReport').style.display = 'none';
    renderOopsReport(null);
    renderValidationBadge(null);
    renderOntology(data.ontology, data.turtle, 0);
    renderEvaluation(null);
    [1,2,3,4,5,6].forEach(markDone);

    if (!unread.length) setTimeout(() => goTo(9), 800);     // mit Hinweis: erst lesen, dann weiter
  } catch(e) {
    document.getElementById('loadOntoStatus').innerHTML = `<div class="alert alert-error">❌ ${escHtml(e.message)}</div>`;
  }
}
