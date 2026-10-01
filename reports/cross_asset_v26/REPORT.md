# v26 Adaptive Multi-Asset Trend Allocation

## Decision

**V26_REJECTED**

v26 combines the frozen v24 absolute trend with an equally weighted within-group relative-strength
signal. Risk-on holds positive signals or cash. Risk-off permits half-strength shorts, cuts positive
growth signals to 40%, and retains positive rates, real-assets and FX signals. Four dynamic group
gross budgets target equal ex-ante proxy risk contribution.

| Metric | Train | Reused development |
|---|---:|---:|
| Net Sharpe | -0.023 | 0.665 |
| CAGR | -0.09% | 1.80% |
| Max drawdown | -6.25% | -6.03% |
| SPY beta | 0.030 | 0.036 |
| SPY R-squared | 6.4% | 5.7% |

v26 improves reused-development risk-adjusted performance relative to v25 while reducing SPY
dependence, but it has no positive train evidence. The frozen candidate therefore fails rather than
being promoted from the reused 2017–2024 window.

## Risk-allocation audit

- Development mean absolute actual group risk-contribution deviation from 25%:
  **13.46%**.
- Largest development mean group risk-contribution share:
  **28.15%**.
- Positive development risk groups: **4 / 4**.
- Emergency liquidity overrides: **3** in train
  and **2** in development.
- Maximum development group-cap ratio: **3.73x**;
  maximum name-cap excess: **2.66%**.
- Failed gate components: **train_sharpe, train_cagr, risk_contribution_deviation, train_operational, development_operational**.

The mean group risk shares are close to 25% in aggregate, but the mean absolute deviation at each
rebalance is **13.46%**. That
distinction matters: average allocations conceal unstable point-in-time risk contributions.

## 2022 and 2023

| Version | 2022 net return | 2023 net return |
|---|---:|---:|
| v24 dynamic symmetric | -0.41% | -3.88% |
| v25 regime-aware | -3.07% | 1.42% |
| v26 adaptive allocation | -2.85% | 1.76% |

v26 remains effectively long-only: development short expectancy is
**-0.00%**. The improvement comes from long allocation and lower
equity-beta concentration, not from discovering an independent short alpha.

The 2017–2024 window is reused development evidence. This result cannot validate the model or
authorize orders. Relative strength and risk allocation are assessed together under the frozen v26
portfolio hypothesis; further changes require a new protocol.

Orders allowed: **No**.
