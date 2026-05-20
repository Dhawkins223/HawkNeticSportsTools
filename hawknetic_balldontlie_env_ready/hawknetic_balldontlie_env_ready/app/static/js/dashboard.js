const slipLegs = [];
let games = [];
let props = [];
let odds = [];
let activeGameId = null;
let activeMarketTab = 'Popular';

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options
  });
  const data = await response.json().catch(() => ({ detail: 'Request failed.' }));
  if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
  return data;
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
  if (value === undefined || value === null) return 'No odds';
  return Number(value) > 0 ? `+${value}` : String(value);
}

function americanToDecimal(oddsValue) {
  const oddsNumber = Number(oddsValue);
  return oddsNumber > 0 ? 1 + oddsNumber / 100 : 1 + 100 / Math.abs(oddsNumber);
}

function payoutPreview() {
  const stake = Number(document.getElementById('stake')?.value || 0);
  if (!stake || !slipLegs.length) return 0;
  const decimal = slipLegs.reduce((product, leg) => product * americanToDecimal(leg.oddsAmerican), 1);
  return stake * decimal;
}

function marketTypeFromLabel(label = '') {
  const text = String(label).toLowerCase();
  if (text.includes('moneyline')) return 'moneyline';
  if (text.includes('spread')) return 'spread';
  if (text.includes('total') || text.includes('over') || text.includes('under')) return 'total';
  if (text.includes('team')) return 'team_prop';
  return 'player_prop';
}

function eventLabelForGame(game) {
  if (!game) return 'Event data unavailable';
  return `${game.visitor_team_name || game.visitor_team_abbr || 'Away'} @ ${game.home_team_name || game.home_team_abbr || 'Home'}`;
}

function buildMarketOptions() {
  const gameMap = new Map(games.map((game) => [String(game.id), game]));
  const propOptions = props.flatMap((prop) => {
    const gameId = String(prop.game_id || 'manual');
    const game = gameMap.get(gameId);
    const base = {
      eventLabel: eventLabelForGame(game),
      gameId,
      startsAt: game?.game_date,
      marketType: marketTypeFromLabel(prop.market || prop.selection),
      line: prop.line ?? null,
      source: 'props'
    };
    const label = `${prop.market || prop.selection || 'Prop'} ${prop.line ?? ''}`.trim();
    return [
      { ...base, id: `prop-${prop.id || label}-over`, label, oddsAmerican: prop.over_odds ?? null },
      { ...base, id: `prop-${prop.id || label}-under`, label: label.toLowerCase().includes('under') ? label : `${label} under`, oddsAmerican: prop.under_odds ?? null }
    ].filter((option) => option.oddsAmerican !== null || (prop.over_odds === undefined && prop.under_odds === undefined));
  });
  const oddsOptions = odds.map((row, index) => {
    const gameId = String(row.game_id || 'manual');
    return {
      id: `odds-${row.id || index}`,
      label: String(row.selection || row.market || 'Market'),
      line: null,
      oddsAmerican: typeof row.odds_value === 'number' ? row.odds_value : null,
      marketType: marketTypeFromLabel(row.market || ''),
      eventLabel: eventLabelForGame(gameMap.get(gameId)),
      gameId,
      source: 'odds'
    };
  });
  return [...propOptions, ...oddsOptions];
}

function renderGames() {
  const list = document.getElementById('game-list');
  if (!list) return;
  if (!games.length) {
    list.innerHTML = '<p>Not enough data available yet. You can still add a Bet365 slip manually.</p>';
    return;
  }
  list.innerHTML = games.slice(0, 18).map((game) => `
    <button type="button" class="${activeGameId === String(game.id) ? 'active' : ''}" data-game-id="${game.id}">
      <strong>${escapeHtml(eventLabelForGame(game))}</strong>
      <span>${escapeHtml(game.game_date || 'Start time pending')}</span>
      <small>${escapeHtml(game.status || 'Market status pending')}</small>
    </button>
  `).join('');
  list.querySelectorAll('[data-game-id]').forEach((button) => {
    button.addEventListener('click', () => {
      activeGameId = button.dataset.gameId;
      renderGames();
      renderMarkets();
    });
  });
}

function tabMatches(option) {
  if (activeMarketTab === 'Popular') return true;
  if (activeMarketTab === 'Player Props') return option.marketType === 'player_prop';
  if (activeMarketTab === 'Moneyline') return option.marketType === 'moneyline';
  if (activeMarketTab === 'Spread') return option.marketType === 'spread';
  if (activeMarketTab === 'Total') return option.marketType === 'total';
  return activeMarketTab === 'Same Game';
}

