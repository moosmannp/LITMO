// Schritt 1: LLM konfigurieren
// (PLAN.md Phase 4: eine Datei je Schritt; klassische Skripte - alle Funktionen sind global,
// sofort ausgefuehrt wird nur main.js, das zuletzt laedt)

// ── Step 1: LLM Config ─────────────────────────────────────────────────────────
// Modelle laut KI:connect-Oberflaeche. Die IDs der neueren Modelle sind abgeleitet — massgeblich ist die
// Liste, die GET /v1/models liefert (siehe loadProviderModels).
const RWTH_MODELS = [
  ['mistral-small-4-119b-2603', 'Mistral Small 4 119B (reasoning, hosted in NRW)'],
  ['qwen-3.8-27b', 'Qwen 3.8 27B (hosted in NRW)'],
  ['gpt-oss-120b', 'OpenAI GPT OSS 120b (hosted in NRW)'],
  ['gpt-6-astra', 'OpenAI GPT-6 Astra'],
  ['gpt-6-sol', 'OpenAI GPT-6 Sol'],
  ['gpt-6-luna', 'OpenAI GPT-6 Luna'],
];

async function loadProviderModels() {
  const provider = document.getElementById('provider').value;
  const apiKey = document.getElementById('apiKey').value.trim();
  const hint = document.getElementById('modelHint');
  if (provider !== 'rwthgpt' || (!apiKey && !serverKey(provider))) return;
  hint.style.display = 'block';
  hint.textContent = '⏳ Loading available models from KI:connect…';
  try {
    const res = await fetch(`${API}/api/models`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider, api_key: apiKey, model: '',
                             base_url: document.getElementById('baseUrl').value.trim() }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Request failed');
    if (document.getElementById('provider').value !== provider || !data.models.length) return;
    const sel = document.getElementById('model');
    const prev = sel.value;
    const labels = Object.fromEntries(RWTH_MODELS);
    // Bekannte Modelle in der Reihenfolge der Liste oben, danach alle weiteren
    const ids = [...RWTH_MODELS.map(([id]) => id).filter(id => data.models.includes(id)),
                 ...data.models.filter(id => !labels[id]).sort()];
    sel.innerHTML = ids.map(id => `<option value="${escHtml(id)}">${escHtml(labels[id] || id)}</option>`).join('');
    if (ids.includes(prev)) sel.value = prev;
    hint.textContent = `✅ ${ids.length} models available on KI:connect.`;
  } catch (e) {
    hint.textContent = `⚠️ Could not load the model list (${e.message}); showing the default list.`;
  }
}

