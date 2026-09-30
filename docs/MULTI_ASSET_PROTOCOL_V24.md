# v24 — Dynamic Symmetric TSMOM Research Protocol

Frozen on 2026-10-01 before any v24 signal or portfolio result was evaluated. v24 tests one
prespecified cash-ETF candidate. It asks whether causal standardization and a genuinely odd
long/short mapping repair the short-book weakness found in v20 and v21. It does not search over
thresholds, lookbacks, momentum weights, nonlinear mappings or portfolio caps.

## Evidence status

- Train and train-only calibration: 2008-01-02 through 2016-12-30.
- Reused development audit: 2017-01-03 through 2024-12-31.
- 2022 is a disclosed regime diagnostic inside reused development.
- The 2021–2024 period was consumed by v20 and is not a fresh holdout.
- No historical result can authorize paper or live orders. A passing candidate must be frozen for
  prospective validation.

The source is the frozen 45-ETF v17 panel with required SHA-256
`82347fef112a5f04dc2b5accf947f362eefe1a0a89f1c59bf143a369ab63e32e`. It is an adjusted ETF
research archive, not a futures contract or exchange-grade execution dataset.

## Frozen signal

For each asset, compute the same volatility-normalized 3/6/12-month momentum family used by v19:

```text
component_h(t) = [log(P[t-21]) - log(P[t-h])] / [daily_vol_60(t) * sqrt(h-21)]
composite(t) = 0.25 * component_63 + 0.35 * component_126 + 0.40 * component_252
```

`daily_vol_60(t)` uses returns through `t-1`. Standardize the composite separately for each asset
with the prior rolling 252 sessions, requiring 126 observations:

```text
z(t) = [composite(t) - mean(composite[t-252:t-1])] / std(composite[t-252:t-1])
threshold(t) = q70(abs(z[t-252:t-1]))
```

The rolling mean, standard deviation and 70th-percentile threshold are shifted one session. The
current observation therefore cannot change its own normalization or threshold. Clip `z` to
[-5, 5] only for numerical stability.

Confirm direction with a symmetric standardized moving-average gap:

```text
trend_strength(t) = log(MA50(t) / MA200(t)) / [daily_vol_60(t) * sqrt(150)]
```

The active signal is:

```text
signal(t) = tanh(z(t))
```

only when `abs(z(t)) > threshold(t)` and `sign(z(t)) == sign(trend_strength(t))`; otherwise it is
zero. Every rule is invariant to simultaneous sign reversal of `z` and trend strength. There is no
long-specific or short-specific threshold, confirmation, multiplier or eligibility rule.

## Frozen risk scaling

Divide the active signal by effective annualized volatility:

```text
effective_volatility = max(
    asset_60d_annualized_volatility,
    8%,
    cross-sectional_median_volatility / 1.5,
)
```

This bounds low-volatility leverage. Apply one portfolio-level, causal SPY regime scaler to both
longs and shorts:

- normal: 1.0;
- high volatility or correction: 0.7 when SPY 20-session realized volatility exceeds its prior
  trailing-252-session 80th percentile or SPY drawdown is at most -10%;
- stress: 0.4 when realized volatility exceeds its prior 95th percentile or drawdown is at most
  -15%.

Stress overrides high volatility. The percentile references are shifted one session. The scaler
can change gross risk but cannot change signal direction or relative long/short treatment.

## Frozen portfolio and costs

- Rebalance every 10 sessions.
- 100% gross cap; 50% long-gross cap; 50% short-gross cap; 20% absolute net cap.
- 10% name cap; 25% ordinary turnover cap; 0.10% ADV participation at USD 100,000 research NAV.
- 8% annualized portfolio volatility cap.
- Existing risk-budgeted macro-factor and sleeve caps from v19.
- Existing spread, slippage, square-root impact and 1% annual short-borrow proxy.
- No exact factor neutrality, forced exposure, neutral replacement asset or asymmetric short cap.
- Train-only zero-intercept calibration against five-session forward return. A nonpositive train
  slope blocks the family without reversing it.

An optimizer failure is fail-closed. Independently feasible holdings may be retained; otherwise
the engine may execute a fully costed emergency liquidation. It may not convert an unverified
solver result into a position.

## Prespecified evidence and gates

Report train, reused development and 2022 metrics. Required diagnostics are net Sharpe, CAGR,
maximum drawdown, turnover, long and short net expectancy and Sharpe after allocated transaction
and borrow costs, long and short gross contribution, average long and short exposure, SPY beta and
R-squared, top-five contribution share, yearly results, and contribution from every asset sleeve.

The historical research gate requires all of the following:

### Primary

- train and reused-development net Sharpe above 0.50;
- train and reused-development CAGR positive; and
- train and reused-development maximum drawdown at least -15%.

### Robustness

- frozen-trade doubled-transaction-cost reused-development Sharpe above zero;
- one-session signal-and-regime delay reused-development Sharpe above zero; and
- frozen-trade state-dependent-cost reused-development Sharpe above zero.

### Symmetry and structure

- long and short annualized net expectancy are independently nonnegative in both train and reused
  development;
- long and short standalone Sharpe are independently nonnegative in both train and reused
  development;
- absolute difference between average long and short gross exposure is at most 20 percentage
  points in reused development;
- top-five absolute contribution share is below 75%;
- SPY regression R-squared is below 50%;
- at least three sleeves have positive reused-development gross contribution; and
- at least three of four fixed regimes have positive net arithmetic contribution: 2017–2019,
  2020, 2021–2022 and 2023–2024.

### Operational

- all gross, long-gross, short-gross, net, name, volatility, factor, sleeve, turnover and liquidity
  constraints pass the engine audit; and
- annual turnover is at most 25.

Possible decisions are `V24_HISTORICAL_GATE_PASS_PROSPECTIVE_REQUIRED`, `V24_REJECTED`, and
`V24_BLOCKED_NONPOSITIVE_TRAIN_SLOPE`. Orders remain disabled in every state. If the symmetric
signal still produces negative short expectancy, the conclusion is a cash-ETF instrument/economic
structure failure under this design, not permission to tune a short-specific rule on reused data.
