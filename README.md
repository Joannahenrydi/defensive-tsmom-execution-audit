# Defensive TSMOM Execution and Short-Book Audit

A one-time locked-holdout evaluation of the frozen 45-ETF defensive time-series momentum strategy,
with standalone long/short accounting and causal state-dependent execution costs.

> **Decision: LOCKED PORTFOLIO FAIL · LONG-DRIVEN, NOT SYMMETRIC.** The frozen strategy remained
> profitable in 2021–2024, but its 0.150 Sharpe did not pass the prespecified 0.50 gate. The short
> book had negative expectancy after transaction and borrow costs. No parameters were changed after
> the holdout was read, and orders remain disabled.

## Why this audit exists

The preceding development study produced a 0.927 net Sharpe but showed that almost all positive
contribution came from the long book. It also used a largely exogenous cost model. This audit was
frozen before accessing 2021–2024 to answer two narrower questions:

1. Does the unchanged portfolio survive a genuinely untouched holdout under harsher,
   state-dependent costs?
2. Does the short book produce standalone positive expectancy after allocated trading costs and
   borrow?

The protocol, evaluator and tests were committed before the one-time locked run.

## Frozen strategy

- 45 liquid ETFs across equities, rates, credit, metals, commodities and currencies.
- Absolute 3/6/12-month momentum weighted 25%/35%/40%, skipping the most recent 21 sessions.
- 200-session trend confirmation and a fixed 0.25 signal dead zone.
- Inverse 60-session volatility sizing.
- 8% annual volatility cap and rebalancing every 10 sessions.
- Fixed gross, net, name, turnover, liquidity, macro-factor and sleeve budgets.
- Spread, slippage, square-root impact and a 1% annual short-borrow proxy.

The signal, portfolio constraints, universe and cost assumptions are identical to the frozen v19
candidate. v20 changes only the audit depth.

## One-time locked result

| 2021–2024 evaluation | Net Sharpe | Net CAGR | Max drawdown | Decision |
|---|---:|---:|---:|---|
| Frozen v19 baseline | **0.150** | **0.51%** | **-11.03%** | Fail: Sharpe below 0.50 |
| Same trades, 2× transaction cost | **0.147** | **0.50%** | **-11.03%** | Stress remains positive |
| Same trades, state-dependent costs | **0.131** | **0.44%** | **-11.22%** | Stress remains positive |

The strategy earned positive returns in three of four locked years:

| Year | Baseline return | Baseline Sharpe | State-cost return | State-cost Sharpe |
|---|---:|---:|---:|---:|
| 2021 | +1.90% | 0.673 | +1.88% | 0.669 |
| 2022 | **-8.93%** | **-1.642** | **-9.15%** | **-1.684** |
| 2023 | +5.64% | 1.484 | +5.62% | 1.476 |
| 2024 | +4.08% | 1.673 | +4.08% | 1.673 |

The 2022 loss is the binding regime failure. The total locked period stayed profitable because the
other three years recovered the drawdown, but the risk-adjusted result was too weak for promotion.

## Short-book teardown

Transaction costs are allocated by reconstructed long and short turnover; borrow is assigned
entirely to the short book. Daily long and short net contributions reconcile exactly to total
portfolio net return.

| Segment | Short net annualized expectancy | Short Sharpe | Average short gross exposure |
|---|---:|---:|---:|
| Train 2008–2016 | -0.05% | -2.734 | 5.09% |
| Reused development 2017–2020 | -0.13% | -0.451 | 6.18% |
| Locked test 2021–2024 | **-0.18%** | **-0.495** | 11.41% |
| Locked 2022 only | **-0.07%** | **-0.125** | 21.53% |

The 2022 short book generated positive gross contribution, but borrow and allocated transaction
costs more than consumed it. The evidence rejects a symmetric long-short CTA interpretation. The
portfolio is better described as a risk-managed long trend strategy with a weak short overlay.

## State-dependent execution stress

All stressed results retain the baseline holdings and trades. Cost multipliers use only information
available by the previous close:

- SPY 20-session realized volatility relative to its trailing 252-session median;
- cross-sectional ETF dollar-volume liquidity relative to trailing 60-session norms; and
- a 1.5× stress factor when prior SPY drawdown is at least 10%.

| Multiplier | Mean | 95th percentile | Maximum |
|---|---:|---:|---:|
| Transaction cost | 1.48× | 2.84× | 4.00× |
| Borrow cost | 1.35× | 2.66× | 3.00× |

Costs are not the primary reason the total portfolio failed: the state-dependent stress reduced
Sharpe by only 0.018. The main weakness is unstable gross performance, particularly in 2022.

## Research decision

The outcome is intentionally fail-closed:

- `LOCKED_PORTFOLIO_FAIL`: locked Sharpe missed the frozen 0.50 threshold.
- `LONG_DRIVEN_NOT_SYMMETRIC`: short-book expectancy and Sharpe were negative in train,
  development and locked test.
- `orders_allowed: false`: neither paper nor live trading is authorized.

The 2021–2024 holdout is now consumed and cannot be reused to tune the strategy. A future candidate
must use a new version and prospective evaluation period. The economically relevant next research
direction is a futures implementation with explicit roll, margin, carry and short-side execution,
rather than trying to repair cash-ETF shorts on the consumed holdout.

## Evidence

- [Frozen v20 protocol](docs/MULTI_ASSET_PROTOCOL_V20.md)
- [Locked audit report](reports/cross_asset_v20/REPORT.md)
- [Machine-readable decision](reports/cross_asset_v20/SUMMARY.json)
- [Portfolio evaluations](reports/cross_asset_v20/evaluation.csv)
- [Long/short metrics](reports/cross_asset_v20/book_metrics.csv)
- [Locked yearly results](reports/cross_asset_v20/locked_yearly.csv)
- [State multiplier summary](reports/cross_asset_v20/state_multiplier_summary.csv)
- [Daily book reconciliation](reports/cross_asset_v20/locked_book_daily.csv)
- [Frozen evaluator](scripts/evaluate_cross_asset_v20.py)
- [Audit tests](tests/test_cross_asset_v20.py)

## Reproduction safeguards

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[alpaca,data,dev]'
pytest -q
ruff check data features models portfolio execution risk backtest live scripts tests
```

The committed reports are the single decision record. Re-running the evaluator is reproduction,
not a new holdout. It must use the frozen source hash recorded in `SUMMARY.json` and must not be
used to change v20 parameters.

Historical backtests are research evidence, not a guarantee of future performance.
