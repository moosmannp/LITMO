// Schritt 8: Generieren, Bericht, Ontologie-Ansicht, Graph
// (PLAN.md Phase 4: eine Datei je Schritt; klassische Skripte - alle Funktionen sind global,
// sofort ausgefuehrt wird nur main.js, das zuletzt laedt)

// ── Step 5: Generate ───────────────────────────────────────────────────────────
// Bericht der Generierung Modul fuer Modul (nur mit Begriffsinventar aus Schritt 3)
// Farben des Graphen je Thema (vis-network zeichnet auf eine Leinwand, CSS-Variablen gelten dort nicht)
const GRAPH_THEMES = {
  light: { accent: '#3346B8', accentDark: '#24318A', accentSoft: '#EEF0FB', highlightSoft: '#DDE2F8', text: '#1B1C1F',
           muted: '#85878D', success: '#1E7046', successHi: '#2A8C5A', warning: '#8A5300', onAccent: '#FFFFFF', bg: '#FAFAF8' },
  dark: { accent: '#8C9BFF', accentDark: '#B3BDFF', accentSoft: '#262B47', highlightSoft: '#333B66', text: '#E7E8EA',
          muted: '#7D818A', success: '#5BC489', successHi: '#7CD6A3', warning: '#E8B04B', onAccent: '#0E1120', bg: '#23262C' },
};
const graphColors = () => GRAPH_THEMES[currentTheme()];

// Bericht der Generierung als Ablauf (DECISIONS 126): je Station Ergebnis, Aufrufe und Tokens, Hinweise an der Station,
// zu der sie gehoeren. usage: die Aufrufe des Laufs (Schritt, Tokens), soweit bekannt.
const STAGE_ICON = {
  done: '<svg width="20" height="20" viewBox="0 0 18 18" role="img" aria-label="Done"><circle cx="9" cy="9" r="8" fill="var(--success)"/><path d="M5.5 9.2l2.3 2.3 4.7-4.9" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  warn: '<svg width="20" height="20" viewBox="0 0 20 20" role="img" aria-label="Warning"><circle cx="10" cy="10" r="8.5" fill="var(--warning)"/><path d="M10 5.5v5.2M10 13.6v.1" stroke="#fff" stroke-width="1.8" stroke-linecap="round"/></svg>',
  bad: '<svg width="20" height="20" viewBox="0 0 20 20" role="img" aria-label="Error"><path d="M10 2l8.5 15h-17z" fill="var(--error)"/><path d="M10 8v4M10 14.4v.1" stroke="#fff" stroke-width="1.8" stroke-linecap="round"/></svg>',
  skip: '<svg width="20" height="20" viewBox="0 0 20 20" role="img" aria-label="Not run"><circle cx="10" cy="10" r="8" fill="none" stroke="var(--faint)" stroke-width="1.5"/></svg>',
};

