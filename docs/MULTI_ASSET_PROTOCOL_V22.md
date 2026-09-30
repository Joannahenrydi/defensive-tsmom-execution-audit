# v22 — ETF Trend + Distribution-Carry Protocol

Frozen on 2026-10-01 before the v22 carry family was evaluated. v21 showed that structural risk
overlays reduced drawdown but did not create positive short-side expectancy. v22 therefore adds one
prespecified information source rather than changing momentum windows or searching more risk caps.

## Evidence status

- Train and calibration: 2008-01-02 through 2016-12-30.
- Reused development audit: 2017-01-03 through 2024-12-31.
- 2022 remains a disclosed diagnostic inside reused development.
- No historical period is called a fresh holdout. Promotion requires prospective evidence after a
  final freeze.

The source is the same hash-locked 45-ETF archive used by v17–v21. It contains unadjusted close,
adjusted close, dividends and capital-gains distributions. It does not contain futures contracts,
term structures, roll schedules, basis or margin.

## Carry family

For each ETF and decision session, compute the cash distribution yield observed over the trailing
252 sessions:

```text
distribution_yield_t = sum((dividend_t + capital_gain_t) / raw_close_(t-1), 252 sessions)
```

The current session distribution may affect the next-session position. No future distribution is
backfilled. Values below zero are set to zero and single-event yields above 25% are rejected as
data errors.

Convert the trailing yield to a within-sleeve cross-sectional percentile using the frozen equity,
rates, credit, metals, commodity and USD sleeve labels. Require at least three eligible assets in a
sleeve. Center and scale the percentile to [-1, 1], then divide by prior 60-session annualized
volatility. This is an **ETF distribution-carry proxy**, not futures curve carry.

The carry family is admitted only if its zero-intercept five-session forward-return slope estimated
on train is positive. A nonpositive slope rejects v22 without reversing the signal.

## Frozen trend family and blend

Use the v21 candidate-D trend specification unchanged:

- 3/6/12-month momentum weighted 25%/35%/40%, skip 21 sessions;
- long threshold +0.25 and 200-session average confirmation;
- short threshold -0.40, 200-session confirmation and at least two negative horizons;
- causal fast risk-off overlay;
- 8% volatility floor and relative 1.5x inverse-volatility bound.

Calibrate trend and carry separately on train. Combine their expected-return scores once:

```text
expected_return = 0.70 * calibrated_trend + 0.30 * calibrated_distribution_carry
```

The weights are fixed and are not searched. Carry may create a position when the slow trend signal
is zero. The fast risk-off overlay can reduce or close any resulting position but cannot reverse
its sign.

## Portfolio and costs

- Same 45 ETFs and macro metadata.
- Rebalance every 10 sessions; 8% annual volatility cap.
- Gross 100%, name 10%, net 60%, short gross 35%, turnover 25%.
- Rates sleeve 60%; other sleeve and factor budgets unchanged from v21 D.
- 0.10% ADV participation at USD 100,000 research NAV.
- Same spread, slippage, square-root impact and 1% annual ETF-borrow proxy.
- When a risk cap falls faster than the ADV limit allows, execute the maximum feasible reduction,
  disclose the residual name-cap excess and fail the operational gate.

## Historical research gate

All components must pass:

- reused-development Sharpe above 0.50, CAGR positive and maximum drawdown at least -15%;
- frozen-trade doubled-transaction-cost, one-session-delay and state-dependent-cost Sharpe above
  zero;
- short-book annualized expectancy nonnegative after allocated transaction and borrow costs;
- top-five absolute contribution share below 75%;
- SPY regression R-squared below 50%;
- at least three positive sleeves and three of four positive fixed regimes;
- annual turnover at most 25 and every gross, net, name, short-gross, factor, sleeve and ADV
  constraint satisfied.

The only possible positive status is `V22_HISTORICAL_GATE_PASS_PROSPECTIVE_REQUIRED`. It does not
authorize orders. Failure produces `V22_REJECTED` and advances the program to the futures-native
data gate; v22 parameters may not be repaired after reading reused development.

## Required outputs

- Distribution data-quality and sleeve-coverage audit.
- Train calibration for trend and carry, including slope, observations and digest.
- Train, reused development and 2022 metrics.
- Long/short, sleeve, asset, year and fixed-regime attribution.
- Frozen 2x transaction-cost, one-session-delay and state-dependent-cost results.
- Every gate component, residual risk-cap breach and final fail-closed decision.
