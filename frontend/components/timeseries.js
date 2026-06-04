export async function checkApiHealth(baseUrl) {
    const response = await fetch(`${baseUrl}/health`);

    if (!response.ok) {
        throw new Error(`Health check failed: HTTP ${response.status}`);
    }

    return response.json();
}

export async function fetchAssetDetails(baseUrl, assetId) {
    const response = await fetch(`${baseUrl}/assets/${encodeURIComponent(assetId)}`);

    if (!response.ok) {
        let detail = `Failed to fetch asset details: HTTP ${response.status}`;
        try {
            const body = await response.json();
            if (body.detail) detail = body.detail;
        } catch {}
        throw new Error(detail);
    }

    return response.json();
}

export async function fetchDataSourceDetails(baseUrl, dataSourceId) {
    const response = await fetch(`${baseUrl}/data-sources/${encodeURIComponent(dataSourceId)}`);

    if (!response.ok) {
        let detail = `Failed to fetch data source details: HTTP ${response.status}`;
        try {
            const body = await response.json();
            if (body.detail) detail = body.detail;
        } catch {}
        throw new Error(detail);
    }

    return response.json();
}

export async function fetchTimeSeries({
    baseUrl,
    assetId,
    dataSourceId,
    startBusinessDate,
    endBusinessDate,
    includeAttributes = false
}) {
    const params = new URLSearchParams({
        assetId,
        dataSourceId,
        startBusinessDate,
        endBusinessDate,
        includeAttributes: String(includeAttributes)
    });

    const response = await fetch(`${baseUrl}/data?${params.toString()}`);

    if (!response.ok) {
        let detail = `Failed to fetch data: HTTP ${response.status}`;
        try {
            const body = await response.json();
            if (body.detail) detail = body.detail;
        } catch {}
        throw new Error(detail);
    }

    return response.json();
}