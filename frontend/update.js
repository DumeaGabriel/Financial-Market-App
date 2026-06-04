import {
    checkApiHealth,
    fetchAssets,
    fetchAssetDetails,
    fetchDataSources,
    fetchDataSourceDetails,
    updateAsset,
    updateDataSource
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

    entityType: document.getElementById("entity-type"),
    entityId: document.getElementById("entity-id"),

    checkHealthBtn: document.getElementById("check-health"),
    loadSelectedBtn: document.getElementById("load-selected"),

    selectedPreview: document.getElementById("selected-preview"),
    dynamicFields: document.getElementById("dynamic-fields"),
    editForm: document.getElementById("edit-form"),

    themeToggle: document.querySelector("[data-theme-toggle]")
};

const state = {
    selectedType: "",
    selectedId: "",
    selectedData: null
};

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
    setMessage(`${type} selected: ${id}`);
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
        button.addEventListener("click", () => selectEntity(type, id));
        li.appendChild(button);
        container.appendChild(li);
    });
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

function isEditablePrimitive(value) {
    return ["string", "number", "boolean"].includes(typeof value) || value === null;
}

function renderDynamicFields(data) {
    els.dynamicFields.innerHTML = "";

    Object.entries(data).forEach(([key, value]) => {
        if (key === "id" || key === "assetId" || key === "dataSourceId" || key === "system_time" || key === "systemDate") {
            return;
        }

        const wrapper = document.createElement("label");
        wrapper.className = "dynamic-field";

        const title = document.createElement("span");
        title.textContent = key;
        wrapper.appendChild(title);

        if (isEditablePrimitive(value)) {
            const input = document.createElement("input");
            input.name = key;
            input.dataset.originalType = value === null ? "null" : typeof value;

            if (typeof value === "boolean") {
                input.type = "text";
                input.value = String(value);
            } else if (typeof value === "number") {
                input.type = "number";
                input.value = String(value);
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

        els.dynamicFields.appendChild(wrapper);
    });
}

function collectFormData() {
    const payload = {};

    const fields = els.dynamicFields.querySelectorAll("input, textarea");

    fields.forEach((field) => {
        const key = field.name;
        const type = field.dataset.originalType;
        const rawValue = field.value;

        if (type === "number") {
            payload[key] = rawValue === "" ? null : Number(rawValue);
            return;
        }

        if (type === "boolean") {
            payload[key] = rawValue.toLowerCase() === "true";
            return;
        }

        if (type === "json") {
            payload[key] = rawValue.trim() ? JSON.parse(rawValue) : null;
            return;
        }

        if (type === "null") {
            payload[key] = rawValue.trim() === "" ? null : rawValue;
            return;
        }

        payload[key] = rawValue;
    });

    return payload;
}

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
        els.selectedPreview.textContent = JSON.stringify(data, null, 2);
        renderDynamicFields(data);
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
        const payload = collectFormData();
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

function init() {
    setThemeToggle();

    els.checkHealthBtn.addEventListener("click", handleHealthCheck);
    els.loadAssetsBtn.addEventListener("click", loadAssets);
    els.reloadAssetsBtn.addEventListener("click", loadAssets);
    els.loadSourcesBtn.addEventListener("click", loadSources);
    els.reloadSourcesBtn.addEventListener("click", loadSources);
    els.loadSelectedBtn.addEventListener("click", loadSelectedEntity);
    els.editForm.addEventListener("submit", saveChanges);

    handleHealthCheck();
    loadAssets();
    loadSources();
}

init();