function renderModularReport(r, opts = {}) {
  if (!r) return '';
  const names = (xs, n = 12) => escHtml(xs.slice(0, n).join(', ')) + (xs.length > n ? ' …' : '');
  const calls = opts.usage || [];
  const meta = match => {
    const cs = calls.filter(c => match(c.step || ''));
    if (!cs.length) return '';
    const k = Math.round(cs.reduce((a, c) => a + (c.input_tokens || 0), 0) / 1000);
    return `${cs.length} call${cs.length !== 1 ? 's' : ''} · ${k}k`;
  };
  const stages = [];
  const stage = (status, title, m, lines) => stages.push({ status, title, meta: m, lines: lines.filter(Boolean) });

  // 1. Plan
  const h = r.hierarchy || {};
  stage('done', 'Plan', meta(s => s === 'Module plan' || s.startsWith('Module plan (')), [
    `${r.planned_classes} classes in ${r.modules} modules${r.modules_proposed ? ' – the modules were proposed by the plan (no key notions given)' : ''}`,
    h.planned ? `${h.planned} superclass${h.planned !== 1 ? 'es' : ''} planned${h.set_from_plan && h.set_from_plan.length ? `; ${h.set_from_plan.length} set from the plan where the module left ${h.set_from_plan.length !== 1 ? 'them' : 'it'} out` : ''}${h.differ && h.differ.length ? `; placed differently by the module: ${names(h.differ, 6)}` : ''}`
      : (r.planned_classes > 3 ? 'The plan gave no class a superclass – the hierarchy is flat.' : ''),
    h.declined ? `${h.declined} broader/narrower relation${h.declined !== 1 ? 's' : ''} of the literature declined as not "a kind of" (recorded with the reasons)` : '',
  ]);
  // 2. Jeder zentrale Begriff (DECISIONS 104, 110)
  const ce = r.central;
  const cm = r.central_after_modules;   // nach den Modulen noch fehlende (DECISIONS 136)
  if (ce) stage(ce.unassigned_count || (ce.errors || []).length ? 'warn' : 'done', 'Every central concept placed',
      meta(s => s.startsWith('Plan completion') || s.startsWith('Missing central concepts')), [
    `${ce.central} central concepts: ${ce.by_plan} by the plan${ce.completion_assigned ? `, ${ce.completion_assigned} by the completion` : ''}, ${ce.excluded.length} excluded with a reason${ce.earlier_decisions ? ` (${ce.earlier_decisions} from earlier decisions)` : ''}`,
    ce.reviewed ? `${ce.reviewed} exclusion${ce.reviewed !== 1 ? 's' : ''} of the plan reviewed, ${(ce.review_kept || []).length} kept` : '',
    (ce.accounted_as || []).length ? `${ce.accounted_as.length} "exclusion${ce.accounted_as.length !== 1 ? 's' : ''}" already named a planned class and ${ce.accounted_as.length !== 1 ? 'were' : 'was'} assigned to it: ${names(ce.accounted_as, 10)}` : '',
    ce.unassigned_count ? `<strong>${ce.unassigned_count} still without a place</strong>: ${names(ce.unassigned, 10)}` : '',
    cm && cm.missing.length ? `${cm.missing.length} still missing after the modules: ${cm.added.length} added, ${cm.declined} declined with a reason${
      (cm.errors || []).length ? ` – the step failed (${escHtml(cm.errors[0])}); "Add missing central concepts" can do it` : ''}` : '',
    (ce.errors || []).length ? `The completion call failed (${escHtml(ce.errors[0])}) – "Add missing central concepts" can do it.` : '',
  ]);
  // 3. Anbindung an Vokabulare (DECISIONS 98, 101)
  const ru = r.reuse;
  if (ru && (ru.candidates || ru.links.length || ru.terms.length || ru.error)) stage(ru.error ? 'warn' : 'done', 'Vocabulary links',
    meta(s => s === 'Vocabulary links'), [
    `${ru.candidates || 0} planned class${ru.candidates !== 1 ? 'es' : ''} with candidates · ${ru.links.length} linked${ru.links.length ? ` (${names(ru.links, 8)}; "=" same meaning, "->" a kind of)` : ''}`,
    ru.terms.length ? `Vocabulary terms used instead of own classes: ${names(ru.terms, 8)}` : '',
    ru.error ? `The links could not be decided (${escHtml(ru.error)}); "Align" in step 9 can add them.` : '',
    ru.dropped.length ? `Proposed terms left out: ${names(ru.dropped, 6)}` : '',
  ]);
  // 4. Module
  const failed = r.module_errors.length;
  const byModule = {};
  ((state.currentOntology || {}).classes || []).forEach(c => { if (c.module) byModule[c.module] = (byModule[c.module] || 0) + 1; });
  const failedNames = new Set(r.module_errors.map(e => e.module));
  const chips = Object.keys(byModule).filter(n => !['UpperLayer', 'CoreRelations'].includes(n));
  stage(failed ? 'bad' : (r.placeholder_classes.length ? 'warn' : 'done'), `Modules · ${r.modules - failed} of ${r.modules}`,
    meta(s => s.startsWith('Module:')), [
    chips.length ? `<div class="module-chips">${chips.map(n => `<div class="module-chip${failedNames.has(n) ? ' failed' : ''}"><div>${escHtml(n)}</div>
      <div class="lit-meta">${byModule[n]} class${byModule[n] !== 1 ? 'es' : ''}</div></div>`).join('')}</div>` : '',
    `Together: ${r.classes} classes and ${r.properties} properties`,
    ...r.module_errors.map(e => `Module ${escHtml(e.module)} failed (${escHtml(e.error)}); its planned classes come from the plan only.`),
    r.fallback_classes ? `${r.fallback_classes} planned class${r.fallback_classes !== 1 ? 'es' : ''} missing from their module were added from the plan${r.inventory === false ? '' : ' with the definition from the sources'}` : '',
    r.placeholder_classes.length ? `${r.placeholder_classes.length} class${r.placeholder_classes.length !== 1 ? 'es' : ''} referenced but defined by no module, declared as placeholders: ${names(r.placeholder_classes)}` : '',
    r.redundant_axioms ? `${r.redundant_axioms} SubClassOf axiom${r.redundant_axioms !== 1 ? 's' : ''} that only repeated the hierarchy left out` : '',
    (r.invalid_axioms || []).length ? `Axioms left out because they name no class: ${names(r.invalid_axioms, 6)}` : '',
    (r.inverse_conflicts || []).length ? `Second inverse declarations removed (a property can have only one inverse): ${names(r.inverse_conflicts, 6)}` : '',
  ]);
  // 5. Nach den Modulen (DECISIONS 105, 111, 112)
  const ra = ru && ru.after_modules, ha = h.after_modules, cr = r.core_relations, ca = cr && cr.after_modules;
  const after = [
    ra && ra.candidates ? `<strong>Vocabulary links:</strong> ${ra.candidates} candidates · ${ra.links.length} linked${ra.links.length ? ` (${names(ra.links, 8)})` : ''} · ${ra.declined.length} without a fitting candidate${ra.rejected.length ? ` · refused: ${names(ra.rejected, 4)}` : ''}` : '',
    ha && ha.relations ? `<strong>Hierarchy from the literature:</strong> ${ha.relations} offered · ${ha.realized.length} added${ha.realized.length ? ` (${names(ha.realized, 6)})` : ''} · ${ha.declined} declined with a reason${ha.rejected.length ? ` · refused: ${names(ha.rejected, 4)}` : ''}` : '',
    cr ? `<strong>Core relations:</strong> ${cr.relations} used · ${cr.below_core.length} module propert${cr.below_core.length !== 1 ? 'ies' : 'y'} below them${ca && ca.relations ? ` · ${ca.relations} offered again after the modules, ${ca.placed.length} placed, ${ca.declined} kept as their own kind` : ''}${cr.without_core.length ? ` · ${cr.without_core.length} without one` : ''}` : '',
    cr && cr.violations.length ? `Outside the domain or range of their core relation: ${names(cr.violations, 8)}` : '',
    cr && cr.skipped.length ? `Left out as own versions of a core relation: ${names(cr.skipped)}` : '',
    cr && cr.widened.length ? `Domain or range set to "any" because the plan has no such class: ${names(cr.widened)}` : '',
  ];
  const afterErrors = [ra && ra.errors.length && `vocabulary links (${escHtml(ra.errors[0])}) – "Align" can add them`,
                       ha && ha.errors.length && `hierarchy (${escHtml(ha.errors[0])}) – "Build hierarchy" can do it`,
                       ca && ca.errors.length && `core relations (${escHtml(ca.errors[0])}) – "Consolidate properties" can do it`].filter(Boolean);
  if (after.some(Boolean) || afterErrors.length) stage(afterErrors.length ? 'warn' : 'done', 'After the modules',
    meta(s => s.includes('(after the modules)')), [...after, ...afterErrors.map(e => `A call failed: ${e}`)]);
  // 6. Klassenrestriktionen und Reasoner (DECISIONS 125)
  const rs = r.restrictions;
  if (rs && rs.written) {
    stage(rs.rejected.length ? 'warn' : 'done', 'Class restrictions', 'no call', [
      `${rs.written} written by the modules · ${rs.added} kept${rs.rejected.length ? ` · ${rs.rejected.length} left out` : ''}`,
      rs.rejected.length ? `<span class="lit-meta">${escHtml(rs.rejected.slice(0, 4).join('; '))}${rs.rejected.length > 4 ? ' …' : ''}</span>` : '',
    ]);
    const re = rs.reasoner;
    if (re) stage(!re.checked ? (re.error ? 'bad' : 'skip') : (re.removed.length || (re.still_unsatisfiable || []).length) ? 'warn' : 'done',
      'Reasoner check', 'no call', [
      !re.checked ? (re.error ? `<div class="stage-error">HermiT could not check the ontology: ${escHtml(re.error.slice(0, 260))}</div>` : 'Not checked: Java is missing or the check failed.')
        : re.removed.length ? `${re.removed.length} restriction${re.removed.length !== 1 ? 's' : ''} removed because they made classes unsatisfiable: ${names(re.removed, 6)}` : 'No class became unsatisfiable.',
      re.checked && (re.still_unsatisfiable || []).length ? `Still unsatisfiable: ${names(re.still_unsatisfiable, 8)}` : '',
    ]);
  }
  const u = r.upper_layer;        // obere Schicht (DECISIONS 97)
  const side = u ? `<div class="panel-card" style="padding:14px 18px;">
      <div style="font-weight:600; margin-bottom:8px;">Upper layer</div>
      <div style="display:flex; flex-wrap:wrap; gap:6px;">${(u.used.length ? u.used : ['none used']).map(n => `<span class="lit-pill" style="font-size:13px; color:var(--text);">${escHtml(n)}</span>`).join('')}</div>
      <div class="lit-meta" style="margin-top:8px;">${u.removed.length ? `Left out as empty: ${names(u.removed)}. ` : ''}${u.outside.length ? `Top classes outside it: ${names(u.outside)}.` : 'Every top class is below it.'}</div></div>` : '';
  return `<div class="gen-report">
    <div class="panel-card pipeline">
      <div class="panel-card-head"><h3>${escHtml(opts.title || 'Last generation, step by step')}</h3>${opts.when ? `<span class="lit-meta">${escHtml(opts.when)}</span>` : ''}</div>
      ${stages.map((st, i) => `<div class="stage">
        <div class="stage-rail">${STAGE_ICON[st.status]}${i < stages.length - 1 ? '<span class="stage-line"></span>' : ''}</div>
        <div class="stage-body">
          <div class="stage-head"><span class="stage-title">${st.title}</span>${st.meta ? `<span class="lit-meta">${st.meta}</span>` : ''}</div>
          ${st.lines.map(l => `<div class="stage-line-text">${l}</div>`).join('')}
        </div></div>`).join('')}
    </div>
    ${side}
  </div>`;
}

