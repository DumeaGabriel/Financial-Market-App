/**
 * predictions.js
 *
 * Drives the ML Predictions Dashboard.
 *
 * API document shape (from prediction_job.py / AnalyticsPredictionsRepository):
 * {
 *   asset_id, source_id, business_date,
 *   actual_open, predicted_open,
 *   close, low, high,
 *   seconds,
 *   model_type,
 *   generated_at
 * }
 */

// ── State ─────────────────────────────────────────────────────────────────────

const state = {
  items: [],
  predChart: null,
  errorChart: null,
  theme: matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light",
};

// ── Helpers ───────────────────────────────────────────────────────────────────

const el = (id) => document.getElementById(id);

function apiBase() {
  return el("apiBase").value.trim().replace(/\/$/, "");
}

async function fetchJson(path) {
  const res = await fetch(`${apiBase()}${path}`);
  if (!res.ok) throw new Error(`HTTP ${res.status} – ${res.statusText}`);
  return res.json();
}

function fmt(value, decimals = 2) {
  if (value == null || isNaN(value)) return "—";
  return Number(value).toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

function fmtPct(value) {
  if (value == null || isNaN(value)) return "—";
  const sign = value >= 0 ? "+" : "";
  return `${sign}${Number(value).toFixed(2)}%`;
}

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

// ── Theme ─────────────────────────────────────────────────────────────────────

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  state.theme = theme;
}

// ── Filter initialisation ─────────────────────────────────────────────────────

function fillSelect(selectId, items, allLabel = "All") {
  const select = el(selectId);
  const current = select.value;
  const firstOpt = select.options[0]?.outerHTML ?? `<option value="">${allLabel}</option>`;
  select.innerHTML =
    firstOpt +
    items
      .map((v) => `<option value="${String(v).replace(/"/g, "&quot;")}">${v}</option>`)
      .join("");
  if ([...select.options].some((o) => o.value === current)) select.value = current;
}

async function initialize() {
  el("connectionStatus").textContent = "Loading filter options…";
  try {
    const [assets, models] = await Promise.all([
      fetchJson("/api/v1/analytics/predictions/assets?limit=100"),
      fetchJson("/api/v1/analytics/predictions/models"),
    ]);
    fillSelect("assetSelect", assets.items ?? [], "All assets");
    fillSelect("modelSelect", models.items ?? [], "All models");
    el("connectionStatus").textContent =
      "Connected. Select filters and press Load predictions.";
  } catch (err) {
    el("connectionStatus").textContent = `Could not load filter options: ${err.message}`;
  }
}

// ── Query ─────────────────────────────────────────────────────────────────────

function buildQuery() {
  const params = new URLSearchParams({ limit: "100" });
  const assetId = el("assetSelect").value;
  const modelType = el("modelSelect").value;
  const startDate = el("startDate").value;
  const endDate = el("endDate").value;

  if (assetId) params.set("assetId", assetId);
  if (modelType) params.set("modelType", modelType);
  if (startDate) params.set("startBusinessDate", startDate);
  if (endDate) params.set("endBusinessDate", endDate);

  return params.toString();
}

// ── KPIs ──────────────────────────────────────────────────────────────────────

function renderKpis(items) {
  el("kpiCount").textContent = items.length || "0";
  el("kpiCountSub").textContent = items.length
    ? `Across ${new Set(items.map((x) => x.asset_id)).size} asset(s)`
    : "No matching records";

  if (!items.length) {
    el("kpiMAE").textContent = "—";
    el("kpiMAPE").textContent = "—";
    el("kpiBest").textContent = "—";
    el("kpiBestDate").textContent = "Smallest absolute error";
    el("kpiWorst").textContent = "—";
    el("kpiWorstDate").textContent = "Largest absolute error";
    return;
  }

  const errors = items.map((it) => {
    const actual = Number(it.actual_open);
    const pred = Number(it.predicted_open);
    return { date: it.business_date, abs: Math.abs(actual - pred), pct: actual !== 0 ? (Math.abs(actual - pred) / Math.abs(actual)) * 100 : null };
  });

  const validErrors = errors.filter((e) => isFinite(e.abs));
  const mae = validErrors.reduce((s, e) => s + e.abs, 0) / validErrors.length;

  const validPcts = errors.filter((e) => e.pct != null && isFinite(e.pct));
  const mape = validPcts.length
    ? validPcts.reduce((s, e) => s + e.pct, 0) / validPcts.length
    : null;

  const best = validErrors.reduce((a, b) => (a.abs < b.abs ? a : b));
  const worst = validErrors.reduce((a, b) => (a.abs > b.abs ? a : b));

  el("kpiMAE").textContent = fmt(mae);
  el("kpiMAPE").textContent = mape != null ? `${mape.toFixed(2)}%` : "—";
  el("kpiBest").textContent = fmt(best.abs);
  el("kpiBestDate").textContent = best.date ?? "—";
  el("kpiWorst").textContent = fmt(worst.abs);
  el("kpiWorstDate").textContent = worst.date ?? "—";
}

