const DATA_URL = "./data/dashboard-data.json";
const FALLBACK_URL = "./data/sample-dashboard-data.json";
const PORTFOLIO_COLOR = "#19b4d6";

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
  renderPortfolioEvolutionChart();
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
      renderPortfolioEvolutionChart();
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
}

function renderTradesTable() {
  const body = document.querySelector("#tradesBody");
  if (!body) {
    return;
  }
  body.innerHTML = "";

  const trades = filterRows(state.data.recent_trades || []);
  if (!trades.length) {
    body.innerHTML = `<tr><td colspan="10" class="no-data">Aucun trade pour ce filtre.</td></tr>`;
    return;
  }

  trades.slice(0, 30).forEach((trade) => {
    const tr = document.createElement("tr");
    const side = String(trade.side || "").toUpperCase();
    const sideClass = side === "BUY" ? "positive" : side === "SELL" ? "negative" : "";
    const reasonLabel = formatTradeReason(trade.reason);
    const decisionContext = formatDecisionContext(findDecisionContextForTrade(trade));
    tr.innerHTML = `
      <td>${formatDateTime(trade.created_at)}</td>
      <td>${escapeHtml(trade.agent_id)}</td>
      <td>${escapeHtml(trade.asset)}</td>
      <td class="${sideClass}">${escapeHtml(side || "-")}</td>
      <td>${formatQuantity(trade.quantity)}</td>
      <td>${formatMoney(trade.notional_eur)}</td>
      <td>${formatMoney(trade.price)}</td>
      <td>${formatMoney(trade.fee_eur)}</td>
      <td class="reason-cell">${escapeHtml(reasonLabel)}</td>
      <td class="context-cell">${escapeHtml(decisionContext)}</td>
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

function renderPortfolioEvolutionChart() {
  const chart = document.querySelector("#portfolioChart");
  const meta = document.querySelector("#portfolioChartMeta");
  const tooltip = document.querySelector("#portfolioChartTooltip");
  if (!chart || !meta || !tooltip) {
    return;
  }

  chart.onpointermove = null;
  chart.onpointerleave = null;
  chart.onpointerdown = null;
  tooltip.hidden = true;
  chart.innerHTML = "";

  const selectedAgent = (state.data.agents || []).find((agent) => agent.id === state.selectedAgentId);
  if (!selectedAgent) {
    meta.textContent = "Agent selectionne";
    chart.innerHTML = buildPortfolioChartEmptyState("Selectionne un agent pour voir sa courbe");
    return;
  }

  const series = buildPortfolioEvolutionSeries(selectedAgent);
  if (!series.length) {
    meta.textContent = `${selectedAgent.name} (${selectedAgent.id})`;
    chart.innerHTML = buildPortfolioChartEmptyState("Pas assez de donnees pour tracer la courbe");
    return;
  }

  const points = series
    .map((point, index) => {
      const equity = Number(point.equity || 0);
      return {
        index,
        time: point.time,
        equity,
        ts: toTimestamp(point.time),
      };
    })
    .filter((point) => Number.isFinite(point.equity));
  if (!points.length) {
    meta.textContent = `${selectedAgent.name} (${selectedAgent.id})`;
    chart.innerHTML = buildPortfolioChartEmptyState("Aucune valeur exploitable pour le graphe");
    return;
  }

  const startValue = Number(series[0].equity || 0);
  const endValue = Number(series[series.length - 1].equity || 0);
  const delta = endValue - startValue;
  const deltaPct = startValue !== 0 ? delta / startValue : 0;
  meta.textContent = `${selectedAgent.name} (${selectedAgent.id}) | ${formatMoney(delta)} (${formatPercent(
    deltaPct
  )})`;

  const width = 1000;
  const height = 320;
  const margins = {
    top: 26,
    right: 84,
    bottom: 44,
    left: 86,
  };
  const plotWidth = width - margins.left - margins.right;
  const plotHeight = height - margins.top - margins.bottom;
  const values = points.map((point) => point.equity);
  let minValue = Math.min(...values);
  let maxValue = Math.max(...values);
  if (Math.abs(maxValue - minValue) < 1e-9) {
    const offset = Math.max(Math.abs(maxValue) * 0.015, 0.5);
    minValue -= offset;
    maxValue += offset;
  }
  const verticalPad = Math.max((maxValue - minValue) * 0.15, 0.35);
  const yMin = minValue - verticalPad;
  const yMax = maxValue + verticalPad;

  const hasTimeAxis = points.some((point) => point.ts > 0);
  points.forEach((point, index) => {
    point.xValue = hasTimeAxis && point.ts > 0 ? point.ts : index;
  });
  const xValues = points.map((point) => point.xValue);
  const xMin = Math.min(...xValues);
  let xMax = Math.max(...xValues);
  if (Math.abs(xMax - xMin) < 1) {
    xMax = xMin + 1;
  }

  const toY = (value) => {
    const ratio = (Number(value || 0) - yMin) / Math.max(1e-9, yMax - yMin);
    return height - margins.bottom - ratio * plotHeight;
  };
  const toX = (xValue) => {
    const ratio = (Number(xValue || 0) - xMin) / Math.max(1e-9, xMax - xMin);
    return margins.left + ratio * plotWidth;
  };

  const chartCoords = points.map((point) => ({
    ...point,
    x: toX(point.xValue),
    y: toY(point.equity),
  }));
  const linePath = buildSmoothLinePath(chartCoords);
  const areaPath = `${linePath} L ${chartCoords[chartCoords.length - 1].x.toFixed(2)} ${(height - margins.bottom).toFixed(
    2
  )} L ${chartCoords[0].x.toFixed(2)} ${(height - margins.bottom).toFixed(2)} Z`;

  const lineColor =
    Math.abs(delta) < 1e-9 ? PORTFOLIO_COLOR : delta >= 0 ? "rgba(87,199,133,0.95)" : "rgba(255,110,110,0.95)";
  const gradientStart =
    Math.abs(delta) < 1e-9 ? "rgba(25,180,214,0.30)" : delta >= 0 ? "rgba(87,199,133,0.30)" : "rgba(255,110,110,0.28)";
  const gradientEnd =
    Math.abs(delta) < 1e-9 ? "rgba(25,180,214,0.02)" : delta >= 0 ? "rgba(87,199,133,0.02)" : "rgba(255,110,110,0.02)";

  const gradientId = `portfolioAreaGradient_${String(selectedAgent.id || "agent").replace(/[^a-zA-Z0-9_-]/g, "_")}`;
  const parts = [];
  parts.push("<defs>");
  parts.push(`<linearGradient id="${gradientId}" x1="0%" y1="0%" x2="0%" y2="100%">`);
  parts.push(`<stop offset="0%" stop-color="${gradientStart}" />`);
  parts.push(`<stop offset="100%" stop-color="${gradientEnd}" />`);
  parts.push("</linearGradient>");
  parts.push("</defs>");

  const yTicks = 5;
  for (let i = 0; i < yTicks; i += 1) {
    const ratio = i / Math.max(1, yTicks - 1);
    const y = margins.top + ratio * plotHeight;
    const value = yMax - ratio * (yMax - yMin);
    parts.push(
      `<line class="chart-grid" x1="${margins.left.toFixed(2)}" y1="${y.toFixed(2)}" x2="${(width - margins.right).toFixed(
        2
      )}" y2="${y.toFixed(2)}" />`
    );
    parts.push(
      `<text class="chart-axis-label" x="${(margins.left - 10).toFixed(2)}" y="${(y + 4).toFixed(
        2
      )}" text-anchor="end">${escapeHtml(formatMoney(value))}</text>`
    );
  }

  const xTicks = Math.min(5, Math.max(2, chartCoords.length));
  for (let i = 0; i < xTicks; i += 1) {
    const ratio = xTicks === 1 ? 0 : i / (xTicks - 1);
    const xValue = xMin + ratio * (xMax - xMin);
    const x = toX(xValue);
    const label = hasTimeAxis ? formatChartTimeLabel(xValue) : `Point ${Math.round(xValue) + 1}`;
    parts.push(
      `<line class="chart-grid" x1="${x.toFixed(2)}" y1="${margins.top.toFixed(2)}" x2="${x.toFixed(2)}" y2="${(
        height - margins.bottom
      ).toFixed(2)}" />`
    );
    parts.push(
      `<text class="chart-axis-label" x="${x.toFixed(2)}" y="${(height - margins.bottom + 18).toFixed(
        2
      )}" text-anchor="middle">${escapeHtml(label)}</text>`
    );
  }

  const startY = toY(startValue);
  parts.push(
    `<line class="chart-baseline" x1="${margins.left.toFixed(2)}" y1="${startY.toFixed(2)}" x2="${(width - margins.right).toFixed(
      2
    )}" y2="${startY.toFixed(2)}" />`
  );

  parts.push(`<path d="${areaPath}" fill="url(#${gradientId})" />`);
  parts.push(`<path class="chart-series" d="${linePath}" stroke="${lineColor}" />`);

  const startX = chartCoords[0].x;
  const endX = chartCoords[chartCoords.length - 1].x;
  const endY = toY(endValue);
  parts.push(`<circle cx="${startX.toFixed(2)}" cy="${startY.toFixed(2)}" r="3.8" fill="${lineColor}" />`);
  parts.push(`<circle cx="${endX.toFixed(2)}" cy="${endY.toFixed(2)}" r="4.3" fill="${lineColor}" />`);
  parts.push(
    `<text class="chart-axis-label" x="${(margins.left + 4).toFixed(2)}" y="${(startY - 8).toFixed(2)}">${escapeHtml(
      formatMoney(startValue)
    )}</text>`
  );
  parts.push(
    `<text class="chart-axis-label" x="${(width - margins.right - 4).toFixed(2)}" y="${(endY - 8).toFixed(
      2
    )}" text-anchor="end">${escapeHtml(formatMoney(endValue))}</text>`
  );

  parts.push(
    `<line id="portfolioFocusLine" class="chart-focus-line" x1="0" y1="${margins.top.toFixed(2)}" x2="0" y2="${(
      height - margins.bottom
    ).toFixed(2)}" visibility="hidden" />`
  );
  parts.push(
    `<circle id="portfolioFocusDot" class="chart-focus-dot" cx="0" cy="0" r="5" fill="${lineColor}" visibility="hidden" />`
  );
  chartCoords.forEach((point, index) => {
    parts.push(
      `<circle class="chart-hit" data-index="${index}" cx="${point.x.toFixed(2)}" cy="${point.y.toFixed(2)}" r="9" />`
    );
  });

  chart.innerHTML = parts.join("");
  bindPortfolioChartInteractions({
    chart,
    tooltip,
    chartCoords,
    lineColor,
    width,
    height,
    plotTop: margins.top,
    plotBottom: height - margins.bottom,
  });
}