// Entschiedene Definitionen nach der Generierung (DECISIONS 83): der Server setzt sie woertlich ein
function definitionsReport(r) {
  if (!r) return '';
  const notes = [];
  if (r.deviated.length) notes.push(`the model wrote a different description for ${r.deviated.length}, replaced by the decided one: ${escHtml(r.deviated.slice(0, 12).join(', '))}${r.deviated.length > 12 ? ' …' : ''}`);
  if (r.missing.length) notes.push(`missing from the ontology: ${escHtml(r.missing.join(', '))} — use "Apply decided definitions" in the evaluation`);
  return `<div class="alert ${r.missing.length ? 'alert-error' : 'alert-info'}" style="align-items:flex-start;"><span>📌</span><span>
    Decided definitions: ${r.classes - r.missing.length} of ${r.classes} classes carry the team's definition.${notes.length ? '<br>' + notes.join('<br>') : ''}</span></div>`;
}

async function generateOntology() {
  if (!state.llmConfig) { alert('Please configure the LLM first (Step 1).'); goTo(1); return; }

  const domain = document.getElementById('domainDesc').value.trim();
  const extra = document.getElementById('extraReqs').value.trim();
  const combined = domain + (extra ? '\n\nAdditional requirements:\n' + extra : '');

  if (!combined) { alert('Please enter a domain description (Step 2).'); return; }
  await saveMomo();                      // Key Notions und Fragen werden nur bei manchen Aktionen gespeichert

  document.getElementById('generateBtn').disabled = true;
  document.getElementById('generateBtnWrap').style.display = 'none';
  document.getElementById('oopsReport').style.display = 'none';
  document.getElementById('cqReport').style.display = 'none';
  const inv = state.corpus && state.corpus.inventory;
  const withInventory = inv && inv.concepts && inv.concepts.length;
  const nNotions = namedNotions().length;
  document.getElementById('genStatus').innerHTML = `
    <div class="alert alert-info">
      <div class="spinner"></div>
      <span>Generating module by module: first a plan ${withInventory ? 'that assigns the concepts of the inventory to'
        : nNotions ? 'of the classes of' : 'that divides the domain into modules and plans the classes of'} ${nNotions
        ? `the ${nNotions} modules` : 'each'}, then each module ${withInventory ? 'with its concepts, definitions and sources'
        : 'with its planned classes, the competency questions and the data'} (four at a time). Automatic OOPS! quality
        check follows. This may take several minutes.</span>
    </div>`;
  document.getElementById('ontologyView').style.display = 'none';
  document.getElementById('toEvaluate').style.display = 'none';

  try {
    const res = await fetch(`${API}/api/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: state.sessionId,
        domain_description: combined,
        selected_standards: state.selectedStandards,
        llm_config: state.llmConfig,
      }),
    });

    const text = await res.text();
    let data;
    try { data = JSON.parse(text); } catch(_) {
      throw new Error(`The server's answer is not JSON (HTTP ${res.status}):\n${text.slice(0, 400)}`);
    }
    if (!res.ok) throw new Error(data.detail || JSON.stringify(data));
    state.currentOntology = data.ontology;
    state.currentTurtle = data.turtle;
    state.iteration = data.iteration;
    state.evaluation = null;             // gehoerte zur vorigen Ontologie; ihre Iteration 1 saehe aktuell aus

    document.getElementById('genStatus').innerHTML =
      renderModularReport(data.modular_report, { usage: (data.usage || {}).calls, title: 'Generated – the run, step by step',
                                                 when: new Date().toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) }) +
      definitionsReport(data.definitions_report) + reuseReport(data.reuse_report);
    recordUsage(data.usage, true);

    renderValidationBadge(data.oops_report?.validation);
    renderOopsReport(data.oops_report);
    renderOntology(data.ontology, data.turtle, data.iteration);
    if (document.getElementById('shaclEditorWrap').style.display !== 'none')
      buildShaclTable(data.ontology);
    markDone(6);
    state.ontologyImported = false;      // eine generierte Ontologie: die Werkzeuge oeffnen nur bei Luecken
    runCQTests();
    renderEvaluation(state.evaluation);   // noch keine Evaluation dieser Ontologie
    document.getElementById('toEvaluate').style.display = 'block';

    document.getElementById('generateBtnWrap').innerHTML =
      '<button class="btn btn-secondary" onclick="resetGenerate()">🔄 Regenerate</button>';
    document.getElementById('generateBtnWrap').style.display = 'block';

  } catch(e) {
    // the server keeps the previous ontology when a generation fails - show it again
    const kept = !!state.currentOntology;
    document.getElementById('genStatus').innerHTML =
      `<div class="alert alert-error"><div style="white-space:pre-wrap">❌ Error: ${escHtml(e.message)}${kept ? '\nThe previous ontology is unchanged.' : ''}</div></div>`;
    if (kept) {
      document.getElementById('ontologyView').style.display = 'block';
      document.getElementById('toEvaluate').style.display = 'block';
      document.getElementById('generateBtnWrap').innerHTML =
        '<button class="btn btn-secondary" onclick="resetGenerate()">🔄 Regenerate</button>';
    } else {
      document.getElementById('generateBtn').disabled = false;
    }
    document.getElementById('generateBtnWrap').style.display = 'block';
  }
}

