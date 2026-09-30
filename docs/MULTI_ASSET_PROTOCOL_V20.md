# v20 — Locked Short-Book and State-Dependent Execution Audit

Frozen on 2026-10-01 before any v20 access to the 2021–2024 holdout. This protocol evaluates the
existing v19 defensive time-series momentum portfolio exactly once. It does not search parameters,
change the strategy, or select among candidates after observing holdout results.

## Research question

The audit answers two separate questions:

1. Does the frozen v19 portfolio retain positive performance in the untouched holdout under both
   its original cost model and a causal state-dependent execution-cost stress?
2. Does the short book demonstrate standalone positive expectancy after allocated transaction costs
   and borrow charges, especially during the 2022 rate-hiking regime?

The first question concerns total-portfolio evidence. The second determines whether the strategy
can be described as a symmetric long-short CTA. Passing one does not imply passing the other.

## Immutable source and research windows

- Source: the frozen 45-ETF v17 panel.
- Required source SHA-256: `82347fef112a5f04dc2b5accf947f362eefe1a0a89f1c59bf143a369ab63e32e`.
- Train: 2008-01-02 through 2016-12-30.
- Reused development audit: 2017-01-03 through 2020-12-31.
- One-time locked test: 2021-01-04 through 2024-12-31.

The v19 train calibration must reproduce slope `6.537825607487585e-06` and digest
`d59984125ff01d469e8b75ded4e674f6a8708b1f066b92d9ce8ef5a744ab9122`. Any mismatch blocks the
run before holdout metrics are written.

## Frozen portfolio specification

Every v19 setting remains unchanged:

- 45-ETF universe and existing eligibility rules.
- 3/6/12-month absolute momentum weights of 25%/35%/40%.
- 21-session momentum skip, 200-session trend confirmation and 0.25 dead zone.
- 60-session volatility scaling and train-only zero-intercept calibration.
- Rebalance every 10 sessions.
- 8% annual volatility cap, 100% gross cap, 10% name cap and 60% net cap.
- Existing turnover, ADV participation, macro factor and sleeve budgets.
- Original costs: 1 bp half-spread, 1 bp slippage, square-root impact coefficient 0.10 and a 1%
  annual short-borrow proxy.

The audit must import the v19 signal and portfolio functions. It may not duplicate them with altered
constants. Holdings and trades used by every stress are the baseline frozen holdings and trades.

## Causal state-dependent cost stress

The stress reprices the fixed baseline path. It never sends higher costs back into the optimizer.
For each cost realization date, every state variable is based on information available by the prior
session close:

- `vol_ratio`: SPY trailing 20-session annualized realized volatility divided by its trailing
  252-session median.
- `liquidity_ratio`: the cross-sectional median of each ETF's dollar volume divided by its trailing
  60-session median dollar volume.
- `drawdown`: SPY prior close divided by the prior running peak minus one.

Missing warm-up ratios default to one. The fixed formulas are:

```text
transaction_multiplier = clip(
    max(1, vol_ratio)
    × max(1, 1 / liquidity_ratio)
    × (1.5 if drawdown <= -10% else 1.0),
    1.0,
    4.0,
)

borrow_multiplier = clip(
    max(1, vol_ratio)
    × (1.5 if drawdown <= -10% else 1.0),
    1.0,
    3.0,
)
```

The baseline transaction charge is multiplied by `transaction_multiplier`; the baseline borrow
charge is multiplied by `borrow_multiplier`. Gross returns, holdings, turnover and trades remain
identical. The report must include average, 95th-percentile and maximum multipliers and reconcile
each stressed net return to gross return minus both stressed charges.

## Long/short standalone accounting

Daily gross contribution is split using the sign of the start-of-session weight. Borrow is assigned
entirely to the short book. Transaction cost is allocated using the reconstructed trade:

```text
pretrade_weight[t] = weight[t-1] × (1 + return[t-1]) / (1 + baseline_net_return[t-1])
long_turnover[t] = sum(abs(positive(weight[t]) - positive(pretrade_weight[t])))
short_turnover[t] = sum(abs(negative(weight[t]) - negative(pretrade_weight[t])))
```

Each day's transaction charge is allocated in proportion to long and short turnover. This treats a
sign crossing as a close in one book and an open in the other. Allocated long and short net returns
must add exactly to total portfolio net return within `1e-10`.

For train, reused development, locked test and calendar year 2022, report each book's gross
contribution, transaction cost, borrow cost, arithmetic net contribution, annualized arithmetic
expectancy, volatility, Sharpe, positive-session rate and average gross exposure.

## Prespecified decisions

The locked total portfolio passes only if all conditions hold:

- net CAGR is positive;
- net Sharpe is greater than 0.50;
- maximum drawdown is at least -20%;
- frozen-trade doubled-transaction-cost Sharpe is positive;
- state-dependent transaction-and-borrow-cost Sharpe is positive; and
- every recorded portfolio risk budget remains satisfied.

The short book passes standalone validation only if its net annualized arithmetic expectancy and
net Sharpe are both positive in train, reused development and locked test. The 2022 result is a
diagnostic, not a separate selection gate.

Possible conclusions are deliberately separate:

- `LOCKED_PORTFOLIO_PASS`: the total portfolio passes the locked gate.
- `LOCKED_PORTFOLIO_FAIL`: the total portfolio fails at least one locked gate.
- `SHORT_BOOK_VALIDATED`: the short book passes all three segment gates.
- `LONG_DRIVEN_NOT_SYMMETRIC`: the short book fails any segment gate.

Paper and live orders remain disabled under every v20 outcome. A total-portfolio pass permits only
a separately frozen prospective shadow protocol. A short-book failure prohibits describing the
result as a symmetric long-short CTA.

## One-time execution and post-run discipline

The implementation and its tests must be committed before the holdout is read. The run then writes
one immutable result set, including hashes of this protocol, source data, evaluator source and the
v19 freeze record. No v20 parameter or rule may be changed in response to the holdout. Any future
strategy design must use a new version and a new prospective evaluation period.
