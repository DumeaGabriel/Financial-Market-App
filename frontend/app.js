import {
    checkApiHealth,
    fetchAssets,
    fetchAssetHistory,
    fetchDataSources,
    fetchDataSourceHistory,
    fetchTimeSeries
} from "./components/admin.js";

const els = {
    apiBaseUrl: document.getElementById("api-base-url"),
    apiStatus: document.getElementById("api-status"),
    messageBox: document.getElementById("message-box"),

    assetsOffset: document.getElementById("assets-offset"),
    assetsLimit: document.getElementById("assets-limit"),
    sourcesOffset: document.getElementById("sources-offset"),
    sourcesLimit: document.getElementById("sources-limit"),

    loadAssetsBtn: document.getElementById("load-assets"),
    reloadAssetsBtn: document.getElementById("reload-assets"),
    loadSourcesBtn: document.getElementById("load-sources"),
    reloadSourcesBtn: document.getElementById("reload-sources"),

    assetsList: document.getElementById("assets-list"),
    sourcesList: document.getElementById("sources-list"),

    queryForm: document.getElementById("query-form"),
    assetId: document.getElementById("asset-id"),
    sourceId: document.getElementById("source-id"),
    startDate: document.getElementById("start-date"),
    endDate: document.getElementById("end-date"),
    includeAttributes: document.getElementById("include-attributes"),
    recordsTableBody: document.getElementById("records-table-body"),
    attributesBox: document.getElementById("attributes-box"),
    chartCanvas: document.getElementById("timeseries-chart"),

    checkHealthBtn: document.getElementById("check-health"),
    themeToggle: document.querySelector("[data-theme-toggle]")
};

const state = {
    chart: null
};

function setMessage(message, type = "") {
    els.messageBox.textContent = message;
    els.messageBox.className = `message-box ${type}`.trim();
}

function setThemeToggle() {
    let theme = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    document.documentElement.setAttribute("data-theme", theme);

    if (els.themeToggle) {
        els.themeToggle.addEventListener("click", () => {
            theme = theme === "dark" ? "light" : "dark";
            document.documentElement.setAttribute("data-theme", theme);
        });
    }
}

function normalizeDate(value) {
    if (!value) return "";
    return String(value).replace(" ", "T");
}

function getSystemDateValue(item) {
    return item?.systemDate || item?.system_time || "";
}

function sortBySystemDateDesc(items) {
    return [...items].sort((a, b) => {
        const aTime = Date.parse(normalizeDate(getSystemDateValue(a)));
        const bTime = Date.parse(normalizeDate(getSystemDateValue(b)));
        return (Number.isNaN(bTime) ? 0 : bTime) - (Number.isNaN(aTime) ? 0 : aTime);
    });
}

function safeStringify(value) {
    try {
        return JSON.stringify(value, null, 2);
    } catch {
        return String(value);
    }
}

function clearResults() {
    renderRecords([]);
    renderAttributes([]);
    renderChart([]);
}

function renderSelectableList(container, items, type) {
    container.innerHTML = "";

    if (!items.length) {
        const empty = document.createElement("li");
        empty.className = "list-empty";
        empty.textContent = "No items returned.";
        container.appendChild(empty);
        return;
    }

    items.forEach((id) => {
        const li = document.createElement("li");
        const button = document.createElement("button");
        button.type = "button";
        button.className = "list-item-button";
        button.textContent = id;

        button.addEventListener("click", () => {
            if (type === "asset") {
                els.assetId.value = id;
                setMessage(`Selected asset: ${id}. Press Fetch data to view results.`, "ok");
            } else {
                els.sourceId.value = id;
                setMessage(`Selected data source: ${id}. Press Fetch data to view results.`, "ok");
            }
        });

        li.appendChild(button);
        container.appendChild(li);
    });
}

function renderAttributes(attributes = []) {
    els.attributesBox.innerHTML = "";

    if (!attributes.length) {
        const chip = document.createElement("span");
        chip.className = "chip";
        chip.textContent = "No attributes returned.";
        els.attributesBox.appendChild(chip);
        return;
    }

    attributes.forEach((attribute) => {
        const chip = document.createElement("span");
        chip.className = "chip";
        chip.textContent = attribute;
        els.attributesBox.appendChild(chip);
    });
}

function renderRecords(records = []) {
    els.recordsTableBody.innerHTML = "";

    if (!records.length) {
        const row = document.createElement("tr");
        const cell = document.createElement("td");
        cell.colSpan = 3;
        cell.textContent = "No records returned.";
        row.appendChild(cell);
        els.recordsTableBody.appendChild(row);
        return;
    }

    records.forEach((record) => {
        const row = document.createElement("tr");

        const businessDate = document.createElement("td");
        businessDate.textContent = record.businessDate || "";
        row.appendChild(businessDate);

        const systemDate = document.createElement("td");
        systemDate.textContent = record.systemDate || record.system_time || "";
        row.appendChild(systemDate);

        const values = document.createElement("td");
        const valuesPre = document.createElement("pre");
        valuesPre.textContent = safeStringify(record.values || {});
        values.appendChild(valuesPre);
        row.appendChild(values);

        els.recordsTableBody.appendChild(row);
    });
}