// Bericht der Pruefung nach der Generierung: Anbindungen, reparierte und entfernte Verweise (DECISIONS 77, 78)
function reuseReport(r) {
  if (!r) return '';
  const repaired = r.dropped.filter(x => x.startsWith('repaired ')), removed = r.dropped.filter(x => !x.startsWith('repaired '));
  const list = xs => escHtml(xs.slice(0, 5).join(' · ')) + (xs.length > 5 ? ' …' : '');
  return `<div class="lit-meta" style="margin:4px 0 8px;">🔌 ${r.links} links to the loaded vocabularies${
    removed.length ? `; ${removed.length} references to terms that do not exist or do not fit were removed: ${list(removed)}` : ''}${
    repaired.length ? `; ${repaired.length} references written as Module:Class were corrected: ${list(repaired.map(x => x.slice(9)))}` : ''}</div>`;
}

// Neu generieren: nach einer Rueckfrage direkt starten (frueher blendete der Button nur die Ontologie aus)
function resetGenerate() {
  if (!confirm(`Generate a new ontology? It replaces the current one (iteration ${state.iteration}) with everything the ` +
               'improvement actions and feedback rounds have changed. Export the project first to keep this version.')) return;
  document.getElementById('generateBtnWrap').innerHTML =
    '<button class="btn btn-primary" id="generateBtn" onclick="generateOntology()">🚀 Generate Ontology</button>';
  generateOntology();
}

