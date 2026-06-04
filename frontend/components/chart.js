function pickNumericSeries(records) {
    const priorityKeys = ["close", "Close", "price", "Price", "open", "Open", "high", "High", "low", "Low"];

    for (const key of priorityKeys) {
        const values = records.map(r => r.values?.[key]).filter(v => typeof v === "number");
        if (values.length > 0) {
            return key;
        }
    }

    for (const record of records) {
        const entries = Object.entries(record.values || {});
        for (const [key, value] of entries) {
            if (typeof value === "number") {
                return key;
            }
        }
    }

    return null;
}

export function renderChart(canvas, records, existingChart) {
    if (existingChart) {
        existingChart.destroy();
    }

    const metricKey = pickNumericSeries(records);

    if (!metricKey) {
        const ctx = canvas.getContext("2d");
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        return null;
    }

    const labels = [...records].reverse().map(r => r.businessDate);
    const values = [...records].reverse().map(r => r.values?.[metricKey] ?? null);

    return new Chart(canvas, {
        type: "line",
        data: {
            labels,
            datasets: [
                {
                    label: metricKey,
                    data: values,
                    borderColor: "#01696f",
                    backgroundColor: "rgba(1, 105, 111, 0.14)",
                    borderWidth: 2,
                    tension: 0.25,
                    fill: true,
                    pointRadius: 2,
                    pointHoverRadius: 4
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: true
                }
            },
            scales: {
                x: {
                    ticks: {
                        maxRotation: 0,
                        autoSkip: true
                    }
                },
                y: {
                    beginAtZero: false
                }
            }
        }
    });
}