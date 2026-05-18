const parlayLegs = [];
let builtParlay = null;

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

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  }[char]));
}

function formatOdds(value) {
  if (value === undefined || value === null) return '-';
  return value > 0 ? `+${value}` : String(value);
}

function formatProbability(value) {
  if (value === undefined || value === null) return '50%';
  return `${Math.round(value * 100)}%`;
}

function formatSignedPercent(value) {
  const rounded = Math.round(value * 100);
  return `${rounded > 0 ? '+' : ''}${rounded}%`;
}

function clampProbability(value) {
  return Math.max(0.01, Math.min(value ?? 0.5, 0.99));
}

function impliedProbabilityFromOdds(odds) {
  if (!odds) return 0.5;
  return odds > 0 ? 100 / (odds + 100) : Math.abs(odds) / (Math.abs(odds) + 100);
}

function decimalOdds(odds) {
  if (!odds) return 2;
  return odds > 0 ? 1 + odds / 100 : 1 + 100 / Math.abs(odds);
}

function product(values) {
  return values.reduce((current, value) => current * value, 1);
}

function edgeForLeg(leg) {
  return clampProbability(leg.probability) - impliedProbabilityFromOdds(leg.odds_value);
}

function calculateSlipMetrics(legs) {
  const probabilities = legs.map((leg) => clampProbability(leg.probability));
  const winProbability = legs.length ? product(probabilities) : 0;
  const lossProbability = legs.length ? 1 - winProbability : 0;
  const estimatedOdds = winProbability > 0 ? Math.round((1 / winProbability - 1) * 100) : undefined;
  const riskTier = !legs.length ? 'ungraded' : legs.length >= 4 || winProbability < 0.2 ? 'high' : legs.length >= 2 ? 'medium' : 'low';
  const legImpacts = legs.map((leg, index) => {
    const edge = edgeForLeg(leg);
    const otherProbability = product(probabilities.filter((_, probabilityIndex) => probabilityIndex !== index));
    const drag = otherProbability - winProbability;
    return {
      edge,
      drag,
      label: edge >= 0.08 ? 'Sharp edge' : edge >= 0.02 ? 'Positive lean' : edge > -0.03 ? 'Fair price' : 'Trap risk'
    };
  });
  const averageProbability = probabilities.length ? probabilities.reduce((sum, value) => sum + value, 0) / probabilities.length : 0;
  const averageEdge = legImpacts.length ? legImpacts.reduce((sum, impact) => sum + impact.edge, 0) / legImpacts.length : 0;
  const weakestLegIndex = legImpacts.reduce((weakest, impact, index) => impact.edge < (legImpacts[weakest]?.edge ?? Infinity) ? index : weakest, 0);
  const score = winProbability * 60 + averageProbability * 25 + Math.max(-0.15, Math.min(averageEdge, 0.25)) * 100;
  const grade = !legs.length ? '--' : score >= 58 ? 'A' : score >= 48 ? 'B+' : score >= 38 ? 'B' : score >= 28 ? 'C+' : 'D';
  const volatility = !legs.length ? 'No ticket' : riskTier === 'high' ? 'Volatile' : averageEdge >= 0.05 ? 'Controlled upside' : 'Balanced';
  const recommendation = !legs.length
    ? 'Add legs to unlock Smart Slip Lab.'
    : legImpacts[weakestLegIndex]?.edge < -0.03
      ? 'Optimizer sees one leg priced worse than the model.'
      : riskTier === 'high'
        ? 'High variance slip: consider reducing leg count.'
        : 'Model profile is playable for analysis.';
  return { winProbability, lossProbability, estimatedOdds, riskTier, grade, volatility, averageProbability, averageEdge, weakestLegIndex, legImpacts, recommendation };
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

function impactWidth(edge) {
  return `${Math.max(8, Math.min(100, 50 + edge * 240))}%`;
}

function renderSlipMetrics() {
  const metrics = calculateSlipMetrics(parlayLegs);
  const displayedWin = builtParlay?.win_probability ?? metrics.winProbability;
  const displayedRisk = builtParlay?.risk_tier || metrics.riskTier;
  const displayedOdds = builtParlay?.estimated_odds ?? metrics.estimatedOdds;
  setText('active-slip-count', parlayLegs.length);
  setText('slip-leg-pill', `${parlayLegs.length} legs`);
  setText('model-win', parlayLegs.length ? `${Math.round(displayedWin * 100)}%` : '--');
  setText('model-win-label', builtParlay ? 'saved score' : 'live lab estimate');
  setText('slip-grade-stat', metrics.grade);
  setText('slip-volatility', metrics.volatility);
  setText('slip-est-win', parlayLegs.length ? `${Math.round(displayedWin * 100)}%` : '--');
  setText('slip-risk', displayedRisk);
  setText('lab-grade', metrics.grade);
  setText('lab-volatility', metrics.volatility);
  setText('lab-edge', `Avg edge ${formatSignedPercent(metrics.averageEdge)}`);
  setText('lab-odds', `Projected odds ${displayedOdds ?? '--'}`);
  setText('lab-recommendation', metrics.recommendation);
  setText('correlation-copy', builtParlay?.correlation_warning || (parlayLegs.length > 1 ? 'Backend correlation review runs when the ticket is saved.' : 'Add multiple legs to check same-game and same-player risk.'));
  setText('trap-copy', builtParlay?.trap_leg_warning || (metrics.legImpacts[metrics.weakestLegIndex]?.label === 'Trap risk' ? 'Trap leg detected by price/model edge.' : 'No trap leg flagged in the live lab yet.'));
  document.querySelectorAll('[data-optimize]').forEach((button) => {
    const mode = button.dataset.optimize;
    button.disabled = mode === 'trap' ? !parlayLegs.length : parlayLegs.length < 2;
  });
}

function renderRows(table, rows) {
  const tbody = table?.querySelector('tbody');
  if (!tbody) return;
  const boardRows = [...rows].sort((a, b) => (b.expected_value || 0) - (a.expected_value || 0)).slice(0, 12);
  setText('market-count', rows.length);
  setText('market-pill', `${rows.length} markets`);
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="muted">No backend records yet. This is an empty real-data state, not mock data.</td></tr>';
    return;
  }
  tbody.innerHTML = boardRows.map((row, index) => {
    const label = `${row.market || row.selection || 'Prop'}`.trim();
    return `<tr>
      <td><strong>${escapeHtml(label)}</strong><small>${escapeHtml(row.confidence_tier || 'confidence pending')}</small></td>
      <td>${row.line ?? '-'}</td>
      <td>${formatProbability(row.model_probability)}</td>
      <td>${row.expected_value ?? '-'}</td>
      <td>${formatOdds(row.over_odds || row.under_odds)}</td>
      <td><button class="button button-small" data-add-leg="${index}">Add to slip</button></td>
    </tr>`;
  }).join('');
  tbody.querySelectorAll('[data-add-leg]').forEach((button) => {
    button.addEventListener('click', () => {
      const row = boardRows[Number(button.dataset.addLeg)];
      parlayLegs.push({
        prop_id: row.id,
        label: `${row.market || 'Prop'} ${row.line ?? ''}`.trim(),
        odds_value: row.over_odds || row.under_odds || 100,
        probability: row.model_probability || 0.5,
        expected_value: row.expected_value,
        confidence_tier: row.confidence_tier
      });
      builtParlay = null;
      renderParlayLegs();
    });
  });
}

