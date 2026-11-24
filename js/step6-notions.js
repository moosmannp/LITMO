// Schritt 6: Key Notions und Module
// (PLAN.md Phase 4: eine Datei je Schritt; klassische Skripte - alle Funktionen sind global,
// sofort ausgefuehrt wird nur main.js, das zuletzt laedt)

// ── Step 4: Key Notions (MOMo Step 3) ─────────────────────────────────────────
// Standard: das Team definiert die Key Notions selbst; Vorschlaege sind optional und muessen einzeln
// uebernommen werden.
let notionSuggestions = [];

async function proceedToNotions() {
  await saveMomo();
  goTo(4);
  if (!state.momo.keyNotions.length) addNotion();
  else renderNotions();
}

async function suggestNotions() {
  // momoCall speichert vorher — auch unfertige Eingaben, damit keine Duplikate vorgeschlagen werden.
  const data = await momoCall('suggest-notions', 'notionStatus', 'Looking for missing key notions…');
  if (!data) return;
  notionSuggestions = (data.key_notions || []).filter(n => n && n.name);
  if (!notionSuggestions.length)
    document.getElementById('notionStatus').innerHTML =
      '<div class="alert alert-success">✅ No missing key notions found — your list already covers the use case.</div>';
  renderNotionSuggestions();
}

function renderNotionSuggestions() {
  document.getElementById('notionSuggestions').innerHTML = notionSuggestions.length ? `<div class="list-card" style="margin-top:10px;">${notionSuggestions.map((n, i) => `
    <div class="list-row">
      <div class="list-body">
        <div style="font-weight:600;">${esc(n.name)} ${n.hidden ? '<span class="pill warn">hidden concept</span>' : ''}</div>
        ${n.description ? `<div class="list-meta">${esc(n.description)}</div>` : ''}
        ${(n.from_cqs && n.from_cqs.length) ? `<div class="list-meta">Traces to: ${n.from_cqs.map(c => esc(c)).join(' · ')}</div>` : ''}
      </div>
      <button class="btn btn-secondary btn-sm" onclick="acceptNotion(${i})">Add</button>
      <button class="icon-btn" onclick="dismissNotion(${i})" title="Dismiss" aria-label="Dismiss ${esc(n.name)}">✕</button>
    </div>`).join('')}</div>` : '';
}

function acceptNotion(i) {
  const [n] = notionSuggestions.splice(i, 1);
  // Eine leere Platzhalterzeile ersetzen statt eine weitere anzuhaengen.
  const blank = state.momo.keyNotions.findIndex(k => !k.name.trim());
  if (blank >= 0) state.momo.keyNotions[blank] = n; else state.momo.keyNotions.push(n);
  renderNotions(); renderNotionSuggestions(); saveMomo();
}

function dismissNotion(i) { notionSuggestions.splice(i, 1); renderNotionSuggestions(); }

function addNotion() {
  state.momo.keyNotions.push({ name: '', description: '', hidden: false, from_cqs: [] });
  renderNotions();
  const inputs = document.querySelectorAll('#notionList input');
  if (inputs.length) inputs[inputs.length - 1].focus();
}

function renderNotions() {
  const list = state.momo.keyNotions;
  renderNotionCount();
  document.getElementById('notionList').innerHTML = list.length ? list.map((n, i) => `
    <div class="list-row">
      <span class="list-num">${i + 1}</span>
      <div class="list-body">
        <div style="display:flex; gap:8px; align-items:center;">
          <input type="text" value="${esc(n.name)}" oninput="updateNotion(${i},'name',this.value)" aria-label="Key notion ${i + 1}"
                 placeholder="KeyNotionName" style="font-weight:600;" />
          ${n.hidden ? '<span class="pill warn">hidden concept</span>' : ''}
        </div>
        <textarea rows="2" oninput="updateNotion(${i},'description',this.value)" aria-label="What key notion ${i + 1} covers"
          placeholder="What does this notion cover?">${esc(n.description)}</textarea>
        ${(n.from_cqs && n.from_cqs.length) ? `<div class="list-meta">Traces to: ${n.from_cqs.map(c => esc(c)).join(' · ')}</div>` : ''}
      </div>
      <button class="icon-btn" onclick="removeNotion(${i})" title="Remove" aria-label="Remove key notion ${i + 1}">✕</button>
    </div>`).join('')
    : `<div class="list-empty">No key notions yet – add the central concepts your ontology is built around.</div>`;
}

function updateNotion(i, field, v) {
  state.momo.keyNotions[i][field] = v;
  if (field === 'name') renderNotionCount();
}
// Nur den Zaehler aktualisieren, damit das Eingabefeld beim Tippen den Fokus behaelt.
function renderNotionCount() {
  const named = state.momo.keyNotions.filter(n => n.name.trim()).length;
  document.getElementById('notionCount').textContent = !named ? '' : `· ${named} → ${named} module${named !== 1 ? 's' : ''}`;
  const warn = document.getElementById('notionWarn');
  warn.style.display = named > 7 ? 'flex' : 'none';
  warn.textContent = `${named} modules is a lot – are some of these notions parts of another one?`;
  if (typeof renderSidebarStatus === 'function') renderSidebarStatus();
}
function removeNotion(i) { state.momo.keyNotions.splice(i, 1); renderNotions(); saveMomo(); }
// Eine leere Zeile des Formulars ist keine Key Notion (der Server speichert sie gar nicht erst).
function namedNotions() { return state.momo.keyNotions.filter(n => n && (n.name || '').trim()); }