function renderOntology(onto, turtle, iter) {
  saveProject();
  renderHeaderStatus();
  state._coreUsage = null;               // die Rueckmeldung zum Kernvokabular gilt fuer die vorige Ontologie
  document.getElementById('iterNum').textContent = iter;

  const sr = document.getElementById('statRow');
  sr.innerHTML = [
    [onto.classes?.length || 0, 'Classes'],
    [onto.properties?.length || 0, 'Properties'],
    [onto.individuals?.length || 0, 'Individuals'],
  ].map(([v,l]) => `<div class="stat"><div class="val">${v}</div><div class="lbl">${l}</div></div>`).join('');

  document.getElementById('summaryBox').textContent = onto.summary || '';

  const ct = document.getElementById('classTable').querySelector('tbody');
  ct.innerHTML = (onto.classes || []).map(c => `
    <tr>
      <td><code>${escHtml(c.name)}</code></td>
      <td>${escHtml(ontoLabel(c))}</td>
      <td>${c.parent ? `<code>${escHtml(c.parent)}</code>` : '<span style="color:var(--text-muted)">—</span>'}</td>
      <td style="color:var(--text-muted)">${escHtml(c.description || '')}
        ${(c.sources || []).length ? `<div style="margin-top:3px;">${c.sources.map(s => `<span class="lit-pill" title="${escHtml(s)}">${escHtml(s.length > 40 ? s.slice(0, 40) + '…' : s)}</span>`).join('')}</div>` : ''}
        ${(c.see_also || []).map(u => `<div class="lit-meta">🧬 ${escHtml(u)}</div>`).join('')}</td>
    </tr>`).join('');

  const pt = document.getElementById('propTable').querySelector('tbody');
  pt.innerHTML = (onto.properties || []).map(p => `
    <tr>
      <td><code>${escHtml(p.name)}</code></td>
      <td><span class="tag ${p.type === 'ObjectProperty' ? 'tag-obj' : 'tag-data'}">${escHtml(p.type || '')}</span></td>
      <td><code>${escHtml(p.domain || '')}</code></td>
      <td><code>${escHtml(p.range || '')}</code></td>
      <td style="color:var(--text-muted)">${escHtml(p.description || '')}</td>
    </tr>`).join('');

  const it = document.getElementById('indTable').querySelector('tbody');
  it.innerHTML = (onto.individuals || []).map(i => `
    <tr>
      <td><code>${escHtml(i.name)}</code></td>
      <td><code>${escHtml(i.class || '')}</code></td>
      <td>${escHtml(ontoLabel(i))}</td>
    </tr>`).join('') || '<tr><td colspan="3" style="color:var(--text-muted); text-align:center;">No individuals defined</td></tr>';

  document.getElementById('owlCode').textContent = turtle;
  document.getElementById('ontologyView').style.display = 'block';
  document.getElementById('toEvaluate').style.display = 'block';
  renderRefineView();

  // Graph neu rendern falls Tab aktiv
  if (document.getElementById('tab-graph').classList.contains('active')) {
    renderGraph(onto);
  }
}

