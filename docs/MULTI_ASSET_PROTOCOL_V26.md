# v26 — Adaptive Multi-Asset Trend Allocation Protocol

Frozen on 2026-10-01 before any v26 result was evaluated. v26 redefines the strategy objective.
It does not require a symmetric or independently profitable short book. It tests whether absolute
trend, within-group relative strength, conditional cash/short exposure and causal equal-risk group
budgets form a more coherent adaptive allocation strategy.

## Evidence status

- Train: 2008-01-02 through 2016-12-30.
- Reused development: 2017-01-03 through 2024-12-31.
- 2021–2024 and 2022 have already been observed in earlier versions.
- No v26 historical result is a fresh holdout.
- A passing historical gate permits only a newly frozen prospective study. Orders remain disabled.

Use the frozen 45-ETF v17 archive with SHA-256
`82347fef112a5f04dc2b5accf947f362eefe1a0a89f1c59bf143a369ab63e32e`.

## Frozen alpha

### Absolute trend

Retain the complete v24 signal: volatility-normalized 3/6/12-month momentum weighted
25%/35%/40%, 21-session skip, prior-window 252-session z-score, prior 70th-percentile dynamic
threshold, standardized 50/200-session moving-average-gap confirmation and `tanh(z)` mapping.

### Within-group relative strength

Map the six ETF sleeves into four macro risk groups:

- growth: equity and credit;
- rates: rates;
- real assets: metals and commodity; and
- FX: USD proxies.

At each decision close, subtract the cross-sectional median composite momentum of the asset's risk
group. Standardize that residual per asset using the prior 252 sessions with 126 minimum. Activate
the relative signal only when absolute relative z-score exceeds its prior rolling 70th percentile.
Map strength with `tanh(relative_z)`. No moving-average confirmation is added to the relative
signal because it measures cross-sectional leadership rather than absolute direction.

Blend the two admitted components without fitting weights:

```text
combined_signal = 0.50 * absolute_signal + 0.50 * relative_signal
```

Divide by the same v24 effective volatility with the 8% floor and cross-sectional bound. Use the
unchanged v24 train-only calibration slope only for common score scale; its sign may not be reversed.

## Frozen market regime and exposure rules

Reuse the v25 risk-off detector: SPY must be below its 200-session average, its 252-session return
must be negative, and its 20-session volatility must exceed the prior rolling 70th percentile.

- Risk-on: retain positive combined signals; set zero or negative signals to cash.
- Risk-off positive signals: multiply growth-group signals by 0.40 and defensive-group signals
  (rates, real assets and FX) by 1.00.
- Risk-off negative signals: multiply by 0.50 and permit shorts.
- Risk-on short gross cap: 0%.
- Risk-off short gross cap: 50%.
- Long gross cap: 100% in both regimes.

The shared v24 1.0/0.7/0.4 portfolio scaler remains in force and applies to total risk budgets.

## Causal equal-risk group budgets

Build daily equal-weight return proxies for the four macro risk groups. At every rebalance, estimate
their covariance from the previous 60 sessions. Solve nonnegative group weights that minimize
squared deviation of variance risk-contribution shares from 25% each, subject to:

- group weights sum to 100%; and
- each group weight lies between 10% and 40%.

The covariance window is shifted one session. The resulting weights become dynamic gross caps for
the four groups. Unused budget remains cash; it is not reassigned to a group without an active
signal. Report both target proxy risk contributions and risk contributions implied by actual ETF
holdings.

## Frozen portfolio and costs

- Rebalance every 10 sessions.
- 100% total gross cap; 100% absolute net cap; 10% name cap.
- 25% ordinary turnover cap and 0.10% ADV participation at USD 100,000 NAV.
- 8% annual portfolio volatility cap.
- Existing macro-factor caps, with the four dynamic risk-group caps replacing the six static sleeve
  gross caps.
- Existing spread, slippage, square-root impact and 1% annual short-borrow proxy.
- Liquidity-limited risk reductions execute the maximum feasible trade and disclose residual cap
  excess.

## Required comparison and attribution

Compare v24, v25 and v26 on Sharpe, CAGR, drawdown, turnover, SPY beta and R-squared, concentration,
long and short expectancy, yearly return, and contribution by the four risk groups. Report 2022 and
2023 separately. Also report risk-on/risk-off exposure, cash share, dynamic group budgets, target
proxy risk contributions, actual-holdings risk contributions and every operational constraint.

## Historical research gate

### Primary

- train and reused-development net Sharpe above 0.50;
- train and reused-development CAGR positive; and
- train and reused-development maximum drawdown at least -15%.

### Robustness

- frozen-trade doubled-transaction-cost development Sharpe above zero;
- synchronized one-session signal/regime/budget delay development Sharpe above zero; and
- frozen-trade state-dependent-cost development Sharpe above zero.

### Diversification

- development top-five absolute contribution share below 75%;
- development SPY regression R-squared below 50%;
- at least three of four risk groups contribute positively in development;
- at least three of four fixed development regimes contribute positively;
- mean absolute actual risk-contribution deviation from the 25% group target is at most 10
  percentage points; and
- no group's mean actual risk-contribution share exceeds 50%.

### Operational

- annual turnover at most 25; and
- all total gross, conditional long/short gross, net, name, volatility, factor, dynamic group,
  turnover and liquidity constraints pass the engine audit.

Possible decisions are `V26_HISTORICAL_GATE_PASS_PROSPECTIVE_REQUIRED`, `V26_REJECTED`, and
`V26_BLOCKED_INPUT_OR_RISK_BUDGET_FAILURE`. Orders remain disabled in every state.
