# v21 — Defensive Long-Biased TSMOM Research Protocol

Frozen on 2026-10-01 before any v21 candidate was executed. v21 is a development study motivated
by the failed v20 locked audit. The objective is to test whether asymmetric shorts, a causal fast
risk-off overlay, bounded inverse-volatility sizing and explicit cash fallback repair known
structural weaknesses without changing the underlying trend family.

## Evidence status and research windows

- Train and train-only selection: 2008-01-02 through 2016-12-30.
- Reused development audit: 2017-01-03 through 2024-12-31.
- 2022 is a disclosed diagnostic inside reused development.
- No historical period is described as a fresh holdout.
- Promotion requires a new prospective period after the final specification is frozen.

The source remains the frozen 45-ETF v17 panel with required SHA-256
`82347fef112a5f04dc2b5accf947f362eefe1a0a89f1c59bf143a369ab63e32e`. The source is adjusted
third-party research data rather than an exchange-grade contract archive.

## Frozen core shared by every candidate

- Same 45 ETFs, eligibility, costs and macro loadings as v19/v20.
- 3/6/12-month volatility-normalized momentum weighted 25%/35%/40%.
- Skip the most recent 21 sessions.
- Long entry requires composite momentum above +0.25 and price above its 200-session average.
- Short entry requires composite momentum below the candidate threshold, price below its
  200-session average, and at least two of the 3/6/12-month moves below zero.
- Rebalance every 10 sessions; 8% portfolio volatility cap; 100% gross cap; 10% name cap; 60% net
  cap; 25% turnover cap; 0.10% ADV participation limit at USD 100,000 research NAV.
- A maximum short-gross constraint is enforced directly by the portfolio optimizer.
- Zero-intercept calibration is estimated on train only for each candidate.

## Causal fast risk-off overlay

The overlay may reduce or close a position but cannot create or reverse one. All inputs are
available at the decision close for next-session execution.

Set the asset name-cap multiplier to 0.5 when any condition holds:

- trailing 20-session realized volatility exceeds the prior trailing-252-session 80th percentile;
- current drawdown from the running peak is below -10%; or
- the 50-session moving average is below the 200-session moving average and 21-session momentum is
  negative.

Set the multiplier to zero when drawdown is below -15% or realized volatility exceeds the prior
trailing-252-session 95th percentile. Multiply the alpha score by the same overlay. The percentile
reference is shifted one session so the current observation cannot change its own threshold.

## Bounded inverse-volatility sizing and cash fallback

For candidates with a volatility floor, divide signal by effective annualized volatility:

```text
effective_volatility = max(
    asset_60d_annualized_volatility,
    fixed_volatility_floor,
    cross_sectional_median_volatility / 1.5,
)
```

This imposes both the fixed floor and a maximum 1.5x inverse-volatility scaler relative to the
cross-sectional median. Explicit cash fallback sets the per-asset name-cap multiplier to zero when
neither long nor short entry is active. It does not substitute a neutral asset.

## Prespecified eight-candidate matrix

| Candidate | Short threshold | Fast overlay | Vol floor | Explicit cash fallback | Short gross cap | Rates sleeve cap |
|---|---:|---:|---:|---:|---:|---:|
| A | -0.40 | No | None | No | 35% | 60% |
| B | -0.40 | Yes | None | No | 35% | 60% |
| C | -0.40 | Yes | 8% | No | 35% | 60% |
| D | -0.40 | Yes | 8% | Yes | 35% | 60% |
| E | -0.50 | Yes | 8% | Yes | 35% | 60% |
| F | -0.40 | Yes | 10% | Yes | 35% | 60% |
| G | -0.40 | Yes | 8% | Yes | 25% | 60% |
| H | -0.40 | Yes | 8% | Yes | 35% | 30% |

Candidate D is the complete base design. E through H each change one dimension relative to D. v19
is reported as a historical control and is not eligible for v21 selection.

## Train-only selection

Every candidate is run over the full history for reporting, but selection uses only train metrics.
A candidate is train-qualified only if:

- net Sharpe is above 0.50, CAGR is positive and maximum drawdown is at least -15%;
- short-book annualized arithmetic expectancy is nonnegative after transaction and borrow costs;
- at least three asset sleeves have positive gross contribution;
- top-five absolute contribution share is below 75%; and
- absolute SPY beta is below 0.20 and SPY regression R-squared is below 50%.

Among qualified candidates, select the highest train Sharpe. Ties within 0.02 select the simpler
candidate in alphabetical order. If none qualifies, no candidate is selected and v21 is rejected.
Development results cannot change this selection.

## Historical research gate for the selected candidate

This gate supports research continuation only, never live promotion. It requires:

### Primary

- reused-development Sharpe above 0.50;
- reused-development CAGR positive; and
- reused-development maximum drawdown at least -15%.

### Robustness

- frozen-trade doubled-transaction-cost development Sharpe above zero;
- one-session-delay development Sharpe above zero; and
- frozen-trade state-dependent-cost development Sharpe above zero.

### Structural

- development top-five absolute contribution share below 75%;
- development short-book annualized expectancy is nonnegative;
- development SPY regression R-squared below 50%;
- at least three asset sleeves have positive development gross contribution; and
- at least three of four fixed development regimes have positive net arithmetic contribution:
  2017–2019, 2020, 2021–2022 and 2023–2024.

### Operational

- annual turnover at most 25;
- all gross, net, name, short-gross, factor, sleeve, turnover and ADV constraints satisfied.

Possible decisions are `V21_HISTORICAL_GATE_PASS_PROSPECTIVE_REQUIRED` and
`V21_REJECTED`. Orders remain disabled under both outcomes.

## Reporting requirements

Report all eight candidates, not only the leader. For each, include train, reused development and
2022 Sharpe, CAGR, drawdown, turnover, long contribution, short contribution and SPY beta. For the
selected candidate also report fixed-cost stresses, yearly and sleeve attribution, top-five
concentration, overlay state frequencies, average long/short exposure and every gate component.

No v21 result may alter this protocol. A failed v21 advances the research program to a separately
frozen trend-plus-carry study rather than a larger search over momentum thresholds.
