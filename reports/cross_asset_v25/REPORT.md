# v25 Regime-Aware Dynamic TSMOM

## Decision

**V25_REJECTED**

v25 retains the complete v24 signal and changes only side treatment. Risk-on sessions halve
negative scores and cap short gross at 25%. Risk-off sessions use the full short score and a 100%
short cap while limiting long gross to 50%. The common v24 risk scaler still controls total risk.

| Metric | Train | Reused development |
|---|---:|---:|
| Net Sharpe | 0.553 | 0.563 |
| CAGR | 2.48% | 2.63% |
| Max drawdown | -6.56% | -10.53% |
| Long net expectancy | 2.64% | 2.71% |
| Short net expectancy | -0.09% | 0.01% |
| Short Sharpe | -0.624 | 0.081 |

## Conditional-short test

- Train risk-off sessions: **245**; short expectancy:
  **-0.41%**; short Sharpe:
  **-1.251**.
- Reused-development risk-off sessions: **157**;
  short expectancy: **-0.00%**;
  short Sharpe: **-1.067**; average short gross:
  **1.60e-06%**.
- v24 versus v25 total return in 2022: **-0.41% / -3.07%**; in 2023:
  **-3.88% / 1.42%**.
- Failed gate components: **train_risk_off_short_expectancy, development_risk_off_short_expectancy, train_risk_off_short_sharpe, development_risk_off_short_sharpe, train_full_short_expectancy, train_operational, development_operational**.

The regime hypothesis is evaluated on reused data and 2022 helped form it. A positive result would
remain development evidence and require prospective validation. Relative-strength alpha and
universe changes were excluded so this comparison isolates regime conditioning.

Orders allowed: **No**.
