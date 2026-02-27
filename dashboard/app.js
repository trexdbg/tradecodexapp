const DATA_URL = "./data/dashboard-data.json";
const FALLBACK_URL = "./data/sample-dashboard-data.json";
const SCORE_COLORS = {
  BTC: "#4ecdc4",
  ETH: "#f4d35e",
  SOL: "#ff8a5b",
  BNB: "#7aa2f7",
  XRP: "#f07178",
};

const currency = new Intl.NumberFormat("fr-FR", {
  style: "currency",
  currency: "EUR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const state = {
  data: emptyPayload(),
  agentFilter: "ALL",
  assetFilter: "ALL",
  selectedAgentId: null,
};

document.addEventListener("DOMContentLoaded", async () => {
  state.data = await loadDashboardData();
  ensureSelectedAgent();
  bootstrapFilters();
  renderDashboard();
});

async function loadDashboardData() {
  for (const url of [DATA_URL, FALLBACK_URL]) {
    try {
      const response = await fetch(url, { cache: "no-store" });
      if (!response.ok) {
        continue;
      }
      return await response.json();
    } catch (_error) {
      continue;
    }
  }
  return emptyPayload();
}

function bootstrapFilters() {
  const agentSelect = document.querySelector("#agentFilter");
  const assetSelect = document.querySelector("#assetFilter");
  if (!agentSelect || !assetSelect) {
    return;
  }

  const agents = state.data.agents || [];
  const assets = state.data.system?.supported_assets || [];
  fillSelect(agentSelect, ["ALL", ...agents.map((agent) => agent.id)]);
  fillSelect(assetSelect, ["ALL", ...assets]);

  agentSelect.addEventListener("change", (event) => {
    state.agentFilter = event.target.value;
    renderTables();
  });

  assetSelect.addEventListener("change", (event) => {
    state.assetFilter = event.target.value;
    renderTables();
  });
}

function fillSelect(select, values) {
  select.innerHTML = "";
  values.forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value === "ALL" ? "Tous" : value;
    select.appendChild(option);
  });
}

function renderDashboard() {
  ensureSelectedAgent();
  renderHeader();
  renderKpis();
  renderMarketTiles();
  renderAgents();
  renderAgentDetail();
  renderScoreChart();
  renderTables();
  renderEvents();
}

function renderHeader() {
  const systemName = document.querySelector("#systemName");
  const modeLabel = document.querySelector("#modeLabel");
  const generatedAt = document.querySelector("#generatedAt");
  if (!systemName || !modeLabel || !generatedAt) {
    return;
  }

  systemName.textContent = `${state.data.system?.name || "cryptoMaster"} Intelligence Board`;
  modeLabel.textContent = String(state.data.system?.mode || "dry_run").replace("_", " ");
  generatedAt.textContent = `Mise a jour: ${formatDateTime(state.data.generated_at)}`;
}

function renderKpis() {
  const topAgent = getTopPerformerAgent();
  const topPerfNode = document.querySelector("#kpiTopPerf");
  const topGainLossNode = document.querySelector("#kpiTopGainLoss");

  if (!topAgent) {
    setText("#kpiTopAgent", "-");
    setText("#kpiTopPerf", "-");
    setText("#kpiTopWinLose", "-");
    setText("#kpiTopGainLoss", "-");
    if (topPerfNode) {
      topPerfNode.classList.remove("positive", "negative");
    }
    if (topGainLossNode) {
      topGainLossNode.classList.remove("positive", "negative");
    }
    return;
  }

  const analytics = computeAgentAnalytics(topAgent.id);
  const topPnl = Number(topAgent.pnl_abs || 0);
  setText("#kpiTopAgent", `${topAgent.name} (${topAgent.id})`);
  if (topPerfNode) {
    topPerfNode.textContent = `${formatMoney(topPnl)} (${formatPercent(topAgent.pnl_pct)})`;
    topPerfNode.classList.toggle("positive", topPnl >= 0);
    topPerfNode.classList.toggle("negative", topPnl < 0);
  }

  setText(
    "#kpiTopWinLose",
    `${formatRate(analytics.stats.winRate)} / ${formatRate(analytics.stats.loseRate)}`
  );

  if (topGainLossNode) {
    topGainLossNode.textContent = `${formatMoney(analytics.stats.gainsEur)} / ${formatMoney(
      -analytics.stats.lossesEur
    )}`;
    topGainLossNode.classList.toggle("positive", analytics.stats.netRealizedEur >= 0);
    topGainLossNode.classList.toggle("negative", analytics.stats.netRealizedEur < 0);
  }
}

