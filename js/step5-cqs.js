// Schritt 5: Kompetenzfragen
// (PLAN.md Phase 4: eine Datei je Schritt; klassische Skripte - alle Funktionen sind global,
// sofort ausgefuehrt wird nur main.js, das zuletzt laedt)

// ── Step 3: Competency Questions (MOMo Step 2) ────────────────────────────────
async function proceedToCQs() {
  if (!document.getElementById('domainDesc').value.trim()) {
    alert('Please describe the use case first.'); return;
  }
  await saveMomo();
  goTo(3);
  if (!state.momo.competencyQuestions.length) suggestCQs();
}

async function suggestCQs() {
  const data = await momoCall('suggest-cqs', 'cqStatus', 'Gathering competency questions…');
  if (!data) return;
  if (data.limit_reached) {
    document.getElementById('cqStatus').innerHTML = `<div class="alert alert-info"><span>ℹ️</span>
      <span>There are already 10 competency questions — remove some to get new suggestions.</span></div>`;
    return;
  }
  (data.competency_questions || []).forEach(cq => {
    if (cq && cq.question) state.momo.competencyQuestions.push(cq);
  });
  renderCQs(); saveMomo();
}

function addCQ() {
  state.momo.competencyQuestions.push({ question: '', rationale: '' });
  renderCQs();
}

// Fragen als nummerierte Zeilen (DECISIONS 126)
function renderCQs() {
  const list = state.momo.competencyQuestions;
  document.getElementById('cqCount').textContent = list.length ? `· ${list.length}` : '';
  document.getElementById('cqList').innerHTML = list.length ? list.map((cq, i) => `
    <div class="list-row">
      <span class="list-num">${i + 1}</span>
      <div class="list-body">
        <textarea rows="2" oninput="updateCQ(${i}, this.value)" aria-label="Competency question ${i + 1}"
          placeholder="e.g. Which vegetarian recipes take less than 30 minutes?">${esc(cq.question)}</textarea>
        ${cq.rationale ? `<div class="list-meta">${esc(cq.rationale)}</div>` : ''}
      </div>
      <button class="icon-btn" onclick="removeCQ(${i})" title="Remove" aria-label="Remove question ${i + 1}">✕</button>
    </div>`).join('')
    : `<div class="list-empty">No competency questions yet – add them, or let the model suggest some.</div>`;
  if (typeof renderSidebarStatus === 'function') renderSidebarStatus();
}

function updateCQ(i, v) { state.momo.competencyQuestions[i].question = v; }
function removeCQ(i) { state.momo.competencyQuestions.splice(i, 1); renderCQs(); saveMomo(); }
