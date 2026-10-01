# v32 — Trend, Carry and Fundamentals Integration Protocol

Frozen on 2026-10-01 before v30 or v31 could pass admission. v32 is an integration study, not a
third search over the same historical sample. It may run only after futures trend, futures carry
and point-in-time equity fundamentals each pass their own unchanged family and standalone
portfolio gates.

## Inputs

- v30 futures trend sleeve;
- v30 futures carry sleeve; and
- v31 market/sector-neutral fundamental equity sleeve.

A blocked or rejected family is omitted from v32 by stopping the experiment. It is not replaced by
an ETF proxy, restated fundamental value, inverted rejected signal or a newly tuned price feature.

## Combination

The three sleeves retain their own instruments, costs and constraints. They are combined at the
portfolio level rather than by ranking futures and stocks in one cross-section. Frozen ex-ante
volatility budgets are 40% trend, 30% carry and 30% fundamentals. Use trailing 60-session sleeve
covariance shifted one session, an 8% portfolio volatility cap and cash fallback. There is no
historical optimization of sleeve weights.

The allocator must report intended and realized risk contribution, cross-sleeve covariance,
margin and cash usage, collateral return, turnover, cost, beta and liquidity. It may scale all
sleeves proportionally to restore a portfolio constraint; it may not silently change their relative
alpha weights.

## Admission and validation

Historical evidence is reused development, not a new holdout. Require net Sharpe above 0.50,
positive CAGR, maximum drawdown at least -15%, positive frozen-trade 2x-cost, one-session-delay and
state-dependent-cost Sharpe, positive contribution from all three families, at least three positive
asset sleeves, top-five contribution below 75%, and no operational breach.

A historical pass freezes code, data hashes and configuration, then starts a prospective shadow
period of at least six months. No historical pass authorizes capital or broker orders.

Possible states include `V32_NOT_RUN_COMPONENT_BLOCKED`, `V32_NOT_RUN_COMPONENT_REJECTED`,
`V32_REJECTED_INTEGRATION_GATE`, and `V32_HISTORICAL_GATE_PASS_PROSPECTIVE_REQUIRED`.
