# v30 — Futures Trend and True Carry Protocol

Frozen on 2026-10-01 before contract-level futures data, curve signals or v30 results were read.
v30 is the first futures-native alpha study. It does not use ETF distributions, continuous-ticker
price spreads or a synthetic yield as carry.

## Evidence status

- Train: 2010-06-07 through 2016-12-30, subject to the licensed source's actual first date.
- Reused development: 2017-01-03 through 2024-12-31.
- These calendar regimes have been inspected through ETF research and are not called a clean
  holdout merely because the instrument changes.
- Any historical pass authorizes only a newly frozen prospective shadow study.
- Orders remain disabled in every v30 state.

## Data gate

Use expiry-specific CME contracts for the 20 roots frozen in
`RESEARCH_DATA_ONBOARDING.md`. Require official settlement, cleared volume, open interest,
point-in-time definitions, multiplier, tick size, currency, last-trade date and first-notice date
for every physically delivered contract. At least 12 roots across three sleeves must have 95%
session coverage and two eligible expiries on at least 60% of observed sessions.

The portfolio gate additionally requires a documented root-level commission and exchange-fee
schedule, a conservative half-spread/slippage rule, and a margin history or a separately disclosed
conservative margin proxy. Missing market data blocks all research. Missing cost or margin data may
permit alpha diagnostics but blocks portfolio admission.

## Contract selection and returns

For each root and session, order contracts by expiry after excluding contracts inside five U.S.
business days of the earlier of first notice and last trade. Cash-settled equity-index contracts
use last trade. The nearest two remaining contracts form the curve.

Strategy PnL is always calculated on an identified contract held from the prior close. When the
front contract changes, its return is measured from the new contract's own prior settlement to its
current settlement. The price-level jump between two different contracts is never booked as PnL.
Roll turnover and roll costs are explicit.

## Alpha families

Trend uses the root excess-return index produced by the causal front-contract rule:

```text
trend = 0.25 * momentum_3m_skip_21
      + 0.35 * momentum_6m_skip_21
      + 0.40 * momentum_12m_skip_21
```

It is divided by prior 60-session volatility with an 8% annual floor.

Long curve carry is positive in backwardation and negative in contango:

```text
carry = log(front settlement / next settlement)
        * 365.25 / (next expiry - front expiry in days)
```

Carry is standardized per root using the prior 252 sessions with 126 observations minimum and
clipped to [-5, 5]. Both signals observed at a settlement can affect positions no earlier than the
next session.

## Train-only family admission

Each family predicts 21-session forward root excess return using completed train labels. Require a
positive zero-intercept slope, positive mean daily rank IC, ICIR above 0.02, and positive standalone
train Sharpe after futures-native costs. A negative family is rejected rather than sign-flipped.
Admitted trend and carry must have absolute daily IC correlation below 0.75.

If both pass, the only permitted blend normalizes the previously frozen 40/30 allocation:

```text
v30 score = (4 / 7) * calibrated trend + (3 / 7) * calibrated carry
```

No alternative signal weight, lookback, roll buffer or standardization window is searched.

## Portfolio and gate

Use volatility-scaled root positions, sleeve risk budgets, 10-session rebalance, a 10% root risk
cap, an 8% portfolio volatility cap and cash fallback. Gross, margin, liquidity and concentration
must remain within documented limits. Collateral interest, commissions, exchange fees, half-spread,
slippage and rolls are included. No ETF borrow charge is applied to futures shorts.

Historical admission requires train and reused-development net Sharpe above 0.50, positive CAGR,
maximum drawdown at least -15%, positive frozen-trade 2x-cost and one-session-delay Sharpe, at least
three positive sleeves, top-five contribution share below 75%, and no operational breach.

Possible states include `V30_BLOCKED_FUTURES_DATA`, `V30_ALPHA_DIAGNOSTICS_ONLY_COST_DATA_BLOCKED`,
`V30_REJECTED_FAMILY_ADMISSION`, `V30_REJECTED_PORTFOLIO_GATE`, and
`V30_HISTORICAL_GATE_PASS_PROSPECTIVE_REQUIRED`.