function buildPortfolioEvolutionSeries(agent) {
  const trades = (state.data.recent_trades || [])
    .filter((trade) => trade.agent_id === agent.id)
    .sort((a, b) => toTimestamp(a.created_at) - toTimestamp(b.created_at));

  const prices = new Map();
  (state.data.market || []).forEach((item) => {
    prices.set(String(item.asset || "").toUpperCase(), Number(item.last_price || 0));
  });

  const quantities = new Map();
  let cash = Number(agent.initial_balance || 0);
  const points = [];
  const addPoint = (time, equity) => {
    if (!Number.isFinite(equity)) {
      return;
    }
    points.push({ time, equity });
  };
  addPoint(trades[0]?.created_at || state.data.generated_at, cash);

  trades.forEach((trade) => {
    const side = String(trade.side || "").toUpperCase();
    const asset = String(trade.asset || "").toUpperCase();
    const quantity = Number(trade.quantity || 0);
    const notional = Number(trade.notional_eur || 0);
    const fee = Number(trade.fee_eur || 0);
    const price = Number(trade.price || 0);

    if (!asset || quantity <= 0 || price <= 0) {
      return;
    }

    prices.set(asset, price);
    const currentQty = Number(quantities.get(asset) || 0);
    if (side === "BUY") {
      cash -= notional + fee;
      quantities.set(asset, currentQty + quantity);
    } else if (side === "SELL") {
      cash += notional - fee;
      const newQty = currentQty - quantity;
      if (Math.abs(newQty) <= 1e-10) {
        quantities.delete(asset);
      } else {
        quantities.set(asset, newQty);
      }
    }

    let positionsValue = 0;
    quantities.forEach((qty, heldAsset) => {
      positionsValue += Number(qty || 0) * Number(prices.get(heldAsset) || 0);
    });
    addPoint(trade.created_at, cash + positionsValue);
  });

  addPoint(state.data.generated_at, Number(agent.equity || cash));
  if (points.length === 1) {
    addPoint(state.data.generated_at, Number(agent.equity || points[0].equity));
  }
  return points;
}

