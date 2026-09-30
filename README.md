# Defensive Time-Series Momentum Research

A frozen, cost-aware study of absolute time-series momentum across 45 liquid cross-asset ETFs.
The project asks whether a simple defensive trend rule can retain positive performance across a
training sample and a reused development audit without parameter search or access to the locked
holdout.

> **Status: DEVELOPMENT ACCEPTED; LOCKED TEST NOT EVALUATED.** The candidate passed its
> prespecified development progression gate, failed the stricter 5% CAGR promotion gate, and is
> not authorized for paper or live trading. The 2021–2024 holdout remains untouched.

## Research question

Can a fixed 3/6/12-month absolute momentum signal, combined with trend confirmation, a dead zone
and explicit macro risk budgets, produce stable net returns after modeled trading and borrow costs?

This repository evaluates one prespecified candidate rather than selecting the best result from a
parameter sweep.

| Research window | Dates | Role |
|---|---|---|
| Train | 2008-01-02 to 2016-12-30 | Signal calibration and fixed portfolio design |
| Reused development audit | 2017-01-03 to 2020-12-31 | Progression decision; not pristine OOS evidence |
| Locked test | 2021-01-04 to 2024-12-31 | **Not loaded or evaluated** |

## Frozen strategy

The universe contains 45 ETFs spanning equities, rates, credit, metals, commodities and
currencies. For each ETF, the signal is:

```text
momentum = 0.25 × MOM_3m + 0.35 × MOM_6m + 0.40 × MOM_12m
```

Each component skips the most recent 21 sessions. A long signal is retained only above the
200-session moving average; a short signal is retained only below it. Signals with absolute value
below 0.25 are set to zero, then scaled by trailing 60-session volatility.

The portfolio rebalances every 10 sessions with an 8% annual volatility target, 100% gross cap,
10% name cap, 60% net cap, turnover and liquidity constraints, and macro factor and sleeve risk
budgets. The cost model includes spread, slippage, square-root market impact and a short-borrow
proxy. Exact macro neutrality is prohibited because it removes the directional trend exposure the
strategy is designed to earn.

## Results

All figures below are net of modeled transaction and borrow costs.

| Evaluation | Net Sharpe | Net CAGR | Max drawdown | Annual turnover |
|---|---:|---:|---:|---:|
| Train 2008–2016 | **1.210** | **2.45%** | **-5.20%** | 0.201 |
| Development 2017–2020 | **0.927** | **3.60%** | **-9.53%** | 0.611 |
| Frozen trades, 2× transaction cost | **0.923** | **3.59%** | **-9.53%** | 0.611 |
| Signal delayed by one session | **0.984** | **3.20%** | **-7.92%** | 0.581 |

The frozen-cost stress keeps holdings, trades, turnover, gross returns and borrow charges identical
to the development baseline. It only doubles each realized transaction charge. The small change in
Sharpe shows that transaction costs are not the binding constraint for this low-turnover candidate.

Development calendar returns were positive in three of four years: +4.81% in 2017, -1.02% in
2018, +7.39% in 2019 and +3.40% in 2020. The result is therefore not explained solely by the 2020
market regime.

## Robustness and limitations

- A one-session signal delay did not eliminate the development result.
- The frozen-trade 2× transaction-cost stress remained positive with a 0.923 Sharpe.
- The top five ETFs—SPY, LQD, EMB, HYG and MUB—generated **75.5%** of absolute development
  contribution; the comparable train concentration was 83.3%.
- Development long-book contribution was **+15.02%**, while short-book contribution was
  **-0.27%**. The result behaves more like a risk-managed long trend portfolio than a symmetric
  long-short CTA.
- Credit contributed **+7.74%** and equities **+5.96%** during development. The 45-ETF universe
  should not be interpreted as 45 independent sources of alpha.
- The development interval was examined by earlier research rounds. Its 0.927 Sharpe is reused
  evidence, not an unbiased out-of-sample estimate.
- The source is adjusted third-party ETF history rather than an exchange-grade point-in-time
  archive. Historical evidence cannot replace prospective paper execution.

