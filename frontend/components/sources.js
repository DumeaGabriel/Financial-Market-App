export async function loadSources(baseUrl, offset = 0, limit = 10) {
    const url = `${baseUrl}/data-sources?offset=${offset}&limit=${limit}`;
    const response = await fetch(url);

    if (!response.ok) {
        throw new Error(`Failed to load data sources: HTTP ${response.status}`);
    }

    return response.json();
}