function buildPortfolioChartEmptyState(message) {
  return `<text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" fill="#86a2b4" font-size="15">${escapeHtml(
    message
  )}</text>`;
}

function buildSmoothLinePath(points) {
  if (!points.length) {
    return "";
  }
  if (points.length === 1) {
    return `M ${points[0].x.toFixed(2)} ${points[0].y.toFixed(2)}`;
  }
  if (points.length === 2) {
    return `M ${points[0].x.toFixed(2)} ${points[0].y.toFixed(2)} L ${points[1].x.toFixed(2)} ${points[1].y.toFixed(
      2
    )}`;
  }

  const segments = [`M ${points[0].x.toFixed(2)} ${points[0].y.toFixed(2)}`];
  for (let i = 1; i < points.length - 1; i += 1) {
    const controlX = points[i].x.toFixed(2);
    const controlY = points[i].y.toFixed(2);
    const nextX = ((points[i].x + points[i + 1].x) / 2).toFixed(2);
    const nextY = ((points[i].y + points[i + 1].y) / 2).toFixed(2);
    segments.push(`Q ${controlX} ${controlY} ${nextX} ${nextY}`);
  }
  const last = points[points.length - 1];
  segments.push(`T ${last.x.toFixed(2)} ${last.y.toFixed(2)}`);
  return segments.join(" ");
}

