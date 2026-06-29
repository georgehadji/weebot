---
name: data-analysis
description: Analyze data from CSV, Excel, JSON, SQL, and Pandas DataFrames. Covers loading, cleaning, transforming, aggregating, visualizing, and exporting. Use Python (pandas, matplotlib, openpyxl) for analysis and PowerShell for file operations. Triggered for any data processing, spreadsheet manipulation, statistics, or reporting task.
metadata:
  emoji: 📊
  trust: trusted
  provenance:
    origin: human
  requires_toolsets: ["python_execute"]
  fallback_for_toolsets: []
---

# Data Analysis

## File Format Handling

| Format | Library | Read | Write |
|---|---|---|---|
| CSV | `pandas` / `csv` | `pd.read_csv("file.csv")` | `df.to_csv("file.csv", index=False)` |
| Excel (.xlsx) | `openpyxl` / `pandas` | `pd.read_excel("file.xlsx")` | `df.to_excel("file.xlsx", index=False)` |
| JSON | `json` / `pandas` | `pd.read_json("file.json")` | `df.to_json("file.json", orient="records")` |
| SQL | `sqlite3` | `pd.read_sql("SELECT...", conn)` | `df.to_sql("table", conn)` |

## Analysis Pipeline

```
1. LOAD     → pd.read_csv/excel/json
2. CLEAN    → dropna(), fillna(), drop_duplicates(), astype()
3. TRANSFORM → groupby(), merge(), pivot_table(), apply()
4. ANALYZE  → describe(), value_counts(), corr(), agg()
5. OUTPUT   → to_csv/excel, print summary, generate chart
```

## Common Patterns

**Summary statistics:**
```python
df.describe()           # count, mean, std, min, max
df["col"].value_counts() # frequency table
df.corr()               # correlation matrix
```

**Grouping and aggregation:**
```python
df.groupby("category")["value"].agg(["sum", "mean", "count"])
```

**Filtering:**
```python
df[df["col"] > 100]                    # greater than
df[df["col"].isin(["A", "B"])]        # in list
df[df["col"].str.contains("pattern")]  # string match
```

**Merging:**
```python
pd.merge(df1, df2, on="key", how="left")
pd.concat([df1, df2], axis=0)
```

## Visualization

```python
import matplotlib.pyplot as plt
df.plot(kind="bar", x="category", y="value")
plt.savefig("output.png", dpi=150, bbox_inches="tight")
```

## PowerShell for File Operations

```powershell
# List CSV files
Get-ChildItem -Recurse -Filter "*.csv"

# Count rows
(Get-Content "file.csv").Count

# Extract columns
Import-Csv "file.csv" | Select-Object Name, Value | Export-Csv "out.csv"

# Combine CSVs
Get-ChildItem *.csv | ForEach-Object { Import-Csv $_.FullName } | Export-Csv combined.csv
```

## Data Cleaning Checklist

- [ ] Remove duplicate rows: `df.drop_duplicates()`
- [ ] Handle missing values: `df.fillna(0)` or `df.dropna()`
- [ ] Convert types: `df["col"] = df["col"].astype(float)`
- [ ] Trim whitespace: `df["col"] = df["col"].str.strip()`
- [ ] Validate ranges: `assert df["age"].between(0, 120).all()`