function renderMarkets() {
  const rows = document.getElementById('market-rows');
  if (!rows) return;
  const options = buildMarketOptions().filter((option) => {
    const gameMatches = !activeGameId || activeGameId === 'manual' || option.gameId === activeGameId;
    return gameMatches && tabMatches(option);
  });
  if (!options.length) {
    rows.innerHTML = '<div class="public-empty-market">Not enough data available yet. Enter your Bet365 slip manually and HawkNetic will analyze what it can.</div>';
    return;
  }
  rows.innerHTML = options.map((option, index) => `
    <article class="public-market-row">
      <div><strong>${escapeHtml(option.eventLabel)}</strong><span>${escapeHtml(option.marketType.replaceAll('_', ' '))}</span></div>
      <button type="button" class="public-odds-button" data-option-index="${index}" ${option.oddsAmerican === null ? 'disabled' : ''}>
        <span>${escapeHtml(option.label)}</span>
        ${option.line !== null && option.line !== undefined ? `<small>Line ${escapeHtml(option.line)}</small>` : ''}
        <strong>${option.oddsAmerican === null ? 'No odds available' : formatOdds(option.oddsAmerican)}</strong>
      </button>
    </article>
  `).join('');
  rows.querySelectorAll('[data-option-index]').forEach((button) => {
    button.addEventListener('click', () => addMarketOption(options[Number(button.dataset.optionIndex)]));
  });
}

function addMarketOption(option) {
  if (!option || option.oddsAmerican === null) return;
  slipLegs.push({
    id: `${option.id}-${Date.now()}`,
    sport: 'NBA',
    bookmaker: document.getElementById('bookmaker')?.value || 'bet365',
    gameId: option.gameId,
    eventLabel: option.eventLabel,
    startsAt: option.startsAt,
    marketType: option.marketType,
    selection: option.label,
    line: option.line,
    oddsAmerican: Number(option.oddsAmerican),
    notes: option.source === 'props' ? option.id : null
  });
  renderSlip();
}

function renderSlip() {
  const container = document.getElementById('slip-legs');
  const count = document.getElementById('slip-count');
  const toggle = document.getElementById('mobile-slip-toggle');
  const runButton = document.getElementById('run-algorithm');
  const payout = document.getElementById('payout-preview');
  if (count) count.textContent = String(slipLegs.length);
  if (toggle) toggle.textContent = `Slip (${slipLegs.length}) · Analyze`;
  if (runButton) runButton.disabled = !slipLegs.length;
  if (payout) payout.textContent = `$${payoutPreview().toFixed(2)}`;
  if (!container) return;
  if (!slipLegs.length) {
    container.innerHTML = '<div class="public-empty-slip">Click odds or add a manual leg. This does not place bets.</div>';
    return;
  }
  container.innerHTML = slipLegs.map((leg, index) => `
    <article class="public-slip-leg">
      <button class="public-drag-handle" type="button" aria-label="Move leg">::</button>
      <div>
        <strong>${escapeHtml(leg.selection)}</strong>
        <p>${escapeHtml(leg.eventLabel)}</p>
        <small>${escapeHtml(leg.marketType.replaceAll('_', ' '))} ${leg.line ?? ''} · ${formatOdds(leg.oddsAmerican)}</small>
      </div>
      <div class="public-leg-controls">
        <button type="button" data-move-up="${index}" ${index === 0 ? 'disabled' : ''}>Up</button>
        <button type="button" data-move-down="${index}" ${index === slipLegs.length - 1 ? 'disabled' : ''}>Down</button>
        <button type="button" data-remove-leg="${index}">Remove</button>
      </div>
    </article>
  `).join('');
  container.querySelectorAll('[data-remove-leg]').forEach((button) => button.addEventListener('click', () => {
    slipLegs.splice(Number(button.dataset.removeLeg), 1);
    renderSlip();
  }));
  container.querySelectorAll('[data-move-up]').forEach((button) => button.addEventListener('click', () => {
    const index = Number(button.dataset.moveUp);
    if (index > 0) [slipLegs[index - 1], slipLegs[index]] = [slipLegs[index], slipLegs[index - 1]];
    renderSlip();
  }));
  container.querySelectorAll('[data-move-down]').forEach((button) => button.addEventListener('click', () => {
    const index = Number(button.dataset.moveDown);
    if (index < slipLegs.length - 1) [slipLegs[index + 1], slipLegs[index]] = [slipLegs[index], slipLegs[index + 1]];
    renderSlip();
  }));
}

function addManualLeg() {
  const eventLabel = document.getElementById('manual-event')?.value.trim();
  const marketType = document.getElementById('manual-market')?.value || 'player_prop';
  const selection = document.getElementById('manual-selection')?.value.trim();
  const lineValue = document.getElementById('manual-line')?.value.trim();
  const oddsValue = Number(document.getElementById('manual-odds')?.value);
  if (!eventLabel || !selection || !Number.isFinite(oddsValue) || oddsValue === 0) return;
  slipLegs.push({
    id: `manual-${Date.now()}`,
    sport: 'NBA',
    bookmaker: document.getElementById('bookmaker')?.value || 'bet365',
    gameId: `manual-${eventLabel.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`,
    eventLabel,
    marketType,
    selection,
    line: lineValue ? Number(lineValue) : null,
    oddsAmerican: oddsValue,
    notes: 'Manual Bet365 entry'
  });
  ['manual-event', 'manual-selection', 'manual-line', 'manual-odds'].forEach((id) => { const input = document.getElementById(id); if (input) input.value = ''; });
  renderSlip();
}