function renderMarketTiles() {
  const marketGrid = document.querySelector("#marketGrid");
  if (!marketGrid) {
    return;
  }
  marketGrid.innerHTML = "";
  const entries = state.data.market || [];
  if (!entries.length) {
    marketGrid.innerHTML = `<p class="no-data">Aucune donnee marche.</p>`;
    return;
  }

  entries.forEach((item) => {
    const delta = Number(item.price_change_pct_24h || 0);
    const tile = document.createElement("article");
    tile.className = "market-tile";
    tile.innerHTML = `
      <p class="asset">${escapeHtml(item.asset)}</p>
      <p class="price">${formatMoney(item.last_price)}</p>
      <p class="delta ${delta >= 0 ? "positive" : "negative"}">${formatPercent(delta / 100)}</p>
    `;
    marketGrid.appendChild(tile);
  });
}

function renderAgents() {
  const agentsGrid = document.querySelector("#agentsGrid");
  if (!agentsGrid) {
    return;
  }
  agentsGrid.innerHTML = "";

  const agents = getAgentsSortedByPerformance();
  if (!agents.length) {
    agentsGrid.innerHTML = `<p class="no-data">Aucun agent initialise.</p>`;
    return;
  }

  agents.forEach((agent) => {
    const analytics = computeAgentAnalytics(agent.id);
    const pnl = Number(agent.pnl_abs || 0);
    const toneClass = pnl > 0 ? "positive-card" : pnl < 0 ? "negative-card" : "neutral-card";
    const selectedClass = state.selectedAgentId === agent.id ? "selected" : "";
    const card = document.createElement("button");
    card.type = "button";
    card.className = `agent-card ${toneClass} ${selectedClass}`.trim();
    card.setAttribute("aria-pressed", state.selectedAgentId === agent.id ? "true" : "false");
    card.innerHTML = `
      <div class="agent-row">
        <p class="agent-name">${escapeHtml(agent.name)} <span class="muted">(${escapeHtml(agent.id)})</span></p>
        <p class="agent-risk">${escapeHtml(agent.risk_profile)}</p>
      </div>
      <div class="agent-metrics">
        <p>Perf<strong class="${pnl >= 0 ? "positive" : "negative"}">${formatMoney(pnl)} (${formatPercent(
      agent.pnl_pct
    )})</strong></p>
        <p>Win rate<strong>${formatRate(analytics.stats.winRate)}</strong></p>
        <p>Trades gagnes<strong>${analytics.stats.wins}</strong></p>
      </div>
    `;
    card.addEventListener("click", () => {
      state.selectedAgentId = agent.id;
      renderAgents();
      renderAgentDetail();
    });
    agentsGrid.appendChild(card);
  });
}