// ── Tabs ───────────────────────────────────────────────────────────────────────
function switchTab(e, name) {
  // Auf den Tab-Container selbst begrenzen, damit die Panel-Nummerierung egal ist.
  const panel = e.target.closest('.panel');
  panel.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  panel.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  e.target.classList.add('active');
  document.getElementById('tab-' + name).classList.add('active');
  if (name === 'graph' && state.currentOntology) renderGraph(state.currentOntology);
}

// ── Graph ──────────────────────────────────────────────────────────────────────
let visNetwork = null;

function renderGraph(onto) {
  const GRAPH = graphColors();
  const container = document.getElementById('ontologyGraph');
  const nodes = [];
  const edges = [];
  const classIds = new Set();

  // Sammle alle Klassenbezeichner
  (onto.classes || []).forEach(c => classIds.add(c.name));

  // Klassen als Knoten
  (onto.classes || []).forEach(c => {
    const isRoot = !c.parent;
    nodes.push({
      id: 'cls_' + c.name,
      label: ontoLabel(c) ? c.name + '\n(' + ontoLabel(c) + ')' : c.name,
      title: c.description || c.name,
      shape: 'ellipse',
      // die Leinwand kennt keine CSS-Variablen: die Farben des hellen Themas hier als Werte
      color: {
        background: isRoot ? GRAPH.accent : GRAPH.accentSoft,
        border: GRAPH.accent,
        highlight: { background: isRoot ? GRAPH.accentDark : GRAPH.highlightSoft, border: GRAPH.accentDark },
      },
      font: { color: isRoot ? GRAPH.onAccent : GRAPH.text, size: 13, face: 'Inter, Segoe UI, sans-serif' },
      mass: isRoot ? 2 : 1,
    });
    // SubClassOf-Kante
    if (c.parent && classIds.has(c.parent)) {
      edges.push({
        from: 'cls_' + c.name,
        to: 'cls_' + c.parent,
        label: 'subClassOf',
        dashes: true,
        arrows: { to: { enabled: true, scaleFactor: 0.7 } },
        color: { color: GRAPH.muted },
        font: { color: GRAPH.muted, size: 10, align: 'middle', strokeColor: GRAPH.bg },
        smooth: { type: 'curvedCW', roundness: 0.2 },
      });
    }
  });

  // Individuen
  (onto.individuals || []).forEach(i => {
    nodes.push({
      id: 'ind_' + i.name,
      label: ontoLabel(i) ? i.name + '\n(' + ontoLabel(i) + ')' : i.name,
      title: 'Individuum: ' + (i.class || ''),
      shape: 'diamond',
      color: { background: GRAPH.success, border: GRAPH.success, highlight: { background: GRAPH.successHi, border: GRAPH.success } },
      font: { color: GRAPH.onAccent, size: 12, face: 'Inter, Segoe UI, sans-serif' },
    });
    if (i.class && classIds.has(i.class)) {
      edges.push({
        from: 'ind_' + i.name,
        to: 'cls_' + i.class,
        label: 'instanceOf',
        dashes: [4, 4],
        arrows: { to: { enabled: true, scaleFactor: 0.6 } },
        color: { color: GRAPH.success },
        font: { color: GRAPH.success, size: 10, align: 'middle', strokeColor: GRAPH.bg },
      });
    }
  });

  // ObjectProperties als Kanten
  (onto.properties || []).forEach(p => {
    if (p.type !== 'ObjectProperty') return;
    const fromId = 'cls_' + p.domain;
    const toId   = 'cls_' + p.range;
    if (!classIds.has(p.domain) || !classIds.has(p.range)) return;
    edges.push({
      from: fromId,
      to: toId,
      label: ontoLabel(p) || p.name,
      arrows: { to: { enabled: true, scaleFactor: 0.8 } },
      color: { color: GRAPH.warning },
      font: { color: GRAPH.warning, size: 11, align: 'middle', strokeWidth: 0 },
      smooth: { type: 'curvedCW', roundness: 0.15 },
    });
  });

  const data = { nodes: new vis.DataSet(nodes), edges: new vis.DataSet(edges) };
  const options = {
    physics: {
      enabled: true,
      solver: 'forceAtlas2Based',
      forceAtlas2Based: { gravitationalConstant: -80, springLength: 140, springConstant: 0.05 },
      stabilization: { iterations: 200 },
    },
    interaction: { hover: true, tooltipDelay: 150, navigationButtons: true, keyboard: true },
    layout: { improvedLayout: true },
  };

  if (visNetwork) visNetwork.destroy();
  visNetwork = new vis.Network(container, data, options);
}