function renderParlayLegs() {
  const list = document.getElementById('parlay-legs');
  if (!list) return;
  renderSlipMetrics();
  if (!parlayLegs.length) {
    list.innerHTML = '<li class="empty-slip"><strong>No active ticket yet</strong><p>Add legs from the predictor board to build and rank a slip.</p></li>';
    return;
  }
  const metrics = calculateSlipMetrics(parlayLegs);
  list.innerHTML = parlayLegs.map((leg, index) => `<li class="slip-leg">
    <span class="leg-rank">${index + 1}</span>
    <div class="leg-details">
      <strong>${escapeHtml(leg.label)}</strong>
      <small>Model ${formatProbability(leg.probability)} | Odds ${formatOdds(leg.odds_value)}</small>
      <div class="impact-meter"><span style="width: ${impactWidth(metrics.legImpacts[index]?.edge ?? 0)}"></span></div>
      <small>${metrics.legImpacts[index]?.label || 'Impact pending'} | edge ${formatSignedPercent(metrics.legImpacts[index]?.edge ?? 0)} | drag ${formatSignedPercent(metrics.legImpacts[index]?.drag ?? 0)}</small>
    </div>
    <div class="leg-actions">
      <button class="link-button" data-up="${index}" type="button">Up</button>
      <button class="link-button" data-down="${index}" type="button">Down</button>
      <button class="link-button" data-remove="${index}" type="button">Remove</button>
    </div>
  </li>`).join('');
  list.querySelectorAll('[data-remove]').forEach((btn) => btn.addEventListener('click', () => { builtParlay = null; parlayLegs.splice(Number(btn.dataset.remove), 1); renderParlayLegs(); }));
  list.querySelectorAll('[data-up]').forEach((btn) => btn.addEventListener('click', () => { const i = Number(btn.dataset.up); if (i > 0) [parlayLegs[i - 1], parlayLegs[i]] = [parlayLegs[i], parlayLegs[i - 1]]; builtParlay = null; renderParlayLegs(); }));
  list.querySelectorAll('[data-down]').forEach((btn) => btn.addEventListener('click', () => { const i = Number(btn.dataset.down); if (i < parlayLegs.length - 1) [parlayLegs[i + 1], parlayLegs[i]] = [parlayLegs[i], parlayLegs[i + 1]]; builtParlay = null; renderParlayLegs(); }));
}