function updateModelOptions() {
  const provider = document.getElementById('provider').value;
  const sel = document.getElementById('model');
  sel.innerHTML = '';
  if (provider === 'anthropic') {
    [
      ['claude-opus-5-5', 'Claude Opus 5.5 (recommended) — $4 / $20 per 1M tokens'],
      ['claude-fable-5-1', 'Claude Fable 5.1 (most capable) — $10 / $50'],
      ['claude-sonnet-5-5', 'Claude Sonnet 5.5 (balanced) — $2 / $10'],
      ['claude-haiku-4-5', 'Claude Haiku 4.5 (fast, low cost) — $1 / $5'],
    ].forEach(([v, l]) => sel.innerHTML += `<option value="${v}">${l}</option>`);
  } else if (provider === 'openai') {
    [
      ['gpt-6-astra', 'GPT-6 Astra (recommended)'],
      ['gpt-5.6-sol', 'GPT-5.6 Sol'],
      ['gpt-5.6-terra', 'GPT-5.6 Terra (balanced cost)'],
      ['gpt-5.6-luna', 'GPT-5.6 Luna (low cost)'],
    ].forEach(([v, l]) => sel.innerHTML += `<option value="${v}">${l}</option>`);
  } else if (provider === 'rwthgpt') {
    // Vorlaeufige Liste; loadProviderModels() ersetzt sie durch die echten Deployment-Namen von KI:connect.
    RWTH_MODELS.forEach(([v, l]) => sel.innerHTML += `<option value="${v}">${l}</option>`);
  } else if (provider === 'gemini') {
    [
      ['gemini-3.8-flash', 'Gemini 3.8 Flash (recommended)'],
      ['gemini-3.1-pro-preview', 'Gemini 3.1 Pro (preview, strongest reasoning)'],
      ['gemini-3.7-flash', 'Gemini 3.7 Flash'],
      ['gemini-3.6-flash', 'Gemini 3.6 Flash'],
      ['gemini-3.5-flash-lite', 'Gemini 3.5 Flash-Lite (fast, low cost)'],
      ['gemini-3.1-flash-lite', 'Gemini 3.1 Flash-Lite (low cost)'],
    ].forEach(([v, l]) => sel.innerHTML += `<option value="${v}">${l}</option>`);
  }
  const isRwth   = provider === 'rwthgpt';
  const isCustom = provider === 'custom';

  // Modell-Dropdown vs. Freitext
  sel.style.display = isCustom ? 'none' : 'block';
  document.getElementById('modelCustom').style.display = isCustom ? 'block' : 'none';
  document.getElementById('modelHint').style.display = 'none';

  // Base-URL-Feld
  document.getElementById('baseUrlCard').style.display = (isRwth || isCustom) ? 'block' : 'none';
  document.getElementById('customProviderCard').style.display = isCustom ? 'block' : 'none';

  if (provider === 'gemini') {
    document.getElementById('baseUrlCard').style.display = 'none';
    document.getElementById('apiKey').placeholder = 'Google AI API-Key (aus aistudio.google.com)';
  } else if (isRwth) {
    if (!document.getElementById('baseUrl').value)
      document.getElementById('baseUrl').value = 'https://chat.kiconnect.nrw/api/v1';
    // kein Schluessel im Code mehr (DECISIONS 139): hat der Server einen, darf das Feld leer bleiben
    document.getElementById('apiKey').placeholder = serverKey('rwthgpt')
      ? 'Leave empty to use the server\'s KI:connect key' : 'KI:connect API key';
    document.getElementById('baseUrlHint').innerHTML =
      'Die Base-URL findest du in den <a href="https://chat.kiconnect.nrw/app/api-docs/" target="_blank" style="color:var(--accent-light);">KI:connect API-Docs</a>.';
    loadProviderModels();
  } else if (isCustom) {
    document.getElementById('baseUrl').value = '';
    document.getElementById('baseUrlHint').textContent = 'Basis-URL des OpenAI-kompatiblen Endpunkts (ohne /chat/completions).';
  } else {
    document.getElementById('baseUrlHint').textContent = '';
  }
}

// Liest die LLM-Konfiguration aus Schritt 1. Gibt bei fehlenden Angaben eine Fehlermeldung (String) zurueck.
function readLlmConfig() {
  const apiKey = document.getElementById('apiKey').value.trim();
  const provider = document.getElementById('provider').value;
  if (!apiKey && !serverKey(provider)) return 'Please enter an API key.';
  const model = provider === 'custom'
    ? document.getElementById('modelCustom').value.trim()
    : document.getElementById('model').value;
  if (!model) return 'Please enter a model name.';
  if (provider === 'custom' && !document.getElementById('baseUrl').value.trim()) return 'Please enter the API base URL.';
  const cfg = {
    provider: provider === 'custom' ? 'openai' : provider,  // custom nutzt openai-kompatiblen Pfad
    api_key: apiKey,
    model,
    // nur RWTH und Custom nutzen eine eigene URL; ein Rest im versteckten Feld darf OpenAI nicht umleiten
    base_url: provider === 'rwthgpt' || provider === 'custom' ? document.getElementById('baseUrl').value.trim() : '',
  };
  if (provider === 'custom') cfg._displayName = document.getElementById('customProviderName').value.trim() || 'Custom';
  return cfg;
}

// Fuer welche Anbieter der Server einen Schluessel hat (DECISIONS 139); geladen beim Start in main.js
function serverKey(provider) { return !!(state.serverKeys || {})[provider]; }
async function loadServerConfig() {
  try {
    const r = await fetch(`${API}/api/config`);
    if (r.ok) state.serverKeys = (await r.json()).server_keys || {};
  } catch (e) { state.serverKeys = {}; }
}

function saveConfig() {
  const cfg = readLlmConfig();
  if (typeof cfg === 'string') { alert(cfg); return; }
  state.llmConfig = cfg;
  state.keyNeededModel = null;
  document.getElementById('keyNotice').style.display = 'none';
  markDone(1);
  goTo(2);
}
