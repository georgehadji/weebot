---
name: data-cleaning-pipeline
description: "Use when the user asks to clean, normalize, validate, or preprocess data. Trigger keywords: clean data, normalize, validate, preprocess, deduplicate, missing values, outliers, data quality."
license: MIT
---

# Data Cleaning Pipeline

## When to use
The user has a CSV, JSON, or Excel file that needs cleaning before analysis.

## Workflow

1. **Load and profile** — use `python_execute` with pandas to read the file, generate summary stats.
2. **Identify issues:** missing values, duplicates, inconsistent formats, outliers, invalid values.
3. **Report issues** to the user with counts and examples.
4. **Apply cleaning** with user confirmation: fill/drop missing, remove duplicates, standardize formats.
5. **Validate** — re-run profiling to confirm issues are resolved.
6. **Save** cleaned data to a new file with `_cleaned` suffix.

## Tool guidance
- `python_execute`: Use pandas for all data operations. Keep scripts idempotent.
- `file_editor`: Read input files to inspect raw format.

## Output
- Cleaned data file + cleaning report (what was done, counts per action)
