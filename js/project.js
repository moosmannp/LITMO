// Projekte: Start, Speichern, Wiederherstellen, Projektauswahl, Export und Import
// (PLAN.md Phase 4: eine Datei je Schritt; klassische Skripte - alle Funktionen sind global,
// sofort ausgefuehrt wird nur main.js, das zuletzt laedt)

// ── Init & Projekt-Persistenz ──────────────────────────────────────────────────
// Der Server speichert jede Session auf der Platte. Der Browser merkt sich nur, welches Projekt offen ist,
// und stellt es beim Laden wieder her — nach Neuladen der Seite ebenso wie nach einem Serverneustart.
const PROJECT_KEY = 'odt.sessionId';
function rememberProject(id) { try { localStorage.setItem(PROJECT_KEY, id); } catch (e) {} }
function rememberedProject() { try { return localStorage.getItem(PROJECT_KEY); } catch (e) { return null; } }

async function init() {
  const sid = rememberedProject();
  if (sid) {
    let data = null;
    try {
      const res = await fetch(`${API}/api/session/${encodeURIComponent(sid)}`);
      if (res.ok) data = await res.json();
    } catch (e) { /* Server nicht erreichbar oder Projekt unbekannt — neu anfangen */ }
    if (data) {
      // Ein Fehler beim Wiederherstellen darf kein neues Projekt anlegen: sonst scheint das gespeicherte verschwunden
      state.sessionId = sid;
      try { restoreProject(data.project, data.turtle); }
      catch (e) {
        console.error(e);
        showProjectNotice(`Part of the project could not be shown (${e.message}). It is still saved; reload the page or open it via 📂 Projects.`);
      }
      return;
    }
  }
  const res = await fetch(`${API}/api/session/create`, { method: 'POST' });
  const data = await res.json();
  state.sessionId = data.session_id;
  rememberProject(state.sessionId);
  renderCQs();
  renderNotions();
  renderPatterns();
}

// _restoreFailed: das Wiederherstellen brach ab (v0.2-Durchlauf: ein Skriptfehler in Schritt 8) - dann haelt die
// Seite einen halben Zustand und darf ihn nicht ueber den gespeicherten schreiben, bis sie neu geladen ist
let _saveTimer = null, _restoring = false, _restoreFailed = false;
function saveProject() {
  if (_restoring || _restoreFailed || !state.sessionId) return;
  clearTimeout(_saveTimer);
  _saveTimer = setTimeout(saveProjectNow, 600);
}

async function saveProjectNow() {
  clearTimeout(_saveTimer);
  if (!state.sessionId || _restoreFailed) return;
  const val = id => (document.getElementById(id) || {}).value || '';
  const ui = {
    step: state.currentStep || 1,
    // Bewusst ohne API-Key: der wird weder gespeichert noch exportiert.
    llm: { provider: val('provider'), model: val('provider') === 'custom' ? val('modelCustom') : val('model'),
           base_url: ['rwthgpt', 'custom'].includes(val('provider')) ? val('baseUrl') : '',
           display_name: val('customProviderName') },
    domainDesc: val('domainDesc'), dataSources: val('dataSources'), extraReqs: val('extraReqs'),
    suggestedStandards: state.suggestedStandards,
    selectedStandards: state.selectedStandards.map(s => s.name),
    currentTurtle: state.currentTurtle, iteration: state.iteration,
    oopsReport: state.oopsReport || null, cqTests: state.cqTests || null, evaluation: state.evaluation || null,
    usageRun: state.usageRun || null, usageSession: state.usageSession || null,
    upload: state.upload || null, ontologyImported: !!state.ontologyImported,
    done: [...document.querySelectorAll('.step-btn.done')].map(b => +b.id.replace('nav', '')),
  };
  try {
    await fetch(`${API}/api/session/ui`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: state.sessionId, ui }),
    });
  } catch (e) { /* nicht blockierend — beim naechsten Speichern erneut */ }
}

