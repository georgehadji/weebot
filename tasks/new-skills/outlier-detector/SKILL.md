---
name: outlier-detector
description: "Use when finding anomalies or outliers in data. Trigger: outlier, anomaly, unusual, extreme values, detect abnormal."
license: MIT
---
# Outlier Detector

## When to use
Identify and explain outliers in numeric data.

## Workflow
1. **Load data** — read numeric columns from the dataset.
2. **Detect** using multiple methods: IQR (1.5x), Z-score (>3), isolation forest.
3. **Visualize** — box plots and scatter plots for each flagged column.
4. **Explain** — for each outlier, note the value, how many std devs from mean, and potential causes.
5. **Recommend** — suggest whether to keep, investigate, or remove.

## Output
Outlier report with visualizations and per-outlier explanations.