---
name: time-series-forecaster
description: "Use when forecasting future values from time series data. Trigger: forecast, predict future, time series, trend, seasonality, projection."
license: MIT
---
# Time Series Forecaster

## When to use
Forecast future values from time-stamped data.

## Workflow
1. **Load and validate** — confirm datetime column, set frequency, check for gaps.
2. **Decompose** — trend, seasonality, and residual components.
3. **Fit model** — exponential smoothing (Holt-Winters) or simple moving average.
4. **Forecast** — predict next N periods with confidence intervals.
5. **Visualize** — historical + forecast line chart with confidence bands.
6. **Report** — forecast values, expected range, model fit quality (MAPE, RMSE).

## Output
Forecast chart and table with confidence intervals.