function restoreProject(p, turtle) {
  _restoring = true;
  try {
    const ui = p.ui || {};
    const momo = p.momo || {};
    const set = (id, v) => { const el = document.getElementById(id); if (el) el.value = v || ''; };
    set('domainDesc', ui.domainDesc ?? momo.use_case);
    set('dataSources', ui.dataSources ?? momo.data_sources);
    set('extraReqs', ui.extraReqs);
    state.momo.competencyQuestions = momo.competency_questions || [];
    state.momo.keyNotions = momo.key_notions || [];
    state.momo.patterns = momo.patterns || [];
    renderCQs(); renderNotions(); renderPatterns();

    // LLM-Auswahl (ohne Key). Ist ein Key vorbelegt (RWTHgpt), gilt die Konfiguration sofort.
    if (ui.llm && ui.llm.provider) {
      document.getElementById('provider').value = ui.llm.provider;
      updateModelOptions();
      if (ui.llm.base_url) set('baseUrl', ui.llm.base_url);
      if (ui.llm.provider === 'custom') {
        set('modelCustom', ui.llm.model); set('customProviderName', ui.llm.display_name);
      } else if (ui.llm.model) {
        const sel = document.getElementById('model');
        if (![...sel.options].some(o => o.value === ui.llm.model))
          sel.insertAdjacentHTML('beforeend', `<option value="${escHtml(ui.llm.model)}">${escHtml(ui.llm.model)}</option>`);
        sel.value = ui.llm.model;
      }
      const cfg = readLlmConfig();
      if (typeof cfg !== 'string') state.llmConfig = cfg;
    }

    if (ui.upload && ui.upload.files && ui.upload.files.length) {
      state.upload = ui.upload;
      renderUploadList(ui.upload.info || ui.upload.files.map(name => ({ name })));
    }

    state.customPrefixes = p.custom_prefixes || {};
    renderCustomPrefixTags();
    // der Server haelt die Standards samt geladener Vokabulare; aeltere Projekte nur im UI-Zustand
    const standards = (p.suggested_standards && p.suggested_standards.length) ? p.suggested_standards : (ui.suggestedStandards || []);
    if (standards.length) {
      state.suggestedStandards = standards;
      const chosen = new Set(ui.selectedStandards || []);
      state.selectedStandards = state.suggestedStandards.filter(s => chosen.has(s.name));
      renderStandards(state.suggestedStandards);
      document.getElementById('standardsContent').style.display = 'block';
      document.getElementById('reloadStandardsBtn').style.display = 'inline-block';
    }

    state.projectTitle = p.title || '';   // ohne eigenen Titel: der Name der Ontologie
    state.ontologyImported = !!ui.ontologyImported;
    if (p.ontology) {
      state.currentOntology = p.ontology;
      state.currentTurtle = turtle || ui.currentTurtle || '';    // der Server kennt den letzten Stand
      state.iteration = p.iterations ?? ui.iteration ?? 1;
      renderValidationBadge(ui.oopsReport && ui.oopsReport.validation);
      renderOopsReport(ui.oopsReport);
      renderOntology(p.ontology, state.currentTurtle, state.iteration);
      document.getElementById('generateBtnWrap').innerHTML =
        '<button class="btn btn-secondary" onclick="resetGenerate()">Generate again</button>';
      const g = p.generation_report;   // Bericht der letzten Generierung, im Projekt gespeichert
      if (g) document.getElementById('genStatus').innerHTML =
        renderModularReport(g.modular_report, { usage: ui.usageRun, title: 'Last generation, step by step',
          when: (g.generated_at ? new Date(g.generated_at).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) + ' · ' : '')
                + 'later changes are not included' }) + definitionsReport(g.definitions_report) + reuseReport(g.reuse_report);
    }
    state.context = p.context || null;
    renderContext();
    loadDefinitions();
    state.propertyVocab = p.property_vocab || null;
    renderPropertyVocab();
    state.corpus = p.corpus || null;
    renderLiterature();
    if (ui.cqTests) { state.cqTests = ui.cqTests; renderCQReport(ui.cqTests); }
    state.evaluation = ui.evaluation || null;
    renderEvaluation(state.evaluation);
    if (ui.usageRun) { state.usageRun = ui.usageRun; state.usageSession = ui.usageSession; renderUsage(); }
    (ui.done || []).forEach(n => { if (document.getElementById('nav' + n)) markDone(n); });
    goTo(ui.step || 1);
    // ohne Schluessel: das Modell in der Kopfzeile zeigt "key needed", Schritt 1 sagt warum - kein Banner auf jeder Seite
    state.keyNeededModel = ui.llm && ui.llm.provider && !state.llmConfig ? (ui.llm.model || ui.llm.provider) : null;
    const notice = document.getElementById('keyNotice');
    notice.style.display = state.keyNeededModel ? 'flex' : 'none';
    notice.textContent = state.keyNeededModel ? `This project uses ${state.keyNeededModel}. Enter the API key again – it is never stored.` : '';
    renderHeaderStatus();
    if (!state.keyNeededModel && (p.ontology || momo.use_case)) showProjectNotice('Project restored.');
  } catch (e) {
    _restoreFailed = true;
    console.error('Restoring the project failed:', e);
    showProjectNotice(`The project could not be shown completely (${e.message}). Nothing is saved from this page until ` +
                      'it is reloaded, so the stored project stays as it was.', true);
  } finally {
    _restoring = false;
  }
}