function pickChartSeries(records = []) {
    if (!records.length) return null;

    const firstRecordWithValues = records.find((record) => {
        const values = record.values || {};
        return Object.keys(values).length > 0;
    });

    if (!firstRecordWithValues) return null;

    const preferredKeys = ["close", "price", "value", "open", "high", "low", "last"];
    const valueKeys = Object.keys(firstRecordWithValues.values || {});
    const selectedKey = preferredKeys.find((key) => valueKeys.includes(key)) || valueKeys[0];

    const labels = [...records].reverse().map((record) => record.businessDate);
    const data = [...records].reverse().map((record) => {
        const rawValue = record.values?.[selectedKey];
        const parsed = typeof rawValue === "number" ? rawValue : Number(rawValue);
        return Number.isNaN(parsed) ? null : parsed;
    });

    if (data.every((value) => value === null)) return null;

    return {
        key: selectedKey,
        labels,
        data
    };
}

function renderChart(records = []) {
    const series = pickChartSeries(records);

    if (state.chart) {
        state.chart.destroy();
        state.chart = null;
    }

    if (!series) return;

    state.chart = new Chart(els.chartCanvas, {
        type: "line",
        data: {
            labels: series.labels,
            datasets: [
                {
                    label: series.key,
                    data: series.data,
                    borderColor: "#01696f",
                    backgroundColor: "rgba(1, 105, 111, 0.15)",
                    tension: 0.2,
                    fill: true
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false
        }
    });
}

function toEntityRows(versions = []) {
    return sortBySystemDateDesc(versions).map((version) => ({
        businessDate: version.businessDate || version.business_date || "",
        systemDate: getSystemDateValue(version),
        values: version
    }));
}

function getEntityAttributes(versions = []) {
    return [...new Set(versions.flatMap((item) => Object.keys(item || {})))].sort();
}

function getDefaultStartDate() {
    return "1900-01-01";
}

function getDefaultEndDate() {
    return "2100-01-01";
}

async function handleHealthCheck() {
    try {
        const data = await checkApiHealth(els.apiBaseUrl.value.trim());
        els.apiStatus.textContent = data.status === "ok" ? "Connected" : "Unexpected";
        els.apiStatus.className = data.status === "ok" ? "status-text ok" : "status-text error";
        setMessage("API health check passed.", "ok");
    } catch (error) {
        els.apiStatus.textContent = "Unavailable";
        els.apiStatus.className = "status-text error";
        setMessage(error.message, "error");
    }
}

async function loadAssets() {
    try {
        const result = await fetchAssets(
            els.apiBaseUrl.value.trim(),
            Number(els.assetsOffset.value),
            Number(els.assetsLimit.value)
        );
        renderSelectableList(els.assetsList, result.items ?? [], "asset");
        setMessage("Assets loaded.", "ok");
    } catch (error) {
        setMessage(error.message, "error");
    }
}

async function loadSources() {
    try {
        const result = await fetchDataSources(
            els.apiBaseUrl.value.trim(),
            Number(els.sourcesOffset.value),
            Number(els.sourcesLimit.value)
        );
        renderSelectableList(els.sourcesList, result.items ?? [], "data-source");
        setMessage("Data sources loaded.", "ok");
    } catch (error) {
        setMessage(error.message, "error");
    }
}

async function handleQuerySubmit(event) {
    event.preventDefault();

    const baseUrl = els.apiBaseUrl.value.trim();
    const assetId = els.assetId.value.trim();
    const dataSourceId = els.sourceId.value.trim();
    const startBusinessDate = els.startDate.value.trim();
    const endBusinessDate = els.endDate.value.trim();
    const includeAttributes = els.includeAttributes.checked;

    clearResults();

    if (!assetId && !dataSourceId) {
        setMessage("Select at least an asset or a data source.", "error");
        return;
    }

    try {
        if (assetId && !dataSourceId) {
            const history = await fetchAssetHistory(baseUrl, assetId);
            const versions = history?.versions ?? [];
            renderRecords(toEntityRows(versions));
            renderAttributes(getEntityAttributes(versions));
            setMessage(`Showing asset collection for ${assetId}.`, "ok");
            return;
        }

        if (!assetId && dataSourceId) {
            const history = await fetchDataSourceHistory(baseUrl, dataSourceId);
            const versions = history?.versions ?? [];
            renderRecords(toEntityRows(versions));
            renderAttributes(getEntityAttributes(versions));
            setMessage(`Showing data source collection for ${dataSourceId}.`, "ok");
            return;
        }

        const resolvedStart = startBusinessDate || getDefaultStartDate();
        const resolvedEnd = endBusinessDate || getDefaultEndDate();

        const response = await fetchTimeSeries(
            baseUrl,
            assetId,
            dataSourceId,
            resolvedStart,
            resolvedEnd,
            includeAttributes
        );

        const records = sortBySystemDateDesc(response?.data?.records ?? []);
        const attributes = response?.attributes ?? [];

        renderRecords(records);
        renderAttributes(attributes);
        renderChart(records);

        setMessage(
            `Showing time-series collection for ${assetId} + ${dataSourceId} from ${resolvedStart} to ${resolvedEnd}.`,
            "ok"
        );
    } catch (error) {
        clearResults();
        setMessage(error.message, "error");
    }
}

function init() {
    setThemeToggle();

    if (els.checkHealthBtn) els.checkHealthBtn.addEventListener("click", handleHealthCheck);
    if (els.loadAssetsBtn) els.loadAssetsBtn.addEventListener("click", loadAssets);
    if (els.reloadAssetsBtn) els.reloadAssetsBtn.addEventListener("click", loadAssets);
    if (els.loadSourcesBtn) els.loadSourcesBtn.addEventListener("click", loadSources);
    if (els.reloadSourcesBtn) els.reloadSourcesBtn.addEventListener("click", loadSources);
    if (els.queryForm) els.queryForm.addEventListener("submit", handleQuerySubmit);

    handleHealthCheck();
    loadAssets();
    loadSources();
}

init();