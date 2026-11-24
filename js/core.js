// Gemeinsam: Zustand, Navigation, MOMo-Hinweise, Token-Verbrauch, Hilfsfunktionen
// (PLAN.md Phase 4: eine Datei je Schritt; klassische Skripte - alle Funktionen sind global,
// sofort ausgefuehrt wird nur main.js, das zuletzt laedt)

// ── State ──────────────────────────────────────────────────────────────────────
const API = '';
let state = {
  sessionId: null,
  llmConfig: null,
  suggestedStandards: [],
  selectedStandards: [],
  customPrefixes: {},
  currentOntology: null,
  currentTurtle: null,
  iteration: 0,
  // MOMo conceptual state (Steps 1–4)
  momo: { competencyQuestions: [], keyNotions: [], patterns: [] },
};

// ── Navigation ─────────────────────────────────────────────────────────────────
// Helles oder dunkles Thema (DECISIONS 127): die Wahl bleibt in diesem Browser; der Graph zeichnet sich neu,
// weil er auf eine Leinwand malt und die CSS-Variablen dort nicht gelten
function currentTheme() { return document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light'; }

function toggleTheme() {
  const next = currentTheme() === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  try { localStorage.setItem('odt.theme', next); } catch (e) { /* ohne Speicher gilt die Wahl bis zum Neuladen */ }
  syncThemeToggle();
  if (state.currentOntology && typeof renderGraph === 'function' && typeof visNetwork !== 'undefined' && visNetwork) renderGraph(state.currentOntology);
}

function syncThemeToggle() {
  const btn = document.getElementById('themeToggle');
  if (btn) btn.setAttribute('aria-label', currentTheme() === 'dark' ? 'Switch to the light theme' : 'Switch to the dark theme');
}

// Kopfzeile: Projekt, Iteration und Modell auf einen Blick (DECISIONS 126)
function renderHeaderStatus() {
  const onto = state.currentOntology;
  document.getElementById('headProject').textContent =
    state.projectTitle || (onto && onto.ontology_name) || 'New project';
  const iter = document.getElementById('headIteration');
  iter.style.display = onto ? '' : 'none';
  iter.textContent = `Iteration ${state.iteration ?? 1}`;
  const model = document.getElementById('headModel');
  const cfg = state.llmConfig;
  // ein wiederhergestelltes Projekt ohne Schluessel: das Modell mit "key needed" statt eines Banners auf jeder Seite
  const needed = !cfg && state.keyNeededModel;
  model.style.display = cfg || needed ? '' : 'none';
  model.classList.toggle('warn', !!needed);
  model.textContent = cfg ? (cfg._displayName ? `${cfg._displayName} · ${cfg.model}` : cfg.model)
    : needed ? `${state.keyNeededModel} · key needed` : '';
  renderSidebarStatus();
}

// Seitenleiste: je Schritt eine Zahl oder eine Warnung (DECISIONS 126)
function renderSidebarStatus() {
  const meta = (nav, text, warn) => {
    const btn = document.getElementById('nav' + nav);
    if (!btn) return;
    let el = btn.querySelector('.step-meta');
    if (!el) { el = document.createElement('span'); el.className = 'step-meta'; btn.appendChild(el); }
    el.textContent = text || '';
    el.classList.toggle('warn', !!warn);
  };
  meta(1, !state.llmConfig && state.keyNeededModel ? 'key needed' : '', true);
  const docs = (state.corpus && state.corpus.docs) || [];
  meta(8, docs.length ? `${docs.length} source${docs.length !== 1 ? 's' : ''}` : '');
  const d = state.definitions && state.definitions.summary;
  const undecided = d ? d.conflicts - d.decided - (d.open || 0) : 0;
  meta(7, undecided > 0 ? `${undecided} undecided` : '', undecided > 0);
  const cqs = (state.momo.competencyQuestions || []).filter(c => (c.question || '').trim()).length;
  meta(3, cqs ? String(cqs) : '');
  const notions = (state.momo.keyNotions || []).filter(n => (n.name || '').trim()).length;
  meta(4, notions ? String(notions) : '');
  const v = state.propertyVocab;
  meta(5, v && v.status === 'proposed' ? 'to review' : '', v && v.status === 'proposed');
  const ev = state.evaluation;
  meta(9, state.currentOntology && ev && ev.iteration !== state.iteration ? 'outdated' : '', true);
}

function toggleKeyVisible() {
  const input = document.getElementById('apiKey');
  const show = input.type === 'password';
  input.type = show ? 'text' : 'password';
  const btn = document.getElementById('keyToggle');
  btn.textContent = show ? 'Hide' : 'Show';
  btn.setAttribute('aria-label', show ? 'Hide the key' : 'Show the key');
}

// Schritt 2: beschreiben oder mit einer vorhandenen Ontologie beginnen
function showStartMode(mode) {
  document.getElementById('startDescribe').style.display = mode === 'load' ? 'none' : '';
  document.getElementById('startLoad').style.display = mode === 'load' ? '' : 'none';
  document.getElementById('startDescribeBtn').classList.toggle('active', mode !== 'load');
  document.getElementById('startLoadBtn').classList.toggle('active', mode === 'load');
}

// Schritt 4 in Reitern; die Zahlen zeigen, was offen ist
function showContextTab(name) {
  state.contextTab = name;
  document.querySelectorAll('#panel7 .subtab').forEach(t => {
    const on = t.id === 'ctab-' + name;
    t.classList.toggle('active', on);
    t.setAttribute('aria-selected', on ? 'true' : 'false');
  });
  document.querySelectorAll('#panel7 .subtab-panel').forEach(p => p.classList.toggle('active', p.id === 'context-' + name));
}

function updateContextTabs() {
  const set = (k, n) => {
    const el = document.getElementById('ctabCount-' + k);
    if (!el) return;
    el.style.display = n ? '' : 'none';
    el.textContent = n || '';
  };
  const md = (document.getElementById('contextMarkdown') || {}).value || '';
  set('doc', (md.match(/\[confirm\]/gi) || []).length);
  const qs = ((state.context || {}).questions || []).length;
  set('questions', qs);
  const qCard = document.getElementById('contextQuestionsCard');
  document.getElementById('contextQuestionsEmpty').style.display = qCard && qCard.style.display !== 'none' ? 'none' : '';
  const d = state.definitions && state.definitions.summary;
  set('definitions', d ? Math.max(0, d.conflicts - d.decided - (d.open || 0)) : 0);
  const dCard = document.getElementById('definitionsCard');
  document.getElementById('definitionsEmpty').style.display = dCard && dCard.style.display !== 'none' ? 'none' : '';
  renderSidebarStatus();
}

function goTo(n) {
  if (!document.getElementById('panel' + n)) n = 1;   // a step that no longer exists (older project files)
  state.currentStep = n;
  saveProject();
  renderHeaderStatus();
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.step-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('panel' + n).classList.add('active');
  document.getElementById('nav' + n).classList.add('active');
  if (n === 8) renderLiterature();
  if (n === 7) loadDefinitions();
  if (n === 5) showPatternStep();
  if (n === 6) renderMomoReadiness();
  if (n === 9) {
    renderRefineView();
    if (state.currentOntology &&
        document.getElementById('turtleEditorWrap').style.display !== 'none') refreshTurtleEditor();
  }
}

// ── MOMo: guide, don't block ───────────────────────────────────────────────────
// MOMo puts the OWL file last on purpose, but the user may still generate at any time.
function renderMomoReadiness() {
  const el = document.getElementById('momoReadiness');
  if (!el) return;
  const missing = [];
  if (!document.getElementById('domainDesc').value.trim()) missing.push('a use case description (Step 2)');
  if (!(state.context && state.context.markdown && state.context.markdown.trim())) missing.push('a project context (Step 4)');
  if (!state.momo.competencyQuestions.length) missing.push('competency questions (Step 5)');
  if (!namedNotions().length) missing.push('key notions (Step 6)');
  const vocab = state.propertyVocab;
  const unapproved = vocab && vocab.basis === 'plan' && vocab.status === 'proposed';
  if (!missing.length && !unapproved) { el.innerHTML = ''; return; }
  el.innerHTML = (missing.length ? `<div class="alert alert-info" style="align-items:flex-start;">
      <span>💡</span>
      <span>MOMo builds the ontology conceptually first — you haven't defined ${missing.join(', ')}.
      You can generate anyway: the plan then chooses the modules itself, and without competency questions nothing
      checks what the ontology must answer.</span>
    </div>` : '') + (unapproved ? `<div class="alert alert-info" style="align-items:flex-start;">
      <span>🔗</span>
      <span>The core relations of Step 7 are proposed but not approved — this generation does not use them; every
      module defines its own properties.</span>
    </div>` : '');
}

async function saveMomo() {
  if (!state.sessionId) return;
  try {
    await fetch(`${API}/api/momo/save`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: state.sessionId,
        use_case: document.getElementById('domainDesc').value.trim(),
        data_sources: (document.getElementById('dataSources') || {}).value || '',
        competency_questions: state.momo.competencyQuestions,
        key_notions: state.momo.keyNotions,
        patterns: state.momo.patterns,
      }),
    });
  } catch (e) { /* nicht blockierend — der konzeptuelle Stand bleibt lokal erhalten */ }
  saveProject();
}

