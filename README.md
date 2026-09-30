# Defensive TSMOM Research and Execution Audit

## Current research status: v21 rejected

The prespecified v21 study tested eight structural repairs after the locked v20 failure:
asymmetric short entry, a causal fast risk-off overlay, bounded inverse-volatility sizing, explicit
cash fallback, short-gross caps and a lower rates budget. Selection used 2008–2016 only; 2017–2024
was treated as reused development evidence.

Candidate D was selected by the train-only rule. It remained profitable in reused development, but
failed the full gate:

| v21 selected candidate D | Result |
|---|---:|
| Train Sharpe | 0.688 |
| Reused-development Sharpe | **0.399** |
| Reused-development CAGR | **1.47%** |
| Reused-development max drawdown | **-7.90%** |
| Annualized short expectancy | **-0.69%** |
| Frozen-trade 2x-cost Sharpe | 0.374 |
| One-session-delay Sharpe | 0.405 |
| State-dependent-cost Sharpe | 0.380 |

The fast overlay reduced risk but did not create independent short-side expectancy. It also exposed
an execution conflict: on some risk-off rebalances, the 0.10% ADV limit prevented the requested
name cap from being restored immediately. The engine now executes the maximum feasible reduction,
reports the residual cap excess, and fails the operational gate rather than assuming an impossible
fill. No orders are authorized.

- [Frozen v21 protocol](docs/MULTI_ASSET_PROTOCOL_V21.md)
- [v21 report](reports/cross_asset_v21/REPORT.md)
- [v21 machine-readable decision](reports/cross_asset_v21/SUMMARY.json)
- [Eight-candidate metrics](reports/cross_asset_v21/candidate_metrics.csv)
- [v21 evaluator](scripts/evaluate_cross_asset_v21.py)

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

## Post-holdout structural audit

The comment-driven v20.1 audit resolves the remaining interpretation questions without changing
the frozen strategy:

| Question | Locked evidence | Conclusion |
|---|---:|---|
| Is performance dependent on equity beta? | Total SPY beta 0.172; HAC t-stat 19.70; R² 53.5%; long beta 0.175; short beta -0.003 | **Directional long dependence confirmed** |
| Is the short book independently profitable? | Net expectancy -0.18%; Sharpe -0.495 | **No** |
| Does removing borrow repair the short book? | Borrow-free expectancy -0.07% | **No over the full holdout** |
| Did shorts hedge 2022? | +0.14% before borrow, -0.07% after borrow, versus -9.12% from the long book | **Too small; net defense failed** |
| Does deleveraging coincide with worse execution? | 2 tail events at 2.24× mean cost versus 1.43× otherwise; liquidity multiplier 1.04× versus 1.07× | **Tail cost interaction present, economically small and not liquidity-driven** |

Average locked net exposure was 52.6%. Regression alpha versus SPY was -1.84% annualized. The
evidence confirms that the observed return was mainly a directional long trend result rather than
a symmetric CTA result.

The borrow-free test is an ETF counterfactual, not a futures backtest. It shows that borrow explains
the 2022 sign flip, but not the multi-year short-side failure. A valid futures claim requires
contract-level roll, carry, basis, collateral, margin and execution data under a separately frozen
protocol.

The deleveraging interaction audit reconstructs drifted pretrade gross exposure and aligns each
rebalance with its following-session realized cost. Across all 100 rebalances, gross change and the
cost multiplier had Pearson correlation 0.093 and Spearman correlation 0.015 (p=0.883), providing
no evidence of a broad monotonic relationship. The single 2022 deleveraging event occurred at a
2.84× cost multiplier, but its state-dependent transaction cost was only 0.006% of NAV, equal to
0.066% of the absolute 2022 arithmetic loss. Futures-style margin stress remains outside the cash
ETF dataset and is specified only in the futures-native follow-up protocol.

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
- [Comment issue resolution](reports/cross_asset_v20_comment_audit/COMMENT_ISSUES.md)
- [Comment audit decision](reports/cross_asset_v20_comment_audit/SUMMARY.json)
- [Market-beta diagnostics](reports/cross_asset_v20_comment_audit/market_beta_diagnostics.csv)
- [Short cost waterfall](reports/cross_asset_v20_comment_audit/short_cost_waterfall.csv)
- [2022 book teardown](reports/cross_asset_v20_comment_audit/locked_yearly_book_teardown.csv)
- [Regime book diagnostics](reports/cross_asset_v20_comment_audit/regime_book_diagnostics.csv)
- [Deleveraging interaction report](reports/cross_asset_v20_comment_audit/DELEVERAGING_INTERACTION.md)
- [Rebalance-level execution audit](reports/cross_asset_v20_comment_audit/deleveraging_execution_audit.csv)
- [Deleveraging execution summary](reports/cross_asset_v20_comment_audit/deleveraging_execution_summary.csv)
- [Deleveraging audit decision](reports/cross_asset_v20_comment_audit/DELEVERAGING_SUMMARY.json)
- [Comment audit implementation](scripts/audit_v20_comment_claims.py)
- [Comment audit tests](tests/test_v20_comment_audit.py)
- [Deleveraging audit implementation](scripts/audit_v20_deleveraging_interaction.py)
- [Deleveraging audit tests](tests/test_v20_deleveraging_interaction.py)
- [Futures-native research specification](docs/FUTURES_RESEARCH_SPEC.md)

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
