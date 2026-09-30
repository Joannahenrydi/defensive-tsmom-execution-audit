# v24 Dynamic Symmetric TSMOM

## Decision

**V24_REJECTED**

v24 applies one causal, prespecified signal to both directions: prior-window z-scoring, a prior
70th-percentile absolute-z threshold, standardized 50/200-day moving-average gap confirmation and
`tanh(z)` sizing. Long and short gross caps are both 50%. The 2017–2024 audit is reused development
evidence; it is not a fresh holdout.

| Segment | Net Sharpe | CAGR | Max DD | Long expectancy | Short expectancy | Long Sharpe | Short Sharpe |
|---|---:|---:|---:|---:|---:|---:|---:|
| Train | 0.266 | 0.69% | -4.59% | 1.12% | -0.39% | 0.466 | -0.279 |
| Reused development | 0.178 | 0.51% | -8.40% | 1.19% | -0.63% | 0.415 | -0.307 |

## Robustness and structure

- Frozen-trade 2x-cost Sharpe: **0.151**.
- One-session signal-and-regime delay Sharpe: **0.250**.
- State-dependent-cost Sharpe: **0.137**.
- Reused-development average long/short gross: **39.37% / 30.62%**.
- SPY beta / R-squared: **0.071 / 17.2%**.
- Largest reused-development dynamic name-cap excess: **0.81%**. The ADV limit prevented immediate liquidation on the affected scaler cuts, so the operational gate failed rather than assuming an impossible fill.
- Failed gate components: **train_sharpe, development_sharpe, train_short_expectancy, development_short_expectancy, train_short_sharpe, development_short_sharpe, train_operational, development_operational**.

In the 2022 diagnostic, the short book earned **2.77%** annualized with Sharpe **1.594**, while the long book earned **-3.16%**. The short hedge worked in that regime but was not large enough to make the portfolio profitable.

## Interpretation

The direction rule is mathematically symmetric, so a negative short book cannot be attributed to
an asymmetric threshold or confirmation rule. It is evidence about this signal on cash ETFs after
borrow and allocated transaction costs. It is not a futures result: contract rolls, carry, margin,
basis and futures execution remain unobserved.

Historical gate passed: **False**. Prospective validation
required: **True**. Orders allowed: **No**.
