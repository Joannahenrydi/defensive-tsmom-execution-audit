# Futures-Native Follow-Up Specification

This document defines what would be required to test whether futures improve the failed ETF short
book. It is a research specification, not evidence that a futures implementation works.

## Why a new study is required

The v20.1 borrow-free counterfactual keeps ETF returns and simply removes borrow. That isolates the
financing question, but it cannot reproduce futures carry, basis, roll, collateral return, margin or
contract-specific execution. A futures claim therefore requires contract-level data and a separate
model.

## Initial liquid universe

- Equity index: ES, NQ and RTY.
- Rates: 2Y, 5Y, 10Y and Ultra/30Y Treasury futures.
- Metals and energy: GC, SI, CL, NG and HG.
- Agriculture: ZC and ZW.
- Currencies: 6E, 6J, 6B and DX where licensing and liquidity permit.

Credit ETF exposures do not have a simple one-for-one listed-futures replacement. They must either
remain outside the futures sleeve or be studied with separate credit-index instruments and data.

## Data and return construction

1. Store every individual contract with exchange timestamp, settlement, volume, open interest,
   multiplier, tick size, first-notice date and last-trade date.
2. Select tradable contracts using only information available at the prior settlement.
3. Build adjusted continuous series only for signals. Compute PnL from the actual held contract and
   record the explicit roll trade.
4. Freeze the roll rule before evaluation: volume/open-interest crossover subject to a fixed
   first-notice buffer.
5. Include collateral yield, variation margin, commissions, bid-ask spread, slippage, roll cost and
   exchange fees. Do not reuse the ETF borrow proxy.

## Required attribution

- Standalone long and short net expectancy and Sharpe.
- PnL by asset, sleeve, year and contract.
- Trend PnL separated from carry/roll and collateral return.
- Market beta, duration beta and USD beta for each book.
- Margin utilization, liquidity participation and stress slippage.
- A 2022 historical diagnostic labelled reused evidence, never a fresh holdout.

## Promotion discipline

The 2021–2024 ETF holdout is consumed. It cannot select futures parameters. Historical futures data
may support research and walk-forward diagnostics, but promotion requires a specification frozen
before a new prospective period. The short book must show positive net expectancy and positive net
Sharpe on its own after all futures costs. Until that happens, paper and live orders remain disabled.