function renderAgentDetail() {
  const detailTitle = document.querySelector("#agentDetailTitle");
  const detailMeta = document.querySelector("#agentDetailMeta");
  const detailSummary = document.querySelector("#agentDetailSummary");
  if (!detailTitle || !detailMeta || !detailSummary) {
    return;
  }

  const selectedAgent = (state.data.agents || []).find((agent) => agent.id === state.selectedAgentId);
  if (!selectedAgent) {
    detailTitle.textContent = "Focus Agent";
    detailMeta.textContent = "Clique sur un agent pour ouvrir le detail.";
    detailSummary.innerHTML = `<p class="no-data">Aucun agent selectionne.</p>`;
    renderOpenTradesTable([]);
    renderHistoryTradesTable([]);
    return;
  }

  const analytics = computeAgentAnalytics(selectedAgent.id);
  const pnl = Number(selectedAgent.pnl_abs || 0);
  const assets = (selectedAgent.assets || []).join(", ") || "-";
  const timeframes = (selectedAgent.timeframes || []).join(", ") || "-";

  detailTitle.textContent = `${selectedAgent.name} (${selectedAgent.id})`;
  detailMeta.textContent = `${selectedAgent.risk_profile.toUpperCase()} | Assets: ${assets} | TF: ${timeframes}`;
  detailSummary.innerHTML = `
    <article class="detail-stat">
      <p>PnL total</p>
      <strong class="${pnl >= 0 ? "positive" : "negative"}">${formatMoney(pnl)} (${formatPercent(
    selectedAgent.pnl_pct
  )})</strong>
    </article>
    <article class="detail-stat">
      <p>Trades clotures</p>
      <strong>${analytics.stats.closedCount}</strong>
    </article>
    <article class="detail-stat">
      <p>Win rate</p>
      <strong class="positive">${formatRate(analytics.stats.winRate)}</strong>
    </article>
    <article class="detail-stat">
      <p>Lose rate</p>
      <strong class="negative">${formatRate(analytics.stats.loseRate)}</strong>
    </article>
    <article class="detail-stat">
      <p>Gains realises</p>
      <strong class="positive">${formatMoney(analytics.stats.gainsEur)}</strong>
    </article>
    <article class="detail-stat">
      <p>Pertes realisees</p>
      <strong class="negative">${formatMoney(-analytics.stats.lossesEur)}</strong>
    </article>
    <article class="detail-stat">
      <p>PnL realise net</p>
      <strong class="${analytics.stats.netRealizedEur >= 0 ? "positive" : "negative"}">${formatMoney(
    analytics.stats.netRealizedEur
  )}</strong>
    </article>
  `;

  renderOpenTradesTable(analytics.openTrades);
  renderHistoryTradesTable(analytics.closedTrades);
}

