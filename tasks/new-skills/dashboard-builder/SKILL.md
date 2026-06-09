---
name: dashboard-builder
description: "Use when building a data dashboard or visual report. Trigger: dashboard, visual report, chart, graph, plot, data visualization report."
license: MIT
---
# Dashboard Builder

## When to use
Create a self-contained HTML dashboard from data.

## Workflow
1. **Load data** — read the dataset, identify key metrics and dimensions.
2. **Design layout** — KPI cards at top, charts in grid below, filters if needed.
3. **Generate charts** — use matplotlib or plotly for each visualization.
4. **Build HTML** — self-contained file with inline CSS, grid layout, and all charts embedded as SVGs or base64 images.
5. **Make responsive** — media queries for mobile.

## Output
A single self-contained HTML file with interactive charts and responsive layout.