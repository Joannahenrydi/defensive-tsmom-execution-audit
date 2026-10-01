# v31 — Trend and Point-in-Time Fundamental Alpha Protocol

Frozen on 2026-10-01 before licensed SF1 data or any v31 result was read. v31 tests whether
as-reported accounting information adds an independent market-neutral equity sleeve to the
cross-asset trend sleeve. Signals from different instruments are not rank-averaged together.

## Evidence status

- Fundamental train: 2018-01-02 through 2022-12-30.
- Fundamental reused development: 2023-01-03 through 2024-12-31.
- The trend sleeve retains the v30 dates and rules.
- The historical periods have been inspected in prior work. A pass requires prospective shadow
  evidence and does not authorize orders.

## Point-in-time data gate

Use SEC accession/filed facts or Sharadar SF1 `ARY` observations. Each filing becomes available one
U.S. business day after its filing date. Amendments are new vintages and never overwrite the
earlier state. `MRY`, `MRQ`, fiscal-period-only timestamps and latest-restatement exports are
prohibited. A signal expires 400 calendar days after its source filing.

The v29 coverage gate remains unchanged: 400 unique symbol mappings, 250 names with a train event,
200 names with three train events, eight sectors with ten covered names, and no duplicate
symbol/availability event.

## Fundamental families

The frozen components are profitability, gross profitability, cash profitability, accrual
quality, conservative asset growth and revenue growth. On each session, values are winsorized at
the 1st/99th percentiles and ranked within sector. A sector needs five names and the complete daily
cross-section needs 100 names.

```text
quality = mean(profitability, gross profitability,
               cash profitability, accrual quality)

conservative growth = mean(conservative asset growth, revenue growth)
```

Each family needs at least two available components. The existing v29 21-session train-only IC,
ICIR, annual consistency, slope and standalone net-economics gates apply without relaxation.

## Sleeve construction

The fundamental sleeve is sector and market-beta neutral, cost aware and constrained by name,
turnover and ADV limits. The trend sleeve is the independently admitted futures trend family from
v30. A missing or rejected trend sleeve does not invalidate fundamental research, and a missing or
rejected fundamental sleeve does not change the v30 result.

Only independently admitted sleeves may enter a combined audit. Allocate 60% of ex-ante volatility
to futures trend and 40% to the equity fundamental sleeve, with no weight search. Report each
sleeve's standalone gross/net performance, capital and risk contribution, correlation, beta,
turnover, cost and capacity.

## Gate

Each sleeve and the combination require train and reused-development net Sharpe above 0.50,
positive CAGR, maximum drawdown at least -15%, positive 2x-cost and one-session-delay Sharpe, and
all operational constraints. The equity sleeve must remain within the frozen beta/sector tolerance.
The combined result also requires absolute daily return correlation below 0.75 and positive
contribution from both sleeves.

Possible states include `V31_BLOCKED_PIT_DATA`, `V31_REJECTED_FUNDAMENTAL_ADMISSION`,
`V31_FUNDAMENTAL_ONLY_ADMITTED_TREND_UNAVAILABLE`, `V31_REJECTED_COMBINED_GATE`, and
`V31_HISTORICAL_GATE_PASS_PROSPECTIVE_REQUIRED`.
