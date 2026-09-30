# v23 Futures-Native Data Gate

## Decision

**V23_BLOCKED_DATA_UNAVAILABLE**

The strategy backtest was not run. v23 requires expiry-specific contracts, settlement, volume,
open interest, contract dates, multipliers and tick sizes. Continuous Yahoo-style tickers or ETF
prices cannot satisfy this gate.

## Missing inputs

- `data/futures/contracts_daily.parquet`
- `data/futures/contracts_metadata.csv`

## Quality issues

- Not evaluated because required files are absent.

## Provider finding

Alpaca's official historical and streaming market-data documentation currently lists stocks,
crypto, options and news. It does not expose the contract-level futures archive required here:

- https://docs.alpaca.markets/us/docs/historical-api
- https://docs.alpaca.markets/us/docs/streaming-market-data

Alpaca credentials therefore do not unblock v23. A separately licensed futures history is needed.
This is a data-identification block, not evidence that Trend + Carry fails in futures. Orders remain
disabled.
