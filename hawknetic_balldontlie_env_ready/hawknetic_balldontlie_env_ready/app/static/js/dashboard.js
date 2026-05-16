const parlayLegs = [];

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options
  });
  let data = {};
  try { data = await response.json(); } catch (err) { data = { detail: 'Non-JSON response from backend.' }; }
  if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
  return data;
}

function setBadge(id, label, ok, detail = '') {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = detail ? `${label}: ${detail}` : label;
  el.classList.toggle('ok', Boolean(ok));
  el.classList.toggle('bad', !ok);
}

function renderRows(table, rows) {
  const tbody = table?.querySelector('tbody');
  if (!tbody) return;
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="5" class="muted">No backend records yet. This is an empty real-data state, not mock data.</td></tr>';
    return;
  }
  tbody.innerHTML = rows.map((row, index) => {
    const label = `${row.market || 'Prop'} ${row.selection || ''}`.trim();
    return `<tr>
      <td>${label}</td>
      <td>${row.line ?? '-'}</td>
      <td>${row.expected_value ?? '-'}</td>
      <td>${row.confidence_tier || '-'}</td>
      <td><button class="button button-small" data-add-leg="${index}">Add</button></td>
    </tr>`;
  }).join('');
  tbody.querySelectorAll('[data-add-leg]').forEach((button) => {
    button.addEventListener('click', () => {
      const row = rows[Number(button.dataset.addLeg)];
      parlayLegs.push({
        prop_id: row.id,
        label: `${row.market || 'Prop'} ${row.line ?? ''}`.trim(),
        odds_value: row.over_odds || row.under_odds || 100,
        probability: row.model_probability || 0.5
      });
      renderParlayLegs();
    });
  });
}

function renderParlayLegs() {
  const list = document.getElementById('parlay-legs');
  if (!list) return;
  if (!parlayLegs.length) {
    list.innerHTML = '<li class="muted">No legs added.</li>';
    return;
  }
  list.innerHTML = parlayLegs.map((leg, index) => `<li>
    <strong>${index + 1}. ${leg.label}</strong>
    <span class="muted"> odds ${leg.odds_value ?? '-'}</span>
    <button class="link-button" data-up="${index}" type="button">Up</button>
    <button class="link-button" data-down="${index}" type="button">Down</button>
    <button class="link-button" data-remove="${index}" type="button">Remove</button>
  </li>`).join('');
  list.querySelectorAll('[data-remove]').forEach((btn) => btn.addEventListener('click', () => { parlayLegs.splice(Number(btn.dataset.remove), 1); renderParlayLegs(); }));
  list.querySelectorAll('[data-up]').forEach((btn) => btn.addEventListener('click', () => { const i = Number(btn.dataset.up); if (i > 0) [parlayLegs[i - 1], parlayLegs[i]] = [parlayLegs[i], parlayLegs[i - 1]]; renderParlayLegs(); }));
  list.querySelectorAll('[data-down]').forEach((btn) => btn.addEventListener('click', () => { const i = Number(btn.dataset.down); if (i < parlayLegs.length - 1) [parlayLegs[i + 1], parlayLegs[i]] = [parlayLegs[i], parlayLegs[i + 1]]; renderParlayLegs(); }));
}