function optimizeSlip(mode) {
  builtParlay = null;
  if (mode === 'trap') {
    const metrics = calculateSlipMetrics(parlayLegs);
    parlayLegs.splice(metrics.weakestLegIndex, 1);
  } else {
    parlayLegs.sort((a, b) => {
      if (mode === 'safer') return clampProbability(b.probability) - clampProbability(a.probability);
      if (mode === 'upside') return decimalOdds(b.odds_value) - decimalOdds(a.odds_value);
      return edgeForLeg(b) - edgeForLeg(a);
    });
  }
  renderParlayLegs();
}

async function loadSavedParlays() {
  try {
    const parlays = await api('/api/parlays');
    const items = parlays.items || [];
    const saved = document.getElementById('saved-parlays');
    setText('saved-ticket-count', items.length);
    if (saved) saved.innerHTML = items.length
      ? `<ul class="ticket-timeline">${items.slice(0, 8).map((p, index) => `<li><span class="timeline-dot">${index + 1}</span><div><strong>${Math.round((p.win_probability || 0) * 100)}% win | ${escapeHtml(p.risk_tier || 'risk pending')}</strong><small>Odds ${p.estimated_odds ?? '-'} | Confidence ${escapeHtml(p.confidence_tier || 'pending')} | EV ${p.expected_value ?? 0}</small></div></li>`).join('')}</ul>`
      : '<p class="muted">No saved parlays yet.</p>';
  } catch (err) {
    const saved = document.getElementById('saved-parlays');
    if (saved) saved.innerHTML = `<p class="error">${escapeHtml(err.message)}</p>`;
  }
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

  await loadSavedParlays();
}



