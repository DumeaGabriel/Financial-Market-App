import {
    checkApiHealth,
    fetchAssets,
    fetchAssetDetails,
    fetchDataSources,
    fetchDataSourceDetails,
    updateAsset,
    updateDataSource,
    updateTimeSeries
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

    // Asset / source editor
    entityType: document.getElementById("entity-type"),
    entityId: document.getElementById("entity-id"),
    checkHealthBtn: document.getElementById("check-health"),
    loadSelectedBtn: document.getElementById("load-selected"),
    selectedPreview: document.getElementById("selected-preview"),
    dynamicFields: document.getElementById("dynamic-fields"),
    editForm: document.getElementById("edit-form"),

    // Time-series editor
    tsAssetId: document.getElementById("ts-asset-id"),
    tsSourceId: document.getElementById("ts-source-id"),
    tsDate: document.getElementById("ts-date"),
    loadTsBtn: document.getElementById("load-ts"),
    tsPreview: document.getElementById("ts-preview"),
    tsDynamicFields: document.getElementById("ts-dynamic-fields"),
    tsEditForm: document.getElementById("ts-edit-form"),

    themeToggle: document.querySelector("[data-theme-toggle]")
};

const state = {
    // asset / source editor
    selectedType: "",
    selectedId: "",
    selectedData: null,
    loadedAt: null,

    // time-series editor
    tsRecord: null,
    tsLoadedAt: null,
};

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

function setMessage(message, type = "") {
    els.messageBox.textContent = message;
    els.messageBox.className = `message-box ${type}`.trim();
}

function setThemeToggle() {
    let theme = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    document.documentElement.setAttribute("data-theme", theme);
    els.themeToggle.addEventListener("click", () => {
        theme = theme === "dark" ? "light" : "dark";
        document.documentElement.setAttribute("data-theme", theme);
    });
}

function selectEntity(type, id) {
    state.selectedType = type;
    state.selectedId = id;
    els.entityType.value = type;
    els.entityId.value = id;

    // Mirror selection into the time-series fields too
    if (type === "asset") els.tsAssetId.value = id;
    if (type === "data-source") els.tsSourceId.value = id;

    setMessage(`${type} selected: ${id}`);
}

// ---------------------------------------------------------------------------
// List rendering
// ---------------------------------------------------------------------------

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
        button.addEventListener("click", () => selectEntity(type, id));
        li.appendChild(button);
        container.appendChild(li);
    });
}

// ---------------------------------------------------------------------------
// Dynamic form rendering (shared for both editors)
// ---------------------------------------------------------------------------

function isEditablePrimitive(value) {
    return ["string", "number", "boolean"].includes(typeof value) || value === null;
}

const SKIP_FIELDS = new Set(["business_year", "id", "assetId", "dataSourceId", "system_date"]);
const FLOAT_FIELDS = new Set(["high", "open", "close", "low"]);

function renderDynamicFields(container, data) {
    container.innerHTML = "";

    Object.entries(data).forEach(([key, value]) => {
        if (SKIP_FIELDS.has(key)) return;

        const wrapper = document.createElement("label");
        wrapper.className = "dynamic-field";

        const title = document.createElement("span");
        title.textContent = key;
        wrapper.appendChild(title);

        if (key === "businessDate") {
            const input = document.createElement("input");
            input.name = key;
            input.type = "text";
            input.value = value ?? "";
            input.readOnly = true;
            input.dataset.originalType = "string";
            input.classList.add("readonly-field");
            wrapper.appendChild(input);
        } else if (isEditablePrimitive(value)) {
            const input = document.createElement("input");
            input.name = key;
            input.dataset.originalType = value === null ? "null" : typeof value;

            if (typeof value === "boolean") {
                input.type = "text";
                input.value = String(value);
            } else if (typeof value === "number") {
                input.type = "number";
                input.value = String(value);
                if (FLOAT_FIELDS.has(key)) {
                    input.step = "any";
                }
            } else {
                input.type = "text";
                input.value = value ?? "";
            }

            wrapper.appendChild(input);
        } else {
            const textarea = document.createElement("textarea");
            textarea.name = key;
            textarea.rows = 6;
            textarea.dataset.originalType = "json";
            textarea.value = JSON.stringify(value, null, 2);
            wrapper.appendChild(textarea);
        }

        container.appendChild(wrapper);
    });
}

function collectFormData(container) {
    const payload = {};
    container.querySelectorAll("input, textarea").forEach((field) => {
        const key = field.name;
        const type = field.dataset.originalType;
        const rawValue = field.value;

        if (type === "number") {
            if (rawValue === "") { payload[key] = null; return; }
            payload[key] = FLOAT_FIELDS.has(key) ? parseFloat(rawValue) : Number(rawValue);
            return;
        }
        if (type === "boolean") { payload[key] = rawValue.toLowerCase() === "true"; return; }
        if (type === "json")    { payload[key] = rawValue.trim() ? JSON.parse(rawValue) : null; return; }
        if (type === "null")    { payload[key] = rawValue.trim() === "" ? null : rawValue; return; }
        payload[key] = rawValue;
    });
    return payload;
}

// ---------------------------------------------------------------------------
// Health check + list loaders
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Asset / source editor
// ---------------------------------------------------------------------------