async function loadDashboardData() {
  if (!document.querySelector('[data-dashboard-api]')) return;
  try {
    const health = await api('/api/health');
    setBadge('backend-status', 'Backend', health.status === 'ok', health.status);
    setBadge('database-status', 'Railway PG', health.database?.railway_postgres && health.database?.ok, health.database?.railway_postgres ? (health.database.ok ? 'connected' : 'error') : 'not configured');
    setBadge('bdl-status', 'BDL', health.ball_dont_lie_configured, health.ball_dont_lie_configured ? 'configured' : 'missing key');
  } catch (err) {
    setBadge('backend-status', 'Backend', false, err.message);
  }

  try {
    const status = await api('/api/data-status');
    const dbPanel = document.getElementById('database-panel');
    if (dbPanel) dbPanel.innerHTML = `<p class="metric">${status.database.table_count}</p><p class="muted">tables visible through ${status.database.engine}</p><p class="${status.database.ok ? 'success' : 'error'}">${status.database.ok ? 'Database query succeeded' : status.database.error}</p>`;
    const coverage = status.historical_coverage;
    const coveragePanel = document.getElementById('coverage-panel');
    if (coveragePanel) coveragePanel.innerHTML = `<p class="metric">${coverage.complete_seasons}/${coverage.total_seasons}</p><p class="muted">complete seasons from ${coverage.start_season}-${coverage.end_season}</p><div class="locked">${coverage.incomplete_seasons} incomplete seasons need historical backfill.</div>`;
    const livePanel = document.getElementById('live-api-panel');
    if (livePanel) livePanel.innerHTML = `<p class="metric">${status.bdl.counts.games}</p><p class="muted">BDL games | ${status.bdl.counts.players} players | ${status.bdl.counts.teams} teams</p>`;
  } catch (err) {
    ['database-panel', 'coverage-panel', 'live-api-panel'].forEach((id) => { const el = document.getElementById(id); if (el) el.innerHTML = `<p class="error">${err.message}</p>`; });
  }

  try {
    const props = await api('/api/props');
    renderRows(document.getElementById('prop-table'), props.items || []);
    const ev = document.getElementById('ev-table');
    if (ev) ev.textContent = (props.items || []).length ? `${props.items.length} EV records loaded from FastAPI.` : 'No EV records in PostgreSQL yet.';
  } catch (err) {
    const tbody = document.querySelector('#prop-table tbody');
    if (tbody) tbody.innerHTML = `<tr><td colspan="5" class="error">${err.message}</td></tr>`;
  }

  try {
    const logs = await api('/api/bdl/logs');
    const panel = document.getElementById('ingestion-panel');
    if (panel) panel.innerHTML = (logs.items || []).length
      ? `<ul class="list">${logs.items.slice(0, 5).map((log) => `<li>${log.resource}: <strong>${log.status}</strong> <span class="muted">${log.error_text || `${log.records_written} written`}</span></li>`).join('')}</ul>`
      : '<p class="muted">No BDL ingestion logs yet.</p>';
  } catch (err) {
    const panel = document.getElementById('ingestion-panel');
    if (panel) panel.innerHTML = `<p class="error">${err.message}</p>`;
  }

  try {
    const parlays = await api('/api/parlays');
    const saved = document.getElementById('saved-parlays');
    if (saved) saved.innerHTML = (parlays.items || []).length
      ? `<ul class="list">${parlays.items.map((p) => `<li>${p.name} <span class="muted">${p.risk_tier || 'risk pending'}</span></li>`).join('')}</ul>`
      : '<p class="muted">No saved parlays yet.</p>';
  } catch (err) {
    const saved = document.getElementById('saved-parlays');
    if (saved) saved.innerHTML = `<p class="error">${err.message}</p>`;
  }
}

async function buildParlay() {
  const output = document.getElementById('parlay-output');
  if (!output) return;
  if (!parlayLegs.length) {
    output.textContent = 'Add at least one leg first.';
    return;
  }
  output.textContent = 'Building parlay...';
  try {
    const data = await api('/api/parlays/build', { method: 'POST', body: JSON.stringify({ name: 'Dashboard Parlay', legs: parlayLegs }) });
    output.textContent = JSON.stringify(data.parlay, null, 2);
  } catch (err) {
    output.textContent = err.message;
  }
}

async function runSimulation() {
  const panel = document.getElementById('simulation-panel');
  try {
    const data = await api('/api/simulations/run', { method: 'POST', body: JSON.stringify({ runs: 1000 }) });
    if (panel) panel.insertAdjacentHTML('beforeend', `<pre class="output-box">${JSON.stringify(data.result, null, 2)}</pre>`);
  } catch (err) {
    if (panel) panel.insertAdjacentHTML('beforeend', `<p class="error">${err.message}</p>`);
  }
}

async function sendPrompt() {
  const promptEl = document.getElementById('ai-prompt');
  const outputEl = document.getElementById('ai-output');
  if (!promptEl || !outputEl) return;
  const prompt = promptEl.value.trim();
  if (!prompt) {
    outputEl.textContent = 'Enter a finding or question first.';
    return;
  }
  outputEl.textContent = 'Working...';
  try {
    const data = await api('/api/ai/chat', { method: 'POST', body: JSON.stringify({ prompt }) });
    outputEl.textContent = data.content;
  } catch (err) {
    outputEl.textContent = err.message;
  }
}

document.getElementById('ai-send')?.addEventListener('click', sendPrompt);
document.getElementById('build-parlay')?.addEventListener('click', buildParlay);
document.getElementById('run-simulation')?.addEventListener('click', runSimulation);
document.getElementById('sidebar-toggle')?.addEventListener('click', () => document.querySelector('.app-shell')?.classList.toggle('sidebar-collapsed'));
renderParlayLegs();
loadDashboardData();