function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

async function momoCall(endpoint, statusEl, busyText, extra) {
  if (!state.llmConfig) { alert('Please configure the LLM first (Step 1).'); goTo(1); return null; }
  await saveMomo();
  const st = document.getElementById(statusEl);
  st.innerHTML = `<div class="alert alert-info"><div class="spinner"></div><span>${busyText}</span></div>`;
  try {
    const res = await fetch(`${API}/api/momo/${endpoint}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: state.sessionId, llm_config: state.llmConfig, ...(extra || {}) }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Request failed');
    st.innerHTML = '';
    return data;
  } catch (e) {
    st.innerHTML = `<div class="alert alert-error"><span>❌</span><span>Error: ${esc(e.message)}</span></div>`;
    return null;
  }
}

// ── Token-Verbrauch ────────────────────────────────────────────────────────────
// Ein "Lauf" ist eine Generierung bzw. Feedback-Runde samt der anschliessenden CQ-Tests.
function recordUsage(usage, newRun) {
  if (!usage) return;
  if (newRun || !state.usageRun) state.usageRun = [];
  state.usageRun.push(...usage.calls);
  state.usageSession = state.usageSession || { input: 0, output: 0, calls: 0, unknown: 0 };
  state.usageSession.input += usage.input_tokens;
  state.usageSession.output += usage.output_tokens;
  state.usageSession.calls += usage.calls.length;
  state.usageSession.unknown += usage.unknown_calls;
  renderUsage();
}

function renderUsage() {
  saveProject();
  const el = document.getElementById('usageBox');
  const calls = state.usageRun || [];
  if (!calls.length) { el.style.display = 'none'; return; }
  const fmt = n => n.toLocaleString('en-US');
  const known = calls.filter(c => c.input_tokens != null);
  const inp = known.reduce((a, c) => a + c.input_tokens, 0);
  const out = known.reduce((a, c) => a + (c.output_tokens || 0), 0);
  const unknown = calls.length - known.length;
  const ses = state.usageSession;
  const rows = calls.map(c => `<tr><td>${escHtml(c.step)}</td>
      <td style="text-align:right">${c.input_tokens != null ? fmt(c.input_tokens) : 'n/a'}</td>
      <td style="text-align:right">${c.output_tokens != null ? fmt(c.output_tokens) : 'n/a'}</td></tr>`).join('');
  el.innerHTML = `
    <div class="oops-banner info">
      <div style="font-weight:700; margin-bottom:4px;">🔢 Token Usage</div>
      <div>This run: <strong>${fmt(inp)}</strong> input · <strong>${fmt(out)}</strong> output tokens
        in ${calls.length} LLM call${calls.length !== 1 ? 's' : ''}.
        Session total: ${fmt(ses.input)} input · ${fmt(ses.output)} output tokens in ${ses.calls} calls.</div>
      ${unknown || ses.unknown ? `<div class="pf-desc" style="margin-top:4px;">⚠️ The provider reported no usage for
        ${unknown || ses.unknown} call(s); the totals are incomplete.</div>` : ''}
      <div class="oops-pitfall-list" id="usageList" style="display:none">
        <table><thead><tr><th>Step</th><th style="text-align:right">Input</th><th style="text-align:right">Output</th></tr></thead>
        <tbody>${rows}</tbody></table>
      </div>
      <button class="oops-toggle" id="usageToggleBtn" onclick="toggleUsageList()">▶ Show details</button>
    </div>`;
  el.style.display = 'block';
}

function toggleUsageList() {
  const list = document.getElementById('usageList');
  const btn  = document.getElementById('usageToggleBtn');
  const hidden = list.style.display === 'none';
  list.style.display = hidden ? 'flex' : 'none';
  btn.textContent = hidden ? '▼ Hide details' : '▶ Show details';
}

// ── Helpers ────────────────────────────────────────────────────────────────────
// Label in der ersten Sprache (aeltere Ontologien haben nur label_de)
function ontoLabel(x) {
  if (!x) return '';
  if (x.labels && typeof x.labels === 'object') {
    const first = Object.values(x.labels).find(v => v);
    if (first) return String(first);
  }
  return x.label_de || '';
}

function markDone(n) {
  document.getElementById('nav' + n).classList.add('done');
}

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;').replace(/'/g,'&#39;');   // auch in Attributen (Code-Review 2026-10-29)
}
