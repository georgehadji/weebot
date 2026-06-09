---
name: exploratory-data-analysis
description: "Use when exploring a new dataset to understand its structure and patterns. Trigger: explore data, profile dataset, data summary, descriptive statistics, EDA."
license: MIT
---
# Exploratory Data Analysis

## When to use
Quickly understand a new dataset — structure, distributions, correlations, and quality.

## Workflow
1. **Load** — read CSV/JSON/Excel with pandas.
2. **Profile** — row count, column types, missing %, unique counts, memory usage.
3. **Distributions** — histograms for numeric columns, value counts for categorical.
4. **Correlations** — heatmap of numeric correlations, flag pairs above 0.7.
5. **Outliers** — flag values beyond 3x IQR per numeric column.
6. **Report** — single-page summary with key findings and data quality score.

## Output
An EDA report with summary statistics, distributions, correlations, and data quality flags.