These findings are recorded as
`REVIEW_REQUIRED_CONCENTRATED_LONG_BOOK`. They are disclosed rather than repaired after observing
development because adding concentration penalties, tightening sleeve caps or forcing a stronger
short book at this stage would be another round of development optimization.

## Locked-test discipline

The strategy definition, universe, momentum weights, 21-session skip, 200-day confirmation,
0.25 dead zone, 60-day volatility estimate, 8% volatility target, 10-session rebalance schedule,
risk budgets and cost assumptions are frozen under tag
[`v19-development-freeze-20260927`](https://github.com/Joannahenrydi/defensive-tsmom-research/tree/v19-development-freeze-20260927).

No 2021–2024 performance file exists, `locked_test_evaluated` remains `false`, and paper-order
generation remains disabled. A separate protocol must be frozen before the holdout is read once.
The candidate will not be modified in response to that result.

## Key evidence

- [Research protocol](docs/MULTI_ASSET_PROTOCOL_V19.md)
- [v19 report](reports/cross_asset_v19/REPORT.md)
- [Machine-readable decision](reports/cross_asset_v19/SUMMARY.json)
- [Complete evaluation table](reports/cross_asset_v19/evaluation.csv)
- [Asset attribution](reports/cross_asset_v19/asset_attribution.csv)
- [Yearly attribution](reports/cross_asset_v19/yearly_attribution.csv)
- [Sleeve attribution](reports/cross_asset_v19/sleeve_attribution.csv)
- [Long/short attribution](reports/cross_asset_v19/long_short_attribution.csv)
- [Drawdown-regime attribution](reports/cross_asset_v19/drawdown_regime_attribution.csv)
- [Contribution concentration](reports/cross_asset_v19/contribution_concentration.csv)

## Reproduction

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[alpaca,data,dev]'
pytest -q
ruff check data features models portfolio execution risk backtest live scripts tests
```

Collect the cross-asset ETF panel and run the frozen v19 evaluation:

```bash
python -m scripts.collect_cross_asset_etfs_v17 \
  --output output/cross_asset_etfs_v17 --start 2007-01-01 --end 2025-01-01
python -m scripts.evaluate_cross_asset_v19
```

The evaluator reads only the train and reused-development windows. It does not import or evaluate
the locked-test window.

## Repository map

- `scripts/evaluate_cross_asset_v19.py`: frozen signal, stress tests and attribution pipeline.
- `backtest/`: portfolio accounting, holding drift and walk-forward infrastructure.
- `portfolio/`: risk-budgeted construction and cost-aware optimization.
- `execution/`: commission, spread, slippage, impact and borrow models.
- `risk/`: fail-closed promotion rules.
- `reports/cross_asset_v19/`: reproducible v19 evidence and decision artifacts.
- `tests/`: look-ahead, cost-repricing, attribution and portfolio-control tests.

## Research lineage

<details>
<summary>Earlier experiments retained for auditability</summary>

The project began with U.S. equity residual and Kalman alpha research, then moved to cross-asset
trend after the equity signals failed net-of-cost promotion gates. v13 identified that exact macro
neutrality removed the intended trend exposure. v15 established the profitable time-series trend
baseline. v16–v18 improved training results but weakened in development, so their additional
cross-sectional and ensemble components were rejected. v19 returned to absolute momentum and
changed only the prespecified defensive construction.

| Experiment | Train net Sharpe | Development net Sharpe | Decision |
|---|---:|---:|---|
| v13 exact-neutral trend | -0.444 | -0.715 | Rejected |
| v13 risk-budgeted trend | 0.726 | 0.638 | Rejected: drawdown |
| v15 time-series trend | 0.688 | 0.547 | Rejected: return gate |
| v16 trend ensemble | 0.865 | 0.431 | Rejected: instability |
| v18 expanded universe | 0.823 | 0.212 | Rejected: instability |

- [v13–v18 consolidated report](reports/cross_asset_v13_v18/REPORT.md)
- [Research ladder](reports/cross_asset_v13_v18/research_ladder.png)
- [Archived equity research](reports/equity_final/REPORT.md)

</details>

Historical backtests are research evidence, not a guarantee of future performance.
