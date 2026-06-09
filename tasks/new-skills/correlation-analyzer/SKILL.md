---
name: correlation-analyzer
description: "Use when analyzing relationships between variables. Trigger: correlation, relationship, association, covariance, what correlates with, feature relationship."
license: MIT
---
# Correlation Analyzer

## When to use
Find and visualize relationships between numeric variables.

## Workflow
1. **Load data** — select numeric columns.
2. **Compute** — Pearson, Spearman, and Kendall correlation matrices.
3. **Visualize** — heatmap with annotated values, top-N bar chart.
4. **Flag** — pairs with |r| > 0.7 (strong), 0.4-0.7 (moderate), potential multicollinearity.
5. **Context** — explain what each strong correlation means in domain terms.

## Output
Correlation report with heatmap, top relationships, and multicollinearity warnings.