// ── Turtle Validation Badge ────────────────────────────────────────────────────
function renderValidationBadge(val) {
  const el = document.getElementById('validationBadge');
  if (!val) { el.style.display = 'none'; return; }

  let bg, color, icon, text;
  if (val.valid && !val.fixed) {
    bg = 'var(--success-soft)'; color = 'var(--success)'; icon = '✔'; text = 'Turtle syntax valid';
  } else if (val.fixed && val.valid) {
    bg = 'var(--warning-soft)'; color = 'var(--warning)'; icon = '🔧'; text = 'Syntax error auto-corrected';
  } else if (val.fixed && !val.valid) {
    bg = 'var(--error-soft)'; color = 'var(--error)'; icon = '⚠️'; text = 'Syntax error (correction incomplete)';
  } else {
    bg = 'var(--error-soft)'; color = 'var(--error)'; icon = '⚠️'; text = 'Syntax error detected';
  }

  el.style.display = 'inline-flex';
  el.style.cssText = `display:inline-flex; align-items:center; gap:6px; padding:4px 12px; border-radius:20px; font-size:0.8rem; font-weight:600; background:${bg}; color:${color}; border:1px solid ${color}33;`;
  el.title = val.error || '';
  el.innerHTML = `<span>${icon}</span><span>${text}</span>`;
  if (val.error) el.innerHTML += ` <span style="font-weight:400; cursor:help; text-decoration:underline dotted;" title="${escHtml(val.error)}">Details</span>`;
  // Ungueltige Bezeichner benennt der Server selbst um - das soll sichtbar sein, nicht still passieren
  if ((val.renamed || []).length) el.innerHTML += ` <span style="font-weight:400; cursor:help; text-decoration:underline dotted;"
    title="${escHtml(val.renamed.map(r => `${r.old} → ${r.new}`).join('\n'))}">${val.renamed.length} name${val.renamed.length !== 1 ? 's' : ''} renamed</span>`;
}
