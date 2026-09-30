# v25 — Regime-Aware Dynamic TSMOM Research Protocol

Frozen on 2026-10-01 before any v25 portfolio result was evaluated. v25 tests one prespecified
extension of the rejected v24 signal. Its research hypothesis is that short trend has positive
expectancy primarily in broad risk-off regimes and should receive less capital in ordinary
regimes. v25 changes only side-specific signal scaling and gross budgets. It does not change the
v24 signal, universe, train calibration, transaction costs, borrow costs or base risk model.

## Evidence status

- Train: 2008-01-02 through 2016-12-30.
- Reused development: 2017-01-03 through 2024-12-31.
- The 2022 result motivated this hypothesis and is not confirmatory evidence.
- No historical period in v25 is a fresh holdout.
- A passing historical gate authorizes only a frozen prospective study. Orders remain disabled.

The source remains the frozen 45-ETF v17 panel with SHA-256
`82347fef112a5f04dc2b5accf947f362eefe1a0a89f1c59bf143a369ab63e32e`. The v24 signal calibration
must reproduce slope `5.1513871248276005e-05` and digest
`fd015ea2c63e5ca7952585fb7c50d88d6ebd9f18fe5bdf7a9fe01410dab348e3`.

## Frozen v24 signal

Keep every v24 feature unchanged:

- 3/6/12-month volatility-normalized momentum weighted 25%/35%/40%;
- skip the latest 21 sessions;
- per-asset rolling 252-session z-score using prior observations only, with 126 minimum;
- dynamic threshold equal to the prior rolling 70th percentile of absolute z-score;
- symmetric standardized 50/200-session moving-average-gap confirmation;
- `tanh(z)` position-strength mapping;
- 8% annualized volatility floor and cross-sectional inverse-volatility bound; and
- the shared causal 1.0/0.7/0.4 portfolio risk scaler from v24.

The underlying signal remains exactly odd under joint reversal of z-score and trend confirmation.

## Frozen market regime

At decision close `t`, classify the next-session portfolio as risk-off only when all three
conditions hold:

```text
SPY close(t) < SPY MA200(t)
SPY 252-session total return(t) < 0
SPY 20-session annualized realized volatility(t)
    > prior trailing-252-session 70th percentile
```

The volatility percentile is shifted one session and requires 60 observations. All other sessions
are risk-on. The detector is binary and there is no parameter search, hysteresis rule or
asset-specific regime.

## Frozen conditional side treatment

Apply the same v24 signal to every asset, then use the market regime as follows:

| Regime | Long signal multiplier | Short signal multiplier | Long gross cap | Short gross cap |
|---|---:|---:|---:|---:|
| Risk-on | 1.0 | 0.5 | 100% | 25% |
| Risk-off | 1.0 | 1.0 | 50% | 100% |

The shared v24 portfolio risk scaler multiplies both side caps after the regime-specific cap is
selected. The portfolio retains a 100% total gross cap. The absolute net cap is 100% so it does not
silently undo the conditional side budgets.

## Frozen portfolio and costs

- Same 45 ETFs and eligibility rules as v24.
- Rebalance every 10 sessions.
- 100% total gross cap; 10% name cap; 25% ordinary turnover cap.
- 0.10% ADV participation at USD 100,000 research NAV.
- 8% annualized portfolio volatility cap.
- Same macro-factor and sleeve caps as v24.
- Same spread, slippage, square-root impact and 1% annual short-borrow proxy.
- Liquidity-limited cap reductions execute the maximum feasible risk reduction and disclose any
  temporary residual rather than assuming an impossible fill.

Relative-strength alpha, credit removal and universe changes are intentionally excluded. They are
separate hypotheses and require separate frozen protocols.

## Required attribution

Compare v25 with the committed v24 baseline on overall Sharpe, CAGR, drawdown, turnover, SPY beta,
R-squared, concentration, long and short expectancy, and long and short Sharpe. Report those book
metrics separately in risk-on and risk-off observations for train, reused development and 2022.
Also report yearly, sleeve and fixed-regime contributions, risk-off frequency, and every constraint
ratio.

## Historical research gate

### Primary

- train and reused-development net Sharpe above 0.50;
- train and reused-development CAGR positive; and
- train and reused-development maximum drawdown at least -15%.

### Robustness

- frozen-trade doubled-transaction-cost reused-development Sharpe above zero;
- one-session signal-and-regime delay reused-development Sharpe above zero; and
- frozen-trade state-dependent-cost reused-development Sharpe above zero.

### Conditional-short hypothesis

- risk-off short-book annualized net expectancy and Sharpe are positive in both train and reused
  development;
- full-period short-book annualized net expectancy is nonnegative in both train and reused
  development;
- full-period long-book annualized net expectancy is nonnegative in both windows; and
- at least 20 risk-off sessions occur in each window so the conditional result is reportable.

### Structure and operation

- top-five absolute contribution share below 75%;
- SPY regression R-squared below 50%;
- at least three sleeves and three of four fixed development regimes contribute positively;
- annual turnover at most 25; and
- all gross, conditional long/short gross, net, name, volatility, factor, sleeve, turnover and
  liquidity constraints pass the engine audit.

Possible decisions are `V25_HISTORICAL_GATE_PASS_PROSPECTIVE_REQUIRED`, `V25_REJECTED`, and
`V25_BLOCKED_V24_CALIBRATION_MISMATCH`. No result may change this protocol or authorize orders.
