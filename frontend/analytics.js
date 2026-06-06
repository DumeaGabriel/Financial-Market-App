/**
 * analytics.js
 *
 * Drives the Monthly Analytics Dashboard.
 *
 * API document shape (from aggregation_job.py):
 * {
 *   asset_id, source_id, symbol, asset_class, name, year, month,
 *   generated_at, deleted,
 *   metrics: {
 *     count, avg_open, avg_close, min_low, max_high,
 *     total_volume, avg_volume, monthly_return_pct
 *   },
 *   computed_metrics: ["avg_open", "avg_close", …]   ← array of strings
 * }
 */

// ── State ────────────────────────────────────────────────────────────────────

const state = {
  chart: null,
  items: [],
  theme: matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light",
};

// ── Helpers ──────────────────────────────────────────────────────────────────

const el = (id) => document.getElementById(id);

function apiBase() {
  return el("apiBase").value.trim().replace(/\/$/, "");
}

async function fetchJson(path) {
  const response = await fetch(`${apiBase()}${path}`);
  if (!response.ok) throw new Error(`HTTP ${response.status} – ${response.statusText}`);
  return response.json();
}

function monthLabel(item) {
  const y = item.year ?? "";
  const m = item.month ?? "";
  return y && m ? `${y}-${String(m).padStart(2, "0")}` : "n/a";
}

/**
 * Returns the numeric metrics object from an item.
 * Handles both nested { metrics: {…} } and flat top-level fields.
 */
function getMetrics(item) {
  if (item.metrics && typeof item.metrics === "object") return item.metrics;
  const out = {};
  for (const [k, v] of Object.entries(item)) {
    if (typeof v === "number" && !["year", "month"].includes(k)) out[k] = v;
  }
  return out;
}

/** All metric keys present across all items, sorted. */
function allMetricKeys(items) {
  const keys = new Set();
  for (const item of items) {
    for (const k of Object.keys(getMetrics(item))) keys.add(k);
  }
  const order = [
    "avg_close", "avg_open", "min_low", "max_high",
    "avg_volume", "total_volume", "monthly_return_pct", "count",
  ];
  const sorted = order.filter((k) => keys.has(k));
  for (const k of [...keys].sort()) {
    if (!sorted.includes(k)) sorted.push(k);
  }
  return sorted;
}

function formatNum(value, key) {
  if (value == null) return "—";
  if (typeof value !== "number") return String(value);
  if (key === "monthly_return_pct") {
    const sign = value > 0 ? "+" : "";
    return `${sign}${value.toFixed(2)}%`;
  }
  if (key === "count") return value.toLocaleString();
  if (Math.abs(value) >= 1e6) return value.toLocaleString(undefined, { maximumFractionDigits: 0 });
  return value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 });
}

function returnClass(value, key) {
  if (key !== "monthly_return_pct" || value == null) return "";
  return value > 0 ? "positive" : value < 0 ? "negative" : "";
}

// ── Theme ────────────────────────────────────────────────────────────────────

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  state.theme = theme;
}

// ── Filter initialisation ────────────────────────────────────────────────────

function fillSelect(selectId, items) {
  const select = el(selectId);
  const currentVal = select.value;
  const firstOption = select.options[0]?.outerHTML ?? '<option value="">All</option>';
  select.innerHTML =
    firstOption +
    items
      .map((v) => `<option value="${String(v).replace(/"/g, "&quot;")}">${v}</option>`)
      .join("");
  if ([...select.options].some((o) => o.value === currentVal)) {
    select.value = currentVal;
  }
}

async function initialize(showMessage = false) {
  el("connectionStatus").textContent = "Loading filter options from API…";
  try {
    const [assets, symbols, classes] = await Promise.all([
      fetchJson("/api/v1/analytics/monthly/assets?limit=100"),
      fetchJson("/api/v1/analytics/monthly/symbols?limit=100"),
      fetchJson("/api/v1/analytics/monthly/asset-classes"),
    ]);
    fillSelect("assetId", assets.items ?? []);
    fillSelect("symbol", symbols.items ?? []);
    fillSelect("assetClass", classes.items ?? []);
    el("connectionStatus").textContent = showMessage
      ? "Filter options refreshed."
      : "Connected. Select filters and press Apply filters.";
  } catch (err) {
    el("connectionStatus").textContent = `Could not load filter options: ${err.message}`;
  }
}