function renderAnalysis(result) {
  const panel = document.getElementById('analysis-panel');
  if (!panel) return;
  panel.hidden = false;
  panel.className = `public-analysis-panel ${String(result.recommendation || '').toLowerCase()}`;
  panel.innerHTML = `
    <p>HawkNetic recommendation</p>
    <h3>${escapeHtml(String(result.recommendation || '').replaceAll('_', ' '))}</h3>
    <strong>${escapeHtml(result.summary || '')}</strong>
    <div class="public-analysis-metrics">
      <span>Model win <b>${result.modelWinProbability === null ? 'Insufficient data' : `${Math.round(result.modelWinProbability * 100)}%`}</b></span>
      <span>Market implied <b>${result.impliedProbability === null ? '-' : `${Math.round(result.impliedProbability * 100)}%`}</b></span>
      <span>Edge <b>${result.edgePct === null ? '-' : `${Number(result.edgePct).toFixed(1)}%`}</b></span>
      <span>Expected value <b>${result.expectedValue === null ? '-' : `$${Number(result.expectedValue).toFixed(2)}`}</b></span>
      <span>Fair odds <b>${result.fairAmericanOdds ?? '-'}</b></span>
      <span>Confidence <b>${escapeHtml(result.confidenceTier || '-')}</b></span>
    </div>
    ${result.warnings?.length ? `<div class="public-warning-list"><b>Trap warnings</b>${result.warnings.map((warning) => `<span>${escapeHtml(warning)}</span>`).join('')}</div>` : ''}
    <div class="public-leg-analysis">${(result.legAnalyses || []).map((leg) => `<article><strong>${escapeHtml(leg.selection)} · ${escapeHtml(leg.verdict)}</strong><p>${escapeHtml(leg.explanation)}</p>${(leg.warnings || []).map((warning) => `<small>${escapeHtml(warning)}</small>`).join('')}</article>`).join('')}</div>
    ${result.betterAlternatives?.length ? `<div class="public-alternatives"><b>Better alternatives</b>${result.betterAlternatives.map((item) => `<span>${escapeHtml(item.title)}: ${escapeHtml(item.reason)}</span>`).join('')}</div>` : ''}
  `;
}

async function runAlgorithm() {
  if (!slipLegs.length) return;
  const button = document.getElementById('run-algorithm');
  if (button) button.textContent = 'Running algorithm...';
  try {
    const result = await api('/api/slips/analyze', {
      method: 'POST',
      body: JSON.stringify({
        bookmaker: document.getElementById('bookmaker')?.value || 'bet365',
        stake: Number(document.getElementById('stake')?.value || 0),
        legs: slipLegs
      })
    });
    renderAnalysis(result);
  } catch (_err) {
    renderAnalysis({
      recommendation: 'INSUFFICIENT_DATA',
      summary: 'Not enough data to evaluate this slip yet.',
      modelWinProbability: null,
      impliedProbability: null,
      edgePct: null,
      expectedValue: null,
      fairAmericanOdds: null,
      confidenceTier: 'INSUFFICIENT_DATA',
      warnings: ['Slip analysis is temporarily unavailable.'],
      legAnalyses: [],
      betterAlternatives: []
    });
  } finally {
    if (button) button.textContent = 'Run Algorithm';
  }
}

async function loadDashboard() {
  if (!document.querySelector('[data-dashboard-api]')) return;
  try {
    const [gameData, propData, oddsData] = await Promise.all([api('/api/games'), api('/api/props'), api('/api/odds')]);
    games = gameData.items || [];
    props = propData.items || [];
    odds = oddsData.items || [];
    activeGameId = String(games[0]?.id || props[0]?.game_id || 'manual');
  } catch (_err) {
    const error = document.getElementById('market-error');
    if (error) {
      error.hidden = false;
      error.textContent = 'Markets are temporarily unavailable. You can still add a Bet365 slip manually.';
    }
  } finally {
    const loading = document.getElementById('market-loading');
    if (loading) loading.hidden = true;
    renderGames();
    renderMarkets();
    renderSlip();
  }
}

document.querySelectorAll('[data-market-tab]').forEach((button) => {
  button.addEventListener('click', () => {
    activeMarketTab = button.dataset.marketTab || 'Popular';
    document.querySelectorAll('[data-market-tab]').forEach((item) => item.classList.toggle('active', item === button));
    renderMarkets();
  });
});
document.getElementById('add-manual-leg')?.addEventListener('click', addManualLeg);
document.getElementById('stake')?.addEventListener('input', renderSlip);
document.getElementById('run-algorithm')?.addEventListener('click', runAlgorithm);
document.getElementById('mobile-slip-toggle')?.addEventListener('click', () => document.getElementById('slip-panel')?.classList.toggle('mobile-open'));
loadDashboard();