// ── Actual vs Predicted chart ─────────────────────────────────────────────────

function renderPredChart(items) {
  if (state.predChart) { state.predChart.destroy(); state.predChart = null; }

  const status = el("chartStatus");

  if (!items.length) {
    status.textContent = "No data to display.";
    return;
  }

  const sorted = [...items].sort((a, b) =>
    String(a.business_date).localeCompare(String(b.business_date))
  );

  // If multiple assets, annotate labels with asset_id
  const multiAsset = new Set(sorted.map((r) => r.asset_id)).size > 1;

  const labels = sorted.map((r) =>
    multiAsset ? `${r.business_date} (${r.asset_id})` : r.business_date
  );
  const actuals   = sorted.map((r) => (r.actual_open    != null ? Number(r.actual_open)    : null));
  const predicted = sorted.map((r) => (r.predicted_open != null ? Number(r.predicted_open) : null));

  const mutedColor = cssVar("--color-text-muted");

  state.predChart = new Chart(el("predChart"), {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "Actual open",
          data: actuals,
          borderColor: "#4f98a3",
          backgroundColor: "rgba(79,152,163,0.10)",
          borderWidth: 2.5,
          pointRadius: sorted.length > 80 ? 0 : 3,
          pointHoverRadius: 5,
          tension: 0.2,
          fill: false,
          spanGaps: true,
        },
        {
          label: "Predicted open",
          data: predicted,
          borderColor: "#e8af34",
          backgroundColor: "rgba(232,175,52,0.08)",
          borderWidth: 2,
          borderDash: [6, 3],
          pointRadius: sorted.length > 80 ? 0 : 3,
          pointHoverRadius: 5,
          tension: 0.2,
          fill: false,
          spanGaps: true,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: {
          display: true,
          labels: { color: mutedColor, boxWidth: 14, usePointStyle: true },
        },
        tooltip: {
          callbacks: {
            label: (ctx) => `${ctx.dataset.label}: ${fmt(ctx.parsed.y)}`,
            afterBody: (items) => {
              const a = items.find((i) => i.datasetIndex === 0)?.parsed.y;
              const p = items.find((i) => i.datasetIndex === 1)?.parsed.y;
              if (a != null && p != null) {
                const err = a - p;
                const pct = a !== 0 ? ((Math.abs(err) / Math.abs(a)) * 100).toFixed(2) : "—";
                return [`Error: ${err >= 0 ? "+" : ""}${fmt(err)} (${pct}%)`];
              }
              return [];
            },
          },
        },
      },
      scales: {
        x: {
          ticks: { color: mutedColor, maxRotation: 45, autoSkip: true, maxTicksLimit: 20 },
          grid: { color: "rgba(128,128,128,0.08)" },
        },
        y: {
          ticks: { color: mutedColor, callback: (v) => fmt(v) },
          grid: { color: "rgba(128,128,128,0.08)" },
        },
      },
    },
  });

  status.textContent = `Showing ${sorted.length} prediction${sorted.length !== 1 ? "s" : ""}.`;
}

// ── Error histogram ───────────────────────────────────────────────────────────

function renderErrorChart(items) {
  if (state.errorChart) { state.errorChart.destroy(); state.errorChart = null; }

  const status = el("errorStatus");

  if (!items.length) {
    status.textContent = "No data to display.";
    return;
  }

  const rawErrors = items
    .map((r) => Number(r.actual_open) - Number(r.predicted_open))
    .filter((e) => isFinite(e));

  if (!rawErrors.length) {
    status.textContent = "Could not compute errors (missing values).";
    return;
  }

  // Build histogram with ~12 bins
  const min = Math.min(...rawErrors);
  const max = Math.max(...rawErrors);
  const binCount = Math.min(12, rawErrors.length);
  const binSize = (max - min) / binCount || 1;

  const bins = Array.from({ length: binCount }, (_, i) => ({
    label: `${fmt(min + i * binSize, 1)}`,
    count: 0,
  }));

  for (const e of rawErrors) {
    const idx = Math.min(Math.floor((e - min) / binSize), binCount - 1);
    bins[idx].count++;
  }

  const mutedColor = cssVar("--color-text-muted");

  // Color bins: negative errors → error tint, positive → success tint, near-zero → primary
  const barColors = bins.map((b) => {
    const center = min + (bins.indexOf(b) + 0.5) * binSize;
    if (center < -binSize * 0.5) return "rgba(161,44,123,0.55)";
    if (center >  binSize * 0.5) return "rgba(67,122,34,0.55)";
    return "rgba(79,152,163,0.60)";
  });

  state.errorChart = new Chart(el("errorChart"), {
    type: "bar",
    data: {
      labels: bins.map((b) => b.label),
      datasets: [{
        label: "Frequency",
        data: bins.map((b) => b.count),
        backgroundColor: barColors,
        borderRadius: 4,
        borderSkipped: false,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: (items) => `Error ≈ ${items[0].label}`,
            label: (ctx) => `Count: ${ctx.parsed.y}`,
          },
        },
      },
      scales: {
        x: {
          ticks: { color: mutedColor, maxRotation: 45, autoSkip: true },
          grid: { display: false },
          title: { display: true, text: "actual − predicted", color: mutedColor, font: { size: 11 } },
        },
        y: {
          ticks: { color: mutedColor, precision: 0 },
          grid: { color: "rgba(128,128,128,0.08)" },
          title: { display: true, text: "count", color: mutedColor, font: { size: 11 } },
        },
      },
    },
  });

  status.textContent = `Histogram of ${rawErrors.length} error values.`;
}

