export async function loadAssets(baseUrl, offset = 0, limit = 10) {
    const url = `${baseUrl}/assets?offset=${offset}&limit=${limit}`;
    const response = await fetch(url);

    if (!response.ok) {
        throw new Error(`Failed to load assets: HTTP ${response.status}`);
    }

    return response.json();
}