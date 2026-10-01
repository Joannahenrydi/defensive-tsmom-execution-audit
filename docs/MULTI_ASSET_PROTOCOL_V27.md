# v27 — Multi-Source Alpha Framework Protocol

Frozen on 2026-10-01 before any v27 alpha calibration or portfolio result was evaluated. v27
changes the alpha hypothesis rather than producing another trend or risk-overlay variant. It runs
two independent research tracks in parallel and permits a combined portfolio only after every
included family passes its own train-only admission gate.

## Evidence status

- Train and family admission: 2008-01-02 through 2016-12-30.
- Reused development audit: 2017-01-03 through 2024-12-31.
- The entire historical sample has been observed in prior research and is not a fresh holdout.
- A passing historical result can authorize only a newly frozen prospective shadow study.
- Orders remain disabled in every v27 state.

The ETF track uses the frozen 45-ETF v17 archive with SHA-256
`82347fef112a5f04dc2b5accf947f362eefe1a0a89f1c59bf143a369ab63e32e`.

## Track A — Trend plus residual mean reversion

### Trend family

Retain the v24 absolute trend family unchanged:

- volatility-normalized 3/6/12-month momentum weighted 25%/35%/40%;
- 21-session skip;
- per-asset prior-window 252-session z-score with 126-session minimum;
- causal prior 70th-percentile absolute-z activation threshold;
- standardized 50/200-session moving-average-gap confirmation;
- `tanh(z)` mapping; and
- prior 60-session volatility with an 8% annual floor and 1.5x cross-sectional bound.

### Residual mean-reversion family

Use the four v26 macro groups: growth, rates, real assets and FX. For each asset and session,
construct an equal-weight return proxy from the other eligible assets in the same group. Require at
least two peers. Estimate the asset's beta to that leave-one-out proxy over the prior 60 sessions,
with 40 observations minimum, and shift beta by one session. Define:

```text
residual_return_i,t = return_i,t - beta_i,t-1 * peer_group_return_i,t
residual_20_i,t = sum(residual_return_i,t-19:t)
```

Standardize `residual_20` per asset against its prior 252 sessions with 126-session minimum. Clip z
scores to [-5, 5]. Activate only when absolute z exceeds its prior rolling 70th percentile and map:

```text
mean_reversion_signal = -tanh(residual_z)
```

Divide by the same effective volatility used by trend. Information through the decision close may
affect the next session's holdings. No current or future return may enter beta or standardization
parameters.

### Family admission and Track-A blend

Calibrate each family to five-session forward returns using completed labels ending inside train.
The zero-intercept slope must be positive; a negative family is rejected rather than sign-flipped.
Residual mean reversion must also satisfy:

- standalone train net Sharpe above zero under the frozen portfolio construction;
- frozen-trade doubled-transaction-cost train Sharpe above zero; and
- absolute pooled train correlation between calibrated trend and mean-reversion scores below 0.75.

If both families pass, evaluate one Track-A blend. Because carry is absent from Track A, normalize
the intended 40/30 allocation across admitted families:

```text
track_a_score = (4 / 7) * calibrated_trend + (3 / 7) * calibrated_mean_reversion
```

No alternative trend/MR weight is searched. Reused development is read only after Track A passes
train admission.

## Track B — futures term-structure carry

ETF cash distributions, expense ratios and price-derived pseudo-yields are prohibited as carry.
Track B requires expiry-specific futures settlement history and point-in-time contract metadata:

- `data/futures/contracts_daily.parquet`;
- `data/futures/contracts_metadata.csv`.

The files must pass the existing v23 contract, curve-depth, date, coverage and metadata audit. At
least 12 roots in at least three sleeves must pass. Each admitted root must have two simultaneously
observed expiries on at least 60% of sessions. Carry will be the annualized, direction-corrected
front-to-next curve roll yield using only contracts known and tradable at that date, with rolls
scheduled before first notice or last trade. Contract multipliers, tick sizes, roll trades, margin,
collateral return and root-specific transaction costs are mandatory for a portfolio backtest.

If these inputs are missing or fail quality checks, Track B is `V27_B_BLOCKED_DATA` and no carry
backtest is run. This is not an alpha rejection.

## Track C — full trend, mean reversion and carry

Track C is admissible only if Track A's trend and mean-reversion families pass train admission and
Track B has admitted contract-level carry data. Its sole blend is:

```text
composite = 0.40 * calibrated_trend
          + 0.30 * calibrated_mean_reversion
          + 0.30 * calibrated_futures_carry
```

The optional 50/25/25 sensitivity is reserved for a separately frozen future protocol. It is not
run in v27. If Track B is blocked, Track C is `V27_C_NOT_RUN_CARRY_DATA_BLOCKED`.

## Frozen portfolio construction

Use the v26 engine and four causal group risk budgets:

- previous 60 sessions for group-proxy covariance;
- equal 25% proxy risk-contribution targets, 10–40% group-budget bounds;
- 10-session rebalance, 100% gross, 100% absolute net and 10% name caps;
- 25% ordinary turnover and 0.10% ADV participation at USD 100,000 research NAV;
- 8% annual volatility cap and existing macro-factor caps;
- the v24 causal 1.0/0.7/0.4 regime risk scaler;
- positive or negative aggregate alpha is allowed, subject to 100% long and 50% short gross caps;
- absent or sub-threshold alpha remains cash; and
- liquidity-limited reductions execute the maximum feasible trade and disclose every residual
  breach.

Carry must eventually use futures-native costs and margin rather than ETF borrow assumptions. The
ETF Track-A audit retains the existing spread, slippage, square-root impact and 1% annual short
borrow proxy.

## Required evidence

- family calibration, observations, correlation, directional accuracy and artifact digest;
- trend/MR pooled and daily cross-sectional correlation;
- standalone trend, standalone MR and Track-A train metrics;
- Track-A development metrics only after train admission;
- long/short, source counterfactual, year, risk-group and fixed-regime attribution;
- frozen-trade doubled costs, one-session signal delay and state-dependent costs;
- turnover, transaction and borrow costs, ADV participation, concentration, beta, capacity and
  every operational breach;
- 2022 and 2023 shown separately; and
- Track-B data-gate and Track-C disposition.

## Historical gates

An evaluated Track-A candidate requires train and reused-development net Sharpe above 0.50, CAGR
positive, maximum drawdown at least -15%, all three robustness Sharpe values above zero, SPY
R-squared below 50%, top-five contribution share below 75%, at least three positive risk groups and
three positive fixed regimes, and every operational constraint to pass.

Possible final states include `V27_A_REJECTED_FAMILY_ADMISSION`, `V27_A_REJECTED_PORTFOLIO_GATE`,
`V27_A_HISTORICAL_GATE_PASS_PROSPECTIVE_REQUIRED`, `V27_B_BLOCKED_DATA`,
`V27_C_NOT_RUN_CARRY_DATA_BLOCKED`, and `V27_C_HISTORICAL_GATE_PASS_PROSPECTIVE_REQUIRED`.