// ── Table ─────────────────────────────────────────────────────────────────────

function renderTable(items) {
  const container = el("tableContainer");
  el("rowCountBadge").textContent = `${items.length} rows`;

  if (!items.length) {
    container.className = "table-empty-pred";
    container.innerHTML = "No predictions match the selected filters.";
    return;
  }

  // Compute threshold for "high error" warning highlight (top 15%)
  const absErrors = items
    .map((r) => Math.abs(Number(r.actual_open) - Number(r.predicted_open)))
    .filter(isFinite);
  absErrors.sort((a, b) => a - b);
  const warnThreshold = absErrors[Math.floor(absErrors.length * 0.85)] ?? Infinity;

  const rows = items
    .slice(0, 100)
    .map((row) => {
      const actual = Number(row.actual_open);
      const pred   = Number(row.predicted_open);
      const err    = actual - pred;
      const absErr = Math.abs(err);
      const pct    = actual !== 0 ? (absErr / Math.abs(actual)) * 100 : null;

      const isWarn = absErr >= warnThreshold;

      const errClass = err > 0 ? "err-positive" : err < 0 ? "err-negative" : "err-neutral";

      let accuracyClass = "good";
      if (pct != null) {
        if (pct > 5) accuracyClass = "poor";
        else if (pct > 2) accuracyClass = "medium";
      }

      const accuracyLabel = pct != null
        ? `<span class="accuracy-pill ${accuracyClass}">${pct.toFixed(1)}%</span>`
        : "—";

      return `
        <tr class="${isWarn ? "row-warn" : ""}">
          <td>${row.business_date ?? "—"}</td>
          <td>${row.asset_id ?? "—"}</td>
          <td>${row.source_id ?? "—"}</td>
          <td class="th-actual">${fmt(actual)}</td>
          <td class="th-predicted">${fmt(pred)}</td>
          <td class="${errClass}">${err >= 0 ? "+" : ""}${fmt(err)}</td>
          <td>${accuracyLabel}</td>
          <td>${fmt(Number(row.close))}</td>
          <td>${fmt(Number(row.low))}</td>
          <td>${fmt(Number(row.high))}</td>
          <td>${row.model_type ?? "—"}</td>
        </tr>`;
    })
    .join("");

  container.className = "pred-table-scroll";
  container.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>Date</th>
          <th>Asset</th>
          <th>Source</th>
          <th class="th-actual">Actual open</th>
          <th class="th-predicted">Predicted open</th>
          <th class="th-error">Error</th>
          <th class="th-error">Error %</th>
          <th>Close</th>
          <th>Low</th>
          <th>High</th>
          <th>Model</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>`;
}

// ── Load ──────────────────────────────────────────────────────────────────────

async function loadPredictions() {
  el("connectionStatus").textContent = "Loading predictions…";

  try {
    const query = buildQuery();
    const data = await fetchJson(`/api/v1/analytics/predictions?${query}`);
    const items = data.items ?? [];

    // Sort newest-first for KPIs; charts will re-sort ascending
    items.sort((a, b) => String(b.business_date).localeCompare(String(a.business_date)));

    state.items = items;

    renderKpis(items);
    renderPredChart(items);
    renderErrorChart(items);
    renderTable(items);

    el("connectionStatus").textContent =
      `Loaded ${items.length} prediction record${items.length !== 1 ? "s" : ""}.`;
  } catch (err) {
    el("connectionStatus").textContent = `Could not load predictions: ${err.message}`;
    renderKpis([]);
    renderTable([]);
  }
}

// ── Boot ──────────────────────────────────────────────────────────────────────

applyTheme(state.theme);

el("themeToggle").addEventListener("click", () => {
  applyTheme(state.theme === "dark" ? "light" : "dark");
});

el("applyBtn").addEventListener("click", loadPredictions);
el("filtersForm").addEventListener("submit", (e) => {
  e.preventDefault();
  loadPredictions();
});

initialize();