async function runRecentBackfill() {
  const limitEl = document.getElementById('recent-backfill-limit');
  const output = document.getElementById('recent-backfill-output');
  if (!output) return;
  const limit = limitEl && limitEl.value ? Number(limitEl.value) : null;
  const query = limit ? `?max_box_scores=${encodeURIComponent(limit)}` : '';
  output.textContent = 'Running 2020-2026 recent data scrape + import. This can take a long time for full seasons...';
  try {
    const data = await api(`/api/historical/backfill/recent${query}`, { method: 'POST' });
    output.textContent = JSON.stringify(data, null, 2);
    await loadDashboardData();
loadCavsPractice();
  } catch (err) {
    output.textContent = err.message;
  }
}

async function loadCavsPractice() {
  const panel = document.getElementById('cavs-practice-panel');
  if (!panel) return;
  try {
    const data = await api('/api/practice/cavs');
    panel.innerHTML = `<p class="metric">${data.games_available}</p><p class="muted">Cavs games available for practice</p><p class="muted">Completed games: ${data.completed_games}</p><p class="muted">Recent W-L: ${data.recent_wins}-${data.recent_losses}</p><p class="muted">Practice confidence: ${data.practice_confidence}%</p>`;
  } catch (err) {
    panel.innerHTML = `<p class="error">${err.message}</p>`;
  }
}

async function runHistoricalBackfill() {
  const seasonEl = document.getElementById('backfill-season');
  const limitEl = document.getElementById('backfill-limit');
  const output = document.getElementById('historical-backfill-output');
  if (!seasonEl || !output) return;
  const season = Number(seasonEl.value || 1996);
  const limit = limitEl && limitEl.value ? Number(limitEl.value) : null;
  if (!season || season < 1996 || season > 2026) {
    output.textContent = 'Enter a season from 1996 through 2026.';
    return;
  }
  const query = limit ? `?max_box_scores=${encodeURIComponent(limit)}` : '';
  output.textContent = `Running historical scrape + import for ${season}. This can take a while...`;
  try {
    const data = await api(`/api/historical/backfill/${season}${query}`, { method: 'POST' });
    output.textContent = JSON.stringify(data, null, 2);
    await loadDashboardData();
loadCavsPractice();
  } catch (err) {
    output.textContent = err.message;
  }
}

async function buildParlay() {
  const output = document.getElementById('parlay-output');
  if (!output) return;
  if (!parlayLegs.length) {
    output.innerHTML = '<p class="muted">Add at least one leg first.</p>';
    return;
  }
  output.innerHTML = '<p class="muted">Running predictor...</p>';
  try {
    const data = await api('/api/parlays/build', { method: 'POST', body: JSON.stringify({ name: 'Dashboard Parlay', legs: parlayLegs }) });
    builtParlay = data.parlay;
    renderSlipMetrics();
    output.innerHTML = `<span>Odds <strong>${builtParlay.estimated_odds ?? '-'}</strong></span>
      <span>Win <strong>${Math.round((builtParlay.win_probability || 0) * 100)}%</strong></span>
      <span>Loss <strong>${Math.round((builtParlay.loss_probability || 0) * 100)}%</strong></span>
      <span>EV <strong>${builtParlay.expected_value ?? 0}</strong></span>
      <span>Risk <strong>${escapeHtml(builtParlay.risk_tier || 'pending')}</strong></span>
      <span>Confidence <strong>${escapeHtml(builtParlay.confidence_tier || 'pending')}</strong></span>`;
    await loadSavedParlays();
  } catch (err) {
    output.innerHTML = `<p class="error">${escapeHtml(err.message)}</p>`;
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
document.getElementById('run-historical-backfill')?.addEventListener('click', runHistoricalBackfill);
document.getElementById('run-recent-backfill')?.addEventListener('click', runRecentBackfill);
document.getElementById('sidebar-toggle')?.addEventListener('click', () => document.querySelector('.app-shell')?.classList.toggle('sidebar-collapsed'));
document.querySelectorAll('[data-optimize]').forEach((button) => button.addEventListener('click', () => optimizeSlip(button.dataset.optimize)));
renderParlayLegs();
loadDashboardData();
loadCavsPractice();