// ── Query ────────────────────────────────────────────────────────────────────

function buildQuery() {
  const params = new URLSearchParams();
  const map = {
    assetId: el("assetId").value,
    symbol: el("symbol").value,
    assetClass: el("assetClass").value,
    startYear: el("startYear").value,
    endYear: el("endYear").value,
    limit: "100",
  };
  for (const [key, value] of Object.entries(map)) {
    if (value !== "") params.set(key, value);
  }
  return params.toString();
}

// ── KPIs ─────────────────────────────────────────────────────────────────────

function renderKpis(items) {
  el("kpiRows").textContent = items.length;
  el("kpiRowsSub").textContent = items.length
    ? "Records currently shown by the query"
    : "No matching records";
  el("kpiLatestMonth").textContent = items.length ? monthLabel(items[0]) : "—";
  el("kpiAssets").textContent = new Set(
    items.map((x) => x.asset_id).filter(Boolean)
  ).size;
  el("kpiSymbols").textContent = new Set(
    items.map((x) => x.symbol).filter(Boolean)
  ).size;
}

// ── Metric selector ──────────────────────────────────────────────────────────

function populateMetricSelect(items) {
  const select = el("metricSelect");
  const keys = allMetricKeys(items);
  const current = select.value;

  select.innerHTML =
    '<option value="">— pick metric —</option>' +
    keys.map((k) => `<option value="${k}">${k}</option>`).join("");

  const preferred = ["avg_close", "avg_open", "monthly_return_pct"];
  const best = preferred.find((k) => keys.includes(k));
  if (keys.includes(current)) {
    select.value = current;
  } else if (best) {
    select.value = best;
  }
}

// ── Chart ────────────────────────────────────────────────────────────────────

function renderChart(items, metricKey) {
  if (state.chart) {
    state.chart.destroy();
    state.chart = null;
  }

  const badge = el("metricBadge");
  const status = el("chartStatus");

  if (!metricKey || !items.length) {
    badge.textContent = metricKey ? `Metric: ${metricKey}` : "No metric selected";
    status.textContent = items.length
      ? "Select a metric above to draw the chart."
      : "Load data first.";
    return;
  }

  const sorted = [...items].sort((a, b) => monthLabel(a).localeCompare(monthLabel(b)));

  const byAsset = new Map();
  for (const item of sorted) {
    const key = item.symbol || item.asset_id || "unknown";
    if (!byAsset.has(key)) byAsset.set(key, []);
    byAsset.get(key).push(item);
  }

  const labelSet = new Set(sorted.map(monthLabel));
  const labels = [...labelSet].sort();

  const palette = [
    "#4f98a3", "#e8af34", "#6daa45", "#d163a7", "#5591c7",
    "#e07b54", "#8e6bbf", "#4ab09e", "#d45f5f", "#7dba6f",
  ];

  const datasets = [...byAsset.entries()].map(([symbol, rows], i) => {
    const dataMap = new Map(rows.map((r) => [monthLabel(r), getMetrics(r)[metricKey] ?? null]));
    return {
      label: symbol,
      data: labels.map((l) => dataMap.get(l) ?? null),
      borderColor: palette[i % palette.length],
      backgroundColor: `${palette[i % palette.length]}22`,
      borderWidth: 2,
      tension: 0.25,
      fill: byAsset.size === 1,
      pointRadius: labels.length > 60 ? 0 : 3,
      pointHoverRadius: 5,
      spanGaps: true,
    };
  });

  const cs = getComputedStyle(document.documentElement);
  const mutedColor = cs.getPropertyValue("--color-text-muted").trim();

  state.chart = new Chart(el("trendChart"), {
    type: "line",
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: byAsset.size > 1, labels: { color: mutedColor, boxWidth: 12 } },
        tooltip: {
          callbacks: {
            label: (ctx) =>
              `${ctx.dataset.label}: ${formatNum(ctx.parsed.y, metricKey)}`,
          },
        },
      },
      scales: {
        x: {
          ticks: { color: mutedColor, maxRotation: 45, autoSkip: true, maxTicksLimit: 18 },
          grid: { color: "rgba(128,128,128,0.10)" },
        },
        y: {
          ticks: {
            color: mutedColor,
            callback: (v) => formatNum(v, metricKey),
          },
          grid: { color: "rgba(128,128,128,0.10)" },
        },
      },
    },
  });

  badge.textContent = `Metric: ${metricKey}`;
  status.textContent = `Showing ${metricKey} across ${items.length} records${byAsset.size > 1 ? `, ${byAsset.size} assets` : ""}.`;
}

