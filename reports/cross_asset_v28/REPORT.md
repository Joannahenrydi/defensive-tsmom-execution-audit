# v28 Cross-Asset OHLCV Information Decomposition

## Decision

**V28_REJECTED_STANDALONE_TRAIN**

The three OHLCV hypotheses were frozen before evaluation. Current-session bars affect only the
next session. Every feature was risk-group residualized and standardized with prior observations.

| Family | Five-day slope | Mean rank IC | ICIR | Positive years | Decision |
|---|---:|---:|---:|---:|---|
| overnight_gap_reversal | 0.00002160 | 0.0055 | 0.0264 | 6/8 | REJECTED_ADMISSION_RANK_OR_DIVERSIFICATION_CAP |
| intraday_reversal | 0.00002124 | 0.0064 | 0.0313 | 6/8 | REJECTED_STANDALONE_PORTFOLIO_GATE |
| volume_shock_reversal | 0.00001126 | 0.0055 | 0.0280 | 6/8 | REJECTED_STANDALONE_PORTFOLIO_GATE |

Statistically admitted families: **intraday_reversal, volume_shock_reversal**.
Portfolio-admitted families: **none**.
Reused-development portfolio evaluated: **False**.

| Train standalone family | Net Sharpe | Frozen-trade 2x-cost Sharpe |
|---|---:|---:|
| intraday_reversal | -0.053 | -0.071 |
| volume_shock_reversal | cash / undefined | cash / undefined |

An undefined Sharpe denotes an all-cash optimizer result: after calibrated expected return and
costs, the frozen objective found no trade with positive net value. It is a failed admission, not
missing performance.

No rejected feature was sign-flipped, assigned a different horizon or repaired after viewing its
train statistics. Orders remain disabled.
