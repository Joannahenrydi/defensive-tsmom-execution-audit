# v28 — Cross-Asset OHLCV Information-Decomposition Protocol

Frozen on 2026-10-01 before any v28 feature statistic or portfolio result was evaluated. v27
rejected 20-session residual mean reversion at its train-only slope gate and could not evaluate
futures carry without contract data. v28 tests whether daily open/close decomposition and volume
dislocation provide independent information in the 45-ETF universe. It does not change trend
windows, risk caps or regime rules.

## Evidence status

- Train and family admission: 2008-01-02 through 2016-12-30.
- Reused development audit: 2017-01-03 through 2024-12-31.
- No historical period is a fresh holdout.
- Orders remain disabled in every state.

Use the hash-locked v17 ETF archive:
`82347fef112a5f04dc2b5accf947f362eefe1a0a89f1c59bf143a369ab63e32e`.

## Frozen feature families

Reconstruct adjusted open, high and low with the same-session adjustment factor
`adjusted_close / raw_close`. Current-session OHLCV is available only after the close and may affect
the next session's holdings.

For each raw feature, subtract the same-session median of its v26 macro risk group. Standardize the
result per asset against the prior 252 sessions with a 126-session minimum. Clip z to [-5, 5],
activate only beyond the prior rolling 70th percentile of absolute z, map with `tanh(z)`, and divide
by the v24 effective volatility.

The only three candidates are:

1. `overnight_gap_reversal`: negative log adjusted-open / prior adjusted-close;
2. `intraday_reversal`: negative log adjusted-close / adjusted-open; and
3. `volume_shock_reversal`: negative same-group residual close-to-close return multiplied by the
   absolute difference between log volume and its prior 60-session median.

No continuation version, alternate horizon, threshold, sign reversal or feature interaction is
searched in v28.

## Train-only family admission

Each feature predicts five-session forward total return. Labels must end inside train. A family
must satisfy all of the following:

- positive zero-intercept pooled slope;
- positive mean daily cross-sectional rank IC;
- rank-IC information ratio at least 0.02;
- at least six positive calendar-year rank ICs, with at least six observed train years;
- standalone train net Sharpe above zero under the frozen portfolio construction; and
- standalone frozen-trade doubled-transaction-cost train Sharpe above zero.

Rank qualified families by train ICIR and admit at most two. A second family is admitted only if
the absolute correlation of its daily train rank-IC series with the first is below 0.75. Failure at
any stage prevents a reused-development portfolio evaluation.

## Frozen blend

Retain the v24 trend family and its train calibration. If one OHLCV family passes, use:

```text
composite = 0.60 * calibrated_trend + 0.40 * calibrated_ohlcv
```

If two pass, divide the 40% OHLCV allocation equally. No alternative blend is evaluated.

## Portfolio and gates

Use the v27 Track-A portfolio unchanged: four causal v26 group budgets, 10-session rebalance, 100%
gross, 100% absolute net, 100% long and 50% short gross caps, 10% name cap, 25% ordinary turnover,
0.10% ADV participation at USD 100,000 NAV, 8% volatility cap, the v24 1.0/0.7/0.4 risk scaler,
existing macro caps and the existing transaction, impact and borrow model. Unused alpha budget is
cash. Every liquidity-limited transition and residual breach is disclosed.

An evaluated blend requires train and reused-development Sharpe above 0.50, positive CAGR, maximum
drawdown at least -15%, positive doubled-cost, one-session-delay and state-cost Sharpe, SPY
R-squared below 50%, top-five contribution share below 75%, at least three positive risk groups,
three positive fixed regimes and full operational compliance.

Required outputs are family qualification, annual IC, daily-IC correlation, standalone train
evidence, admitted-family lock, source counterfactuals, long/short, year, group, regime, cost,
capacity, beta and constraint audits. Possible states are `V28_REJECTED_FAMILY_QUALIFICATION`,
`V28_REJECTED_STANDALONE_TRAIN`, `V28_REJECTED_PORTFOLIO_GATE`, and
`V28_HISTORICAL_GATE_PASS_PROSPECTIVE_REQUIRED`.