async function loadSelectedEntity() {
    if (!state.selectedType || !state.selectedId) {
        setMessage("Select an asset or data source first.", "error");
        return;
    }

    try {
        const baseUrl = els.apiBaseUrl.value.trim();
        const data = state.selectedType === "asset"
            ? await fetchAssetDetails(baseUrl, state.selectedId)
            : await fetchDataSourceDetails(baseUrl, state.selectedId);

        state.selectedData = data;
        state.loadedAt = new Date().toISOString();
        els.selectedPreview.textContent = JSON.stringify(data, null, 2);
        renderDynamicFields(els.dynamicFields, data);
        setMessage(`${state.selectedType} details loaded.`, "ok");
    } catch (error) {
        setMessage(error.message, "error");
    }
}

async function saveChanges(event) {
    event.preventDefault();

    if (!state.selectedType || !state.selectedId) {
        setMessage("Nothing selected to update.", "error");
        return;
    }

    try {
        const payload = collectFormData(els.dynamicFields);
        payload["system_date"] = state.loadedAt ?? new Date().toISOString();
        const baseUrl = els.apiBaseUrl.value.trim();

        const result = state.selectedType === "asset"
            ? await updateAsset(baseUrl, state.selectedId, payload)
            : await updateDataSource(baseUrl, state.selectedId, payload);

        els.selectedPreview.textContent = JSON.stringify(result, null, 2);
        setMessage("Changes saved successfully.", "ok");
    } catch (error) {
        setMessage(`Save failed: ${error.message}`, "error");
    }
}

// ---------------------------------------------------------------------------
// Time-series editor
// ---------------------------------------------------------------------------

async function fetchLatestTimeSeries(baseUrl, assetId, sourceId, date) {
    const start = date || "1900-01-01";
    const end   = date ? nextDay(date) : "2100-01-01";

    const params = new URLSearchParams({ assetId, dataSourceId: sourceId, startBusinessDate: start, endBusinessDate: end });
    const response = await fetch(`${baseUrl}/data?${params.toString()}`);

    if (!response.ok) {
        let detail = `Failed to fetch time-series: HTTP ${response.status}`;
        try { const b = await response.json(); if (b.detail) detail = b.detail; } catch {}
        throw new Error(detail);
    }

    const json = await response.json();
    const records = json?.data?.records ?? [];

    if (!records.length) throw new Error("No time-series records found for this combination.");

    // Deduplicate: keep latest system_date per business_date, then pick the most recent business_date
    const byDate = {};
    for (const rec of records) {
        const bd = rec.businessDate;
        const sd = rec.systemDate || rec.system_date || "";
        if (!byDate[bd] || sd > byDate[bd].systemDate) {
            byDate[bd] = { ...rec, systemDate: sd };
        }
    }

    const sorted = Object.values(byDate).sort((a, b) => b.businessDate.localeCompare(a.businessDate));
    return sorted[0];
}

function nextDay(dateStr) {
    const d = new Date(dateStr);
    d.setUTCDate(d.getUTCDate() + 1);
    return d.toISOString().slice(0, 10);
}

async function loadTimeSeries() {
    const baseUrl  = els.apiBaseUrl.value.trim();
    const assetId  = els.tsAssetId.value.trim();
    const sourceId = els.tsSourceId.value.trim();
    const date     = els.tsDate.value.trim();

    if (!assetId || !sourceId) {
        setMessage("Provide both Asset ID and Source ID for time-series.", "error");
        return;
    }

    try {
        const record = await fetchLatestTimeSeries(baseUrl, assetId, sourceId, date || null);

        state.tsRecord   = record;
        state.tsLoadedAt = new Date().toISOString();

        els.tsPreview.textContent = JSON.stringify(record, null, 2);

        // Flatten values into the top-level object so they appear as editable fields
        const flat = {
            businessDate: record.businessDate,
            ...(record.values ?? {})
        };
        renderDynamicFields(els.tsDynamicFields, flat);

        setMessage(`Time-series loaded: ${assetId} / ${sourceId} — ${record.businessDate}.`, "ok");
    } catch (error) {
        setMessage(error.message, "error");
    }
}

async function saveTsChanges(event) {
    event.preventDefault();

    if (!state.tsRecord) {
        setMessage("No time-series record loaded.", "error");
        return;
    }

    try {
        const edits = collectFormData(els.tsDynamicFields);

        const payload = {
            businessDate: state.tsRecord.businessDate,
            values: {
                ...(state.tsRecord.values ?? {}),
                ...Object.fromEntries(
                    Object.entries(edits).filter(([k]) => k !== "businessDate")
                )
            }
        };

        const baseUrl  = els.apiBaseUrl.value.trim();
        const assetId  = els.tsAssetId.value.trim();
        const sourceId = els.tsSourceId.value.trim();

        const result = await updateTimeSeries(baseUrl, assetId, sourceId, payload);

        els.tsPreview.textContent = JSON.stringify(result, null, 2);
        setMessage("Time-series record saved successfully.", "ok");
    } catch (error) {
        setMessage(`Save failed: ${error.message}`, "error");
    }
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

function init() {
    setThemeToggle();

    els.checkHealthBtn.addEventListener("click", handleHealthCheck);
    els.loadAssetsBtn.addEventListener("click", loadAssets);
    els.reloadAssetsBtn.addEventListener("click", loadAssets);
    els.loadSourcesBtn.addEventListener("click", loadSources);
    els.reloadSourcesBtn.addEventListener("click", loadSources);
    els.loadSelectedBtn.addEventListener("click", loadSelectedEntity);
    els.editForm.addEventListener("submit", saveChanges);
    els.loadTsBtn.addEventListener("click", loadTimeSeries);
    els.tsEditForm.addEventListener("submit", saveTsChanges);

    handleHealthCheck();
    loadAssets();
    loadSources();
}

init();