function showProjectNotice(text, sticky = false) {
  const el = document.getElementById('projectNotice');
  el.textContent = text;
  el.style.display = 'block';
  clearTimeout(showProjectNotice._t);
  if (!sticky) showProjectNotice._t = setTimeout(() => { el.style.display = 'none'; }, 8000);
}

async function newProject() {
  if (!confirm('Start a new, empty project? The current project stays saved and can be exported first.')) return;
  await saveProjectNow();
  const res = await fetch(`${API}/api/session/create`, { method: 'POST' });
  rememberProject((await res.json()).session_id);
  location.reload();
}

// Projektauswahl: alle gespeicherten Projekte, zuletzt geaenderte zuerst; Oeffnen laedt die Seite mit dem Projekt neu
async function openProjectPicker() {
  closeProjectPicker();
  const box = document.createElement('div');
  box.id = 'projectPicker';
  box.className = 'picker-backdrop';
  box.onclick = e => { if (e.target === box) closeProjectPicker(); };
  box.innerHTML = `<div class="picker"><div style="display:flex; align-items:center; margin-bottom:10px;">
      <strong style="flex:1;">Projects</strong><button class="momo-del" onclick="closeProjectPicker()" title="Close">✕</button></div>
    <div id="projectPickerList"><div class="alert alert-info"><div class="spinner"></div><span>Loading…</span></div></div></div>`;
  document.body.appendChild(box);
  document.addEventListener('keydown', pickerKey);
  await renderProjectPicker();
}
function pickerKey(e) { if (e.key === 'Escape') closeProjectPicker(); }
function closeProjectPicker() {
  const box = document.getElementById('projectPicker');
  if (box) box.remove();
  document.removeEventListener('keydown', pickerKey);
}
async function renderProjectPicker() {
  const el = document.getElementById('projectPickerList');
  try {
    const res = await fetch(`${API}/api/sessions?current=${encodeURIComponent(state.sessionId || '')}`);
    const d = await res.json();
    if (!res.ok) throw new Error(d.detail || 'Request failed');
    state.projectList = d.projects;
    el.innerHTML = d.projects.map((p, i) => {
      const meta = [p.iteration ? `iteration ${p.iteration}` : 'not generated yet',
                    p.classes ? `${p.classes} classes in ${p.modules} modules` : '',
                    p.papers ? `${p.papers} sources` : '',
                    p.updated ? `saved ${new Date(p.updated).toLocaleString()}` : 'not saved yet',
                    p.session_id.slice(0, 8)].filter(Boolean).join(' · ');
      return `<div class="picker-row ${p.current ? 'current' : ''}">
        <div style="flex:1; min-width:0;">
          <div class="picker-title">${escHtml(p.title)}${p.current ? ' <span class="lit-pill">open</span>' : ''}</div>
          <div class="picker-meta">${escHtml(meta)}</div>
          ${p.use_case && p.named ? `<div class="picker-meta" style="white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${escHtml(p.use_case)}</div>` : ''}
        </div>
        <button class="oops-toggle" onclick="renameProject(${i})" title="Give the project its own title">✎ Rename</button>
        ${p.current ? '' : `<button class="btn btn-primary btn-sm" onclick="switchProject(${i})">Open</button>`}
      </div>`;
    }).join('') || '<p class="ctx-hint">No saved projects yet.</p>';
  } catch (e) {
    el.innerHTML = `<div class="alert alert-error"><span>❌</span><span>Error: ${escHtml(e.message)}</span></div>`;
  }
}
async function switchProject(i) {
  await saveProjectNow();
  rememberProject(state.projectList[i].session_id);
  location.reload();
}
async function renameProject(i) {
  const p = state.projectList[i];
  const title = prompt('Title of this project (empty: use the ontology name):', p.named ? p.title : '');
  if (title === null) return;
  await fetch(`${API}/api/session/rename`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: p.session_id, title }),
  });
  if (p.session_id === state.sessionId) { state.projectTitle = title; renderHeaderStatus(); }
  await renderProjectPicker();
}

async function exportProject() {
  await saveProjectNow();
  const a = document.createElement('a');
  a.href = `${API}/api/session/${encodeURIComponent(state.sessionId)}/export`;
  a.download = '';
  document.body.appendChild(a); a.click(); a.remove();
}

async function importProject(file) {
  if (!file) return;
  const fd = new FormData();
  fd.append('file', file);
  try {
    const res = await fetch(`${API}/api/session/import`, { method: 'POST', body: fd });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Import failed');
    await saveProjectNow();
    rememberProject(data.session_id);
    location.reload();
  } catch (e) {
    alert('Import error: ' + e.message);
  } finally {
    document.getElementById('projectImportInput').value = '';
  }
}