function bindPortfolioChartInteractions({ chart, tooltip, chartCoords, lineColor, width, height, plotTop, plotBottom }) {
  if (!chartCoords.length) {
    return;
  }

  const focusLine = chart.querySelector("#portfolioFocusLine");
  const focusDot = chart.querySelector("#portfolioFocusDot");
  if (!focusLine || !focusDot) {
    return;
  }

  const updateSelection = (index) => {
    const point = chartCoords[Math.max(0, Math.min(chartCoords.length - 1, index))];
    if (!point) {
      return;
    }

    focusLine.setAttribute("x1", point.x.toFixed(2));
    focusLine.setAttribute("x2", point.x.toFixed(2));
    focusLine.setAttribute("y1", plotTop.toFixed(2));
    focusLine.setAttribute("y2", plotBottom.toFixed(2));
    focusLine.setAttribute("visibility", "visible");

    focusDot.setAttribute("cx", point.x.toFixed(2));
    focusDot.setAttribute("cy", point.y.toFixed(2));
    focusDot.setAttribute("fill", lineColor);
    focusDot.setAttribute("visibility", "visible");

    tooltip.hidden = false;
    tooltip.style.borderColor = lineColor;
    tooltip.innerHTML = `
      <p class="value">${escapeHtml(formatMoney(point.equity))}</p>
      <p class="time">${escapeHtml(formatDateTime(point.time))}</p>
    `;

    const chartRect = chart.getBoundingClientRect();
    const xPx = (point.x / width) * chartRect.width;
    const yPx = (point.y / height) * chartRect.height;
    const maxLeft = Math.max(8, chartRect.width - tooltip.offsetWidth - 8);
    const maxTop = Math.max(8, chartRect.height - tooltip.offsetHeight - 8);
    const left = clamp(xPx + 12, 8, maxLeft);
    const top = clamp(yPx - tooltip.offsetHeight - 12, 8, maxTop);
    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${top}px`;
  };

  const hideSelection = () => {
    focusLine.setAttribute("visibility", "hidden");
    focusDot.setAttribute("visibility", "hidden");
    tooltip.hidden = true;
  };

  const findNearestPointIndex = (targetX) => {
    let nearestIndex = 0;
    let nearestDistance = Number.POSITIVE_INFINITY;
    chartCoords.forEach((point, index) => {
      const distance = Math.abs(point.x - targetX);
      if (distance < nearestDistance) {
        nearestDistance = distance;
        nearestIndex = index;
      }
    });
    return nearestIndex;
  };

  const toSvgX = (event) => {
    const ctm = chart.getScreenCTM();
    if (!ctm) {
      return null;
    }
    const svgPoint = chart.createSVGPoint();
    svgPoint.x = event.clientX;
    svgPoint.y = event.clientY;
    return svgPoint.matrixTransform(ctm.inverse()).x;
  };

  chart.onpointermove = (event) => {
    const x = toSvgX(event);
    if (x == null) {
      return;
    }
    updateSelection(findNearestPointIndex(x));
  };
  chart.onpointerdown = (event) => {
    const x = toSvgX(event);
    if (x == null) {
      return;
    }
    updateSelection(findNearestPointIndex(x));
  };
  chart.onpointerleave = () => {
    hideSelection();
  };

  updateSelection(chartCoords.length - 1);
}

function formatChartTimeLabel(value) {
  const parsed = new Date(Number(value || 0));
  if (Number.isNaN(parsed.getTime())) {
    return "-";
  }
  return parsed.toLocaleString("fr-FR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function formatTradeReason(reason) {
  const raw = String(reason || "").trim();
  if (!raw) {
    return "-";
  }

  const mapped = raw
    .split("|")
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => {
      const [key, ...rest] = part.split("=");
      if (!rest.length) {
        return part.replace(/_/g, " ");
      }
      const keyLabel = key.replace(/_/g, " ");
      const valueLabel = rest.join("=").replace(/_/g, " ");
      return `${keyLabel}: ${valueLabel}`;
    });
  return mapped.join(" | ") || raw.replace(/_/g, " ");
}

function findDecisionContextForTrade(trade) {
  const tradeTs = toTimestamp(trade.created_at);
  const decisions = (state.data.recent_decisions || []).filter(
    (decision) => decision.agent_id === trade.agent_id && decision.asset === trade.asset
  );
  if (!decisions.length || !tradeTs) {
    return null;
  }

  const maxLagMs = 6 * 60 * 60 * 1000;
  const prior = decisions
    .map((decision) => {
      const decisionTs = toTimestamp(decision.created_at);
      return {
        ...decision,
        lag: tradeTs - decisionTs,
      };
    })
    .filter((decision) => decision.lag >= 0 && decision.lag <= maxLagMs)
    .sort((a, b) => a.lag - b.lag);
  if (prior.length) {
    return prior[0];
  }

  const nearest = decisions
    .map((decision) => {
      const decisionTs = toTimestamp(decision.created_at);
      return {
        ...decision,
        distance: Math.abs(tradeTs - decisionTs),
      };
    })
    .sort((a, b) => a.distance - b.distance);
  return nearest[0] || null;
}

function formatDecisionContext(decision) {
  if (!decision) {
    return "-";
  }
  const score = Number(decision.score || 0);
  const scoreText = `${score >= 0 ? "+" : ""}${score.toFixed(3)}`;
  const strategies = Object.entries(decision.rationale?.strategy_scores || {})
    .filter(([, value]) => Math.abs(Number(value || 0)) > 0.01)
    .map(([name]) => name.replace(/_/g, " "));
  const strategyText = strategies.length ? strategies.join(", ") : "no strategy details";
  return `${decision.action} | score ${scoreText} | regime ${decision.regime || "-"} | ${strategyText}`;
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
