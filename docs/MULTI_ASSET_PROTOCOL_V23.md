# v23 — Futures-Native Trend + Carry Data Gate

Frozen on 2026-10-01 before inspecting any futures-native result. v22 established that ETF cash
distributions are not an admissible carry family. v23 may proceed only with individual futures
contracts and point-in-time contract metadata.

## Research status

The 2017–2024 ETF period is consumed development evidence. v23 cannot restore holdout status to it.
Historical futures data may be used for model development and walk-forward diagnostics. Promotion
still requires a final frozen specification and prospective evidence.

## Initial roots

- Equity index: ES, NQ, RTY.
- US rates: ZT, ZF, ZN, ZB.
- FX: 6E, 6J, 6B, 6A, 6C.
- Metals and energy: GC, SI, HG, CL, NG.
- Agriculture: ZC, ZW, ZS.

At least three sleeves and 12 roots must pass the data gate. No ETF may be relabelled as a futures
contract. Credit remains outside the initial universe.

## Required daily contract file

One row per actual contract and exchange session with:

```text
date, root, contract, settlement, open, high, low, volume, open_interest
```

`contract` must identify an expiry-specific instrument. Continuous tickers such as `ES=F` are not
valid PnL instruments. Settlement, volume and open interest must be point-in-time observations.

## Required point-in-time metadata file

One row per contract with:

```text
root, contract, sleeve, exchange, currency, multiplier, tick_size,
expiry_date, first_notice_date, last_trade_date
```

For cash-settled contracts without first notice, `first_notice_date` may be blank only when an
explicit `cash_settled=true` field is supplied. Multipliers and tick sizes must be positive.

## Minimum historical quality

- Coverage from at least 2008-01-02 through 2024-12-31.
- At least 95% of expected business sessions have one tradable contract for every admitted root.
- At least two simultaneously observed expiries on 60% of root sessions so curve carry can be
  measured rather than inferred from a back-adjusted series.
- Positive settlement, multiplier and tick size; nonnegative volume and open interest.
- No duplicate contract-date rows.
- Expiry, first-notice and last-trade dates cannot move backward across revisions.
- A contract must never be selected on or after its frozen notice/last-trade buffer.

## Frozen roll and PnL rules after data admission

- Signals may use a separately built continuous series; realized PnL must use the held contract.
- Select the front tradable contract until the next contract's prior-session volume exceeds it,
  subject to a five-business-day first-notice/last-trade buffer.
- Carry is the annualized near/far curve slope adjusted for the contract month gap.
- Record roll trade, roll yield, collateral return, variation margin, commissions, exchange fees,
  bid-ask spread and slippage separately.
- Trend uses the same fixed 3/6/12-month 25%/35%/40% signal as v22. Blend 70% trend and 30% carry.
- Volatility scaling, sleeve risk budgets and margin utilization are enforced at contract level.

## Gate decision

The data audit must run before strategy code. Possible statuses are:

- `V23_DATA_ADMITTED_RESEARCH_NOT_RUN`; or
- `V23_BLOCKED_DATA_UNAVAILABLE` / `V23_BLOCKED_DATA_QUALITY`.

A blocked gate is not a rejected alpha result. It means the claimed futures experiment cannot be
identified from the available data. Orders remain disabled in every data-gate state.

## Current-provider limitation

As verified on 2026-10-01, Alpaca's official Historical API and WebSocket Market Data documentation
list stocks, crypto, options and news, but no futures contract archive. Alpaca credentials alone do
not satisfy this protocol. A separately licensed contract-level source is required.
