export async function checkApiHealth(baseUrl) {
    return getJson(`${baseUrl}/health`, "Health check failed");
}

export async function fetchAssets(baseUrl, offset = 0, limit = 10) {
    return getJson(`${baseUrl}/assets?offset=${offset}&limit=${limit}`, "Failed to fetch assets");
}

export async function fetchAssetDetails(baseUrl, assetId) {
    return getJson(
        `${baseUrl}/assets/${encodeURIComponent(assetId)}`,
        "Failed to fetch asset details"
    );
}

export async function fetchAssetHistory(baseUrl, assetId) {
    return getJson(
        `${baseUrl}/assets/${encodeURIComponent(assetId)}?history=true`,
        "Failed to fetch asset history"
    );
}

export async function updateAsset(baseUrl, assetId, fields) {
    return putJson(
        `${baseUrl}/admin/assets/${encodeURIComponent(assetId)}`,
        { fields }
    );
}

export async function fetchDataSources(baseUrl, offset = 0, limit = 10) {
    return getJson(`${baseUrl}/data-sources?offset=${offset}&limit=${limit}`, "Failed to fetch data sources");
}

export async function fetchDataSourceDetails(baseUrl, sourceId) {
    return getJson(
        `${baseUrl}/data-sources/${encodeURIComponent(sourceId)}`,
        "Failed to fetch data source details"
    );
}

export async function fetchDataSourceHistory(baseUrl, sourceId) {
    return getJson(
        `${baseUrl}/data-sources/${encodeURIComponent(sourceId)}?history=true`,
        "Failed to fetch data source history"
    );
}

export async function updateDataSource(baseUrl, sourceId, fields) {
    return putJson(
        `${baseUrl}/admin/data-sources/${encodeURIComponent(sourceId)}`,
        { fields }
    );
}

export async function fetchTimeSeries(
    baseUrl,
    assetId,
    dataSourceId,
    startBusinessDate,
    endBusinessDate,
    includeAttributes = false
) {
    const params = new URLSearchParams({
        assetId,
        dataSourceId,
        startBusinessDate,
        endBusinessDate,
        includeAttributes: String(includeAttributes)
    });

    return getJson(`${baseUrl}/data?${params.toString()}`, "Failed to fetch time series");
}

async function getJson(url, fallbackMessage) {
    const response = await fetch(url);

    if (!response.ok) {
        throw await buildError(response, fallbackMessage);
    }

    return response.json();
}

async function putJson(url, payload) {
    const response = await fetch(url, {
        method: "PUT",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify(payload)
    });

    if (!response.ok) {
        throw await buildError(response, "Request failed");
    }

    return response.json();
}

async function buildError(response, fallbackMessage) {
    try {
        const body = await response.json();
        return new Error(body.detail || `${fallbackMessage}: HTTP ${response.status}`);
    } catch {
        return new Error(`${fallbackMessage}: HTTP ${response.status}`);
    }
}