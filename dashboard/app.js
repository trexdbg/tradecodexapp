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
};

document.addEventListener("DOMContentLoaded", async () => {
  state.data = await loadDashboardData();
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
  renderHeader();
  renderKpis();
  renderMarketTiles();
  renderAgents();
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
  const summary = state.data.summary || {};
  setText("#kpiEquity", formatMoney(summary.total_equity));
  const pnlNode = document.querySelector("#kpiPnl");
  if (pnlNode) {
    pnlNode.textContent = `${formatMoney(summary.pnl_abs)} (${formatPercent(summary.pnl_pct)})`;
    pnlNode.classList.toggle("positive", (summary.pnl_abs || 0) >= 0);
    pnlNode.classList.toggle("negative", (summary.pnl_abs || 0) < 0);
  }
  setText("#kpiDecisions", String(summary.decisions_last_24h || 0));
  setText("#kpiTrades", String(summary.trades_last_24h || 0));
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

  const agents = [...(state.data.agents || [])];
  agents.sort((a, b) => (b.equity || 0) - (a.equity || 0));
  if (!agents.length) {
    agentsGrid.innerHTML = `<p class="no-data">Aucun agent initialise.</p>`;
    return;
  }

  agents.forEach((agent) => {
    const pnl = Number(agent.pnl_abs || 0);
    const card = document.createElement("article");
    card.className = "agent-card";
    card.innerHTML = `
      <div class="agent-row">
        <p class="agent-name">${escapeHtml(agent.name)} <span class="muted">(${escapeHtml(agent.id)})</span></p>
        <p class="agent-risk">${escapeHtml(agent.risk_profile)}</p>
      </div>
      <div class="agent-metrics">
        <p>Equity<strong>${formatMoney(agent.equity)}</strong></p>
        <p>Cash<strong>${formatMoney(agent.cash_balance)}</strong></p>
        <p>PnL<strong class="${pnl >= 0 ? "positive" : "negative"}">${formatMoney(pnl)}</strong></p>
      </div>
    `;
    agentsGrid.appendChild(card);
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

function formatMoney(value) {
  return currency.format(Number(value || 0));
}

function formatPercent(value) {
  const number = Number(value || 0) * 100;
  const sign = number >= 0 ? "+" : "";
  return `${sign}${number.toFixed(2)}%`;
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