// ── Table ────────────────────────────────────────────────────────────────────

function renderTable(items) {
  const container = el("tableContainer");

  if (!items.length) {
    container.className = "table-empty";
    container.innerHTML = "No records match the selected filters.";
    return;
  }

  const metricKeys = allMetricKeys(items);
  const baseColumns = ["asset_id", "source_id", "symbol", "asset_class", "year", "month", "name"];

  const headerCells =
    baseColumns.map((c) => `<th>${c.replace(/_/g, " ")}</th>`).join("") +
    metricKeys.map((k) => `<th class="th-metric">${k.replace(/_/g, " ")}</th>`).join("") +
    `<th>computed metrics</th>`;

  const rows = items
    .slice(0, 50)
    .map((item) => {
      const metrics = getMetrics(item);
      const baseCells = baseColumns
        .map((c) => `<td>${item[c] ?? "—"}</td>`)
        .join("");

      const metricCells = metricKeys
        .map((k) => {
          const val = metrics[k] ?? null;
          const cls = returnClass(val, k);
          return `<td class="${cls}">${formatNum(val, k)}</td>`;
        })
        .join("");

      const computedList = Array.isArray(item.computed_metrics)
        ? item.computed_metrics
        : [];
      const badgeHtml = computedList.length
        ? `<div class="metrics-badges">${computedList
            .map((m) => `<span class="badge">${m}</span>`)
            .join("")}</div>`
        : "—";

      return `<tr>${baseCells}${metricCells}<td>${badgeHtml}</td></tr>`;
    })
    .join("");

  container.className = "table-scroll";
  container.innerHTML = `
    <table>
      <thead><tr>${headerCells}</tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

// ── Load analytics ────────────────────────────────────────────────────────────

async function loadAnalytics() {
  el("connectionStatus").textContent = "Loading monthly analytics…";
  try {
    const query = buildQuery();
    const data = await fetchJson(
      `/api/v1/analytics/monthly${query ? "?" + query : ""}`
    );
    const items = data.items ?? [];
    state.items = items;

    renderKpis(items);
    populateMetricSelect(items);
    renderTable(items);

    const selectedMetric = el("metricSelect").value;
    renderChart(items, selectedMetric);

    el("connectionStatus").textContent = `Loaded ${items.length} monthly analytics records.`;
  } catch (err) {
    el("connectionStatus").textContent = `Could not load analytics: ${err.message}`;
    renderKpis([]);
    renderTable([]);
    renderChart([], "");
  }
  el("connectionStatus").textContent = `Loaded ${items.length} monthly analytics records.`;
    document.querySelector(".analytics-shell").classList.add("filters-applied");
}

// ── Boot ─────────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  applyTheme(state.theme);

  el("themeToggle").addEventListener("click", () => {
    applyTheme(state.theme === "dark" ? "light" : "dark");
  });

  el("applyBtn").addEventListener("click", loadAnalytics);

  el("filtersForm").addEventListener("submit", (e) => {
    e.preventDefault();
    loadAnalytics();
  });

  el("metricSelect").addEventListener("change", () => {
    renderChart(state.items, el("metricSelect").value);
  });

  initialize();
});