function renderOpenTradesTable(openTrades) {
  const body = document.querySelector("#openTradesBody");
  if (!body) {
    return;
  }
  body.innerHTML = "";

  if (!openTrades.length) {
    body.innerHTML = `<tr><td colspan="6" class="no-data">Aucun trade actif.</td></tr>`;
    return;
  }

  openTrades.forEach((position) => {
    const unrealized = Number(position.unrealized_pnl_eur || 0);
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(position.asset)}</td>
      <td>${formatQuantity(position.quantity)}</td>
      <td>${formatMoney(position.avg_price)}</td>
      <td>${formatMoney(position.market_price)}</td>
      <td>${formatMoney(position.market_value_eur)}</td>
      <td class="${unrealized >= 0 ? "positive" : "negative"}">${formatMoney(unrealized)}</td>
    `;
    body.appendChild(tr);
  });
}

function renderHistoryTradesTable(closedTrades) {
  const body = document.querySelector("#historyTradesBody");
  if (!body) {
    return;
  }
  body.innerHTML = "";

  if (!closedTrades.length) {
    body.innerHTML = `<tr><td colspan="6" class="no-data">Aucun trade cloture dans l'historique exporte.</td></tr>`;
    return;
  }

  closedTrades.slice(0, 120).forEach((trade) => {
    const pnl = Number(trade.pnl_eur || 0);
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${formatDateTime(trade.exit_at)}</td>
      <td>${escapeHtml(trade.asset)}</td>
      <td>${formatQuantity(trade.quantity)}</td>
      <td>${formatMoney(trade.entry_price)}</td>
      <td>${formatMoney(trade.exit_price)}</td>
      <td class="${pnl >= 0 ? "positive" : "negative"}">${formatMoney(pnl)}</td>
    `;
    body.appendChild(tr);
  });
}

function renderTables() {
  renderTradesTable();
  renderDecisionsTable();
}

function renderTradesTable() {
  const body = document.querySelector("#tradesBody");
  if (!body) {
    return;
  }
  body.innerHTML = "";

  const trades = filterRows(state.data.recent_trades || []);
  if (!trades.length) {
    body.innerHTML = `<tr><td colspan="7" class="no-data">Aucun trade pour ce filtre.</td></tr>`;
    return;
  }

  trades.slice(0, 80).forEach((trade) => {
    const tr = document.createElement("tr");
    const sideClass = trade.side === "BUY" ? "positive" : "negative";
    tr.innerHTML = `
      <td>${formatDateTime(trade.created_at)}</td>
      <td>${escapeHtml(trade.agent_id)}</td>
      <td>${escapeHtml(trade.asset)}</td>
      <td class="${sideClass}">${escapeHtml(trade.side)}</td>
      <td>${formatMoney(trade.notional_eur)}</td>
      <td>${formatMoney(trade.price)}</td>
      <td>${formatMoney(trade.fee_eur)}</td>
    `;
    body.appendChild(tr);
  });
}

function renderDecisionsTable() {
  const body = document.querySelector("#decisionsBody");
  const meta = document.querySelector("#decisionMeta");
  if (!body || !meta) {
    return;
  }
  body.innerHTML = "";

  const decisions = filterRows(state.data.recent_decisions || []);
  meta.textContent = `${decisions.length} decisions filtrees`;
  if (!decisions.length) {
    body.innerHTML = `<tr><td colspan="7" class="no-data">Aucune decision pour ce filtre.</td></tr>`;
    return;
  }

  decisions.slice(0, 100).forEach((decision) => {
    const score = Number(decision.score || 0);
    const strategies = Object.entries(decision.rationale?.strategy_scores || {})
      .filter(([, value]) => Math.abs(Number(value || 0)) > 0.01)
      .map(([name]) => name)
      .join(", ");
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${formatDateTime(decision.created_at)}</td>
      <td>${escapeHtml(decision.agent_id)}</td>
      <td>${escapeHtml(decision.asset)}</td>
      <td>${escapeHtml(decision.regime)}</td>
      <td>${escapeHtml(decision.action)}</td>
      <td><span class="score-pill ${score >= 0 ? "positive" : "negative"}">${score.toFixed(3)}</span></td>
      <td>${escapeHtml(strategies || "-")}</td>
    `;
    body.appendChild(tr);
  });
}

function renderEvents() {
  const eventsList = document.querySelector("#eventsList");
  if (!eventsList) {
    return;
  }
  eventsList.innerHTML = "";

  const events = state.data.recent_events || [];
  if (!events.length) {
    eventsList.innerHTML = `<li class="event-item"><p class="no-data">Aucun event enregistre.</p></li>`;
    return;
  }

  events.slice(0, 40).forEach((event) => {
    const entry = document.createElement("li");
    entry.className = "event-item";
    entry.innerHTML = `
      <p class="event-type">${escapeHtml(event.event_type)}</p>
      <p>${escapeHtml(formatDateTime(event.created_at))}</p>
    `;
    eventsList.appendChild(entry);
  });
}

function renderScoreChart() {
  const chart = document.querySelector("#scoreChart");
  const legend = document.querySelector("#chartLegend");
  if (!chart || !legend) {
    return;
  }

  chart.innerHTML = "";
  legend.innerHTML = "";
  const width = 1000;
  const height = 280;
  const padding = 28;
  const mid = height / 2;
  const seriesByAsset = state.data.score_series || {};
  const assets = state.data.system?.supported_assets || [];

  const activeAssets = assets.filter((asset) => (seriesByAsset[asset] || []).length > 1);
  if (!activeAssets.length) {
    chart.innerHTML = `<text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" fill="#86a2b4" font-size="15">Pas assez de signaux pour tracer une courbe</text>`;
    return;
  }

  for (let i = 0; i < 5; i += 1) {
    const y = padding + ((height - padding * 2) / 4) * i;
    chart.insertAdjacentHTML(
      "beforeend",
      `<line x1="0" y1="${y}" x2="${width}" y2="${y}" stroke="rgba(85,160,194,0.2)" stroke-width="1" />`
    );
  }
  chart.insertAdjacentHTML(
    "beforeend",
    `<line x1="0" y1="${mid}" x2="${width}" y2="${mid}" stroke="rgba(25,180,214,0.45)" stroke-width="1.5" />`
  );

  activeAssets.forEach((asset) => {
    const points = seriesByAsset[asset];
    const xStep = (width - padding * 2) / Math.max(1, points.length - 1);
    const path = points
      .map((point, index) => {
        const x = padding + xStep * index;
        const y = mid - Number(point.score || 0) * (mid - padding) * 0.92;
        return `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
      })
      .join(" ");
    const color = SCORE_COLORS[asset] || "#19b4d6";
    chart.insertAdjacentHTML(
      "beforeend",
      `<path d="${path}" fill="none" stroke="${color}" stroke-width="2.2" stroke-linecap="round" />`
    );

    const legendItem = document.createElement("span");
    legendItem.className = "legend-item";
    legendItem.innerHTML = `<span class="legend-swatch" style="background:${color}"></span>${escapeHtml(asset)}`;
    legend.appendChild(legendItem);
  });
}

function filterRows(rows) {
  return rows.filter((row) => {
    const agentOk = state.agentFilter === "ALL" || row.agent_id === state.agentFilter;
    const assetOk = state.assetFilter === "ALL" || row.asset === state.assetFilter;
    return agentOk && assetOk;
  });
}

function computeAgentAnalytics(agentId) {
  const agent = (state.data.agents || []).find((row) => row.id === agentId);
  const trades = (state.data.recent_trades || [])
    .filter((trade) => trade.agent_id === agentId)
    .sort((a, b) => toTimestamp(a.created_at) - toTimestamp(b.created_at));

  const closedTrades = buildClosedTrades(trades).sort(
    (a, b) => toTimestamp(b.exit_at) - toTimestamp(a.exit_at)
  );
  const openTrades = [...(agent?.positions || [])]
    .map((position) => {
      const quantity = Number(position.quantity || 0);
      const avgPrice = Number(position.avg_price || 0);
      const marketPrice = Number(position.market_price || 0);
      return {
        ...position,
        unrealized_pnl_eur: (marketPrice - avgPrice) * quantity,
      };
    })
    .sort((a, b) => Number(b.market_value_eur || 0) - Number(a.market_value_eur || 0));

  const wins = closedTrades.filter((trade) => Number(trade.pnl_eur || 0) > 0).length;
  const losses = closedTrades.filter((trade) => Number(trade.pnl_eur || 0) < 0).length;
  const closedCount = wins + losses;
  const gainsEur = closedTrades.reduce((sum, trade) => {
    const pnl = Number(trade.pnl_eur || 0);
    return pnl > 0 ? sum + pnl : sum;
  }, 0);
  const lossesEur = closedTrades.reduce((sum, trade) => {
    const pnl = Number(trade.pnl_eur || 0);
    return pnl < 0 ? sum + Math.abs(pnl) : sum;
  }, 0);
  const netRealizedEur = gainsEur - lossesEur;

  return {
    openTrades,
    closedTrades,
    stats: {
      wins,
      losses,
      closedCount,
      winRate: closedCount ? wins / closedCount : 0,
      loseRate: closedCount ? losses / closedCount : 0,
      gainsEur,
      lossesEur,
      netRealizedEur,
    },
  };
}

function buildClosedTrades(trades) {
  const lotsByAsset = new Map();
  const closedTrades = [];
  const eps = 1e-10;

  trades.forEach((trade) => {
    const asset = String(trade.asset || "").toUpperCase();
    const side = String(trade.side || "").toUpperCase();
    const quantity = Number(trade.quantity || 0);
    const price = Number(trade.price || 0);
    const feeEur = Number(trade.fee_eur || 0);

    if (!asset || quantity <= 0 || price <= 0) {
      return;
    }

    if (!lotsByAsset.has(asset)) {
      lotsByAsset.set(asset, []);
    }

    const lots = lotsByAsset.get(asset);
    if (side === "BUY") {
      lots.push({
        remaining: quantity,
        entryPrice: price,
        entryAt: trade.created_at,
        entryFeePerUnit: feeEur / quantity,
      });
      return;
    }

    if (side !== "SELL") {
      return;
    }

    let remainingToClose = quantity;
    const exitFeePerUnit = feeEur / quantity;
    while (remainingToClose > eps && lots.length) {
      const lot = lots[0];
      const matchedQty = Math.min(lot.remaining, remainingToClose);
      const entryFee = matchedQty * lot.entryFeePerUnit;
      const exitFee = matchedQty * exitFeePerUnit;
      const pnlEur = (price - lot.entryPrice) * matchedQty - entryFee - exitFee;

      closedTrades.push({
        asset,
        quantity: matchedQty,
        entry_price: lot.entryPrice,
        exit_price: price,
        entry_at: lot.entryAt,
        exit_at: trade.created_at,
        pnl_eur: pnlEur,
      });

      lot.remaining -= matchedQty;
      remainingToClose -= matchedQty;
      if (lot.remaining <= eps) {
        lots.shift();
      }
    }
  });

  return closedTrades;
}

function ensureSelectedAgent() {
  const agents = state.data.agents || [];
  if (!agents.length) {
    state.selectedAgentId = null;
    return;
  }
  if (agents.some((agent) => agent.id === state.selectedAgentId)) {
    return;
  }
  const topAgent = getTopPerformerAgent();
  state.selectedAgentId = topAgent ? topAgent.id : agents[0].id;
}

function getTopPerformerAgent() {
  const rankedAgents = getAgentsSortedByPerformance();
  return rankedAgents.length ? rankedAgents[0] : null;
}

function getAgentsSortedByPerformance() {
  return [...(state.data.agents || [])].sort(compareAgentPerformance);
}

function compareAgentPerformance(a, b) {
  const pctDiff = Number(b.pnl_pct || 0) - Number(a.pnl_pct || 0);
  if (Math.abs(pctDiff) > 1e-9) {
    return pctDiff;
  }
  const absDiff = Number(b.pnl_abs || 0) - Number(a.pnl_abs || 0);
  if (Math.abs(absDiff) > 1e-9) {
    return absDiff;
  }
  return Number(b.equity || 0) - Number(a.equity || 0);
}

function formatMoney(value) {
  return currency.format(Number(value || 0));
}

function formatPercent(value) {
  const number = Number(value || 0) * 100;
  const sign = number >= 0 ? "+" : "";
  return `${sign}${number.toFixed(2)}%`;
}

function formatRate(value) {
  const number = Number(value || 0) * 100;
  return `${number.toFixed(1)}%`;
}

function formatQuantity(value) {
  return Number(value || 0).toLocaleString("fr-FR", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 8,
  });
}

function formatDateTime(value) {
  if (!value) {
    return "-";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return String(value);
  }
  return parsed.toLocaleString("fr-FR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function toTimestamp(value) {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? 0 : parsed.getTime();
}

function setText(selector, text) {
  const node = document.querySelector(selector);
  if (!node) {
    return;
  }
  node.textContent = text;
}

function emptyPayload() {
  return {
    generated_at: null,
    system: {
      name: "cryptoMaster Orchestrator",
      mode: "dry_run",
      base_currency: "EUR",
      supported_assets: ["BTC", "ETH", "SOL", "BNB", "XRP"],
    },
    summary: {
      total_equity: 0,
      pnl_abs: 0,
      pnl_pct: 0,
      decisions_last_24h: 0,
      trades_last_24h: 0,
    },
    market: [],
    agents: [],
    recent_decisions: [],
    recent_trades: [],
    recent_events: [],
    score_series: {},
  };
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
