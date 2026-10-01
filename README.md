# Defensive TSMOM Research and Execution Audit

## Current research status: v28 OHLCV alpha admission rejected

v28 moved from close-to-close signals to three prespecified cross-asset OHLCV decompositions. All
features used next-session execution, v26 risk-group residualization and causal rolling
standardization. Two families passed the statistical screen, but neither survived standalone
portfolio economics on train.

| v28 train-only family | Five-day slope | Mean rank IC | ICIR | Portfolio result |
|---|---:|---:|---:|---|
| Overnight-gap reversal | +0.00002160 | +0.0055 | 0.0264 | Third by frozen admission rank |
| Intraday reversal | +0.00002124 | +0.0064 | 0.0313 | Sharpe **-0.053**; 2x cost **-0.071** |
| Volume-shock reversal | +0.00001126 | +0.0055 | 0.0280 | Optimizer selected cash |

The positive rank ICs were too thin to clear costs and portfolio constraints. No family was
sign-flipped or assigned a new window, and the reused 2017–2024 portfolio was not evaluated. The
result rejects these three daily OHLCV families as additions to the trend portfolio; it does not
claim that intraday execution data or event/fundamental information lacks alpha.

- [Frozen v28 protocol](docs/MULTI_ASSET_PROTOCOL_V28.md)
- [v28 report](reports/cross_asset_v28/REPORT.md)
- [v28 machine-readable decision](reports/cross_asset_v28/SUMMARY.json)
- [Train family qualification](reports/cross_asset_v28/train_family_qualification.csv)
- [Standalone train portfolios](reports/cross_asset_v28/standalone_train_portfolios.csv)
- [v28 evaluator](scripts/evaluate_cross_asset_v28.py)

## v27 multi-source alpha admission: rejected and blocked

v27 stopped changing trend construction and opened two independent research tracks. Track A added
a causal 20-session residual mean-reversion family to the frozen trend family. Track B required
expiry-specific futures curves for actual carry and prohibited ETF distributions or price-derived
pseudo-yields as substitutes.

| v27 train-only alpha admission | Trend | Residual mean reversion |
|---|---:|---:|
| Five-session slope | **+0.00005151** | **-0.00002752** |
| Predictive correlation | +0.0033 | **-0.0034** |
| Completed labels | 90,637 | 90,637 |
| Admission | **ADMITTED** | **BLOCKED** |

The two scores were independent in train—their pooled correlation was -0.0046—but independence is
not predictive value. Residual mean reversion had a negative train slope and was rejected without
reversing its sign, blending it with trend, or reading a reused-development portfolio result.
Track B is `V27_B_BLOCKED_DATA` because the workspace lacks expiry-specific futures settlements and
point-in-time contract metadata. Consequently, the 40/30/30 Trend + MR + Carry portfolio was not
run. This is simultaneously an MR alpha rejection and a carry data block; orders remain disabled.

- [Frozen v27 protocol](docs/MULTI_ASSET_PROTOCOL_V27.md)
- [v27 report](reports/cross_asset_v27/REPORT.md)
- [v27 machine-readable decision](reports/cross_asset_v27/SUMMARY.json)
- [Train family calibration](reports/cross_asset_v27/train_family_calibration.csv)
- [Train alpha correlation](reports/cross_asset_v27/train_alpha_correlation.csv)
- [Futures carry data gate](reports/cross_asset_v27/track_b_carry_data_gate.json)
- [v27 evaluator](scripts/evaluate_cross_asset_v27.py)

## v26 adaptive trend allocation: rejected

v26 tested the requested portfolio reframing without tuning on reused development evidence. It
combined the frozen v24 dynamic trend signal with causal within-group relative strength, used cash
instead of shorts in risk-on states, permitted half-strength shorts only in risk-off states, and
targeted equal risk across growth, rates, real assets and FX.

| v26 evidence | Train 2008–2016 | Reused development 2017–2024 |
|---|---:|---:|
| Net Sharpe | **-0.023** | **0.665** |
| Net CAGR | **-0.09%** | **1.80%** |
| Maximum drawdown | -6.25% | -6.03% |
| Long net expectancy | -0.06% | +1.82% |
| Short net expectancy | 0.00% | 0.00% |
| SPY beta | 0.030 | 0.036 |
| SPY R-squared | 6.36% | 5.69% |
| Top-five contribution share | 41.32% | 47.55% |

The development result improved and all four macro groups contributed positively, while equity
beta dependence fell materially. The frozen candidate still fails: train evidence is negative,
point-in-time group risk contributions miss their 10-percentage-point stability gate, and dynamic
risk-budget cuts cannot always be completed immediately under the 0.10% ADV limit. Five rebalance
events required the engine's disclosed maximum-liquidity emergency transition. The short book is
economically absent, so the evidence supports a diversified defensive long allocation in one
window rather than a stable long/short alpha. No parameters were changed after observing the
result, and orders remain disabled.

- [Frozen v26 protocol](docs/MULTI_ASSET_PROTOCOL_V26.md)
- [v26 report](reports/cross_asset_v26/REPORT.md)
- [v26 machine-readable decision](reports/cross_asset_v26/SUMMARY.json)
- [v24-v26 comparison](reports/cross_asset_v26/v24_v25_v26_comparison.csv)
- [Group risk-contribution audit](reports/cross_asset_v26/actual_group_risk_contributions.csv)
- [v26 evaluator](scripts/evaluate_cross_asset_v26.py)

## v25 regime-aware TSMOM: rejected

v25 retained the complete v24 signal and changed only side treatment. The prespecified risk-off
state required SPY below its 200-day average, negative 252-session return and 20-day volatility
above its prior 70th percentile. Risk-on sessions halved negative scores and capped short gross at
25%; risk-off sessions restored the full short score and a 100% short cap while limiting long gross
to 50%.

| v25 evidence | Train | Reused development 2017–2024 |
|---|---:|---:|
| Net Sharpe | **0.553** | **0.563** |
| Net CAGR | 2.48% | 2.63% |
| Maximum drawdown | -6.56% | -10.53% |
| Long net expectancy | +2.64% | +2.71% |
| Short net expectancy | -0.09% | +0.01% |
| SPY R-squared | 18.65% | 37.49% |

The headline portfolio metrics improved substantially from v24, but the conditional-short
hypothesis failed. Risk-off short expectancy and Sharpe were negative in both windows. In reused
development the optimizer allocated only 0.000002% average short gross during risk-off sessions, so
the result is economically a regime-controlled long portfolio rather than evidence of short alpha.
The 2022 return deteriorated from -0.41% in v24 to -3.07% in v25; 2023 improved from -3.88% to
+1.42%, again through the long book. Temporary name-cap excess under the ADV constraint also failed
the operational gate. Orders remain disabled.

- [Frozen v25 protocol](docs/MULTI_ASSET_PROTOCOL_V25.md)
- [v25 report](reports/cross_asset_v25/REPORT.md)
- [v25 machine-readable decision](reports/cross_asset_v25/SUMMARY.json)
- [Conditional long/short diagnostics](reports/cross_asset_v25/conditional_book_metrics.csv)
- [v24 versus v25 comparison](reports/cross_asset_v25/v24_v25_comparison.csv)
- [v25 evaluator](scripts/evaluate_cross_asset_v25.py)

## v24 dynamic symmetric TSMOM: rejected

v24 tested one frozen, mathematically symmetric long/short design: prior-window rolling z-scores,
a causal 70th-percentile dynamic threshold, standardized moving-average-gap confirmation,
`tanh(z)` sizing, identical 50% long and short gross caps, a volatility floor and one portfolio
regime scaler applied equally to both directions. No thresholds or weights were searched after the
results were read.

| v24 evidence | Train | Reused development 2017–2024 |
|---|---:|---:|
| Net Sharpe | **0.266** | **0.178** |
| Net CAGR | 0.69% | 0.51% |
| Maximum drawdown | -4.59% | -8.40% |
| Long net expectancy | +1.12% | +1.19% |
| Short net expectancy | **-0.39%** | **-0.63%** |
| Long Sharpe | 0.466 | 0.415 |
| Short Sharpe | **-0.279** | **-0.307** |

The reused-development long and short books averaged 39.37% and 30.62% gross, top-five absolute
contribution share fell to 31.16%, and SPY regression R-squared was 17.17%. The signal was therefore
far less dependent on a concentrated long book, but symmetric construction did not create positive
multi-year short expectancy. In 2022 alone the short book worked (+2.77% annualized expectancy,
Sharpe 1.594), while the long book lost -3.16%; the total year remained negative.

The candidate also failed the operational gate because a 0.10% ADV limit prevented immediate
compliance with every dynamic name-cap cut; the largest disclosed reused-development residual was
0.81%. The engine executed the maximum feasible reduction and did not assume an impossible fill.
This result strengthens the case for a futures-native follow-up, but it is not a futures result and
does not authorize orders.

- [Frozen v24 protocol](docs/MULTI_ASSET_PROTOCOL_V24.md)
- [v24 report](reports/cross_asset_v24/REPORT.md)
- [v24 machine-readable decision](reports/cross_asset_v24/SUMMARY.json)
- [v24 long/short metrics](reports/cross_asset_v24/book_metrics.csv)
- [v24 yearly attribution](reports/cross_asset_v24/yearly.csv)
- [v24 evaluator](scripts/evaluate_cross_asset_v24.py)

## v23 futures-native study: blocked at the data gate

The v23 contract-level audit is implemented and fail-closed. The current workspace has no
expiry-specific futures settlement archive or point-in-time contract metadata, and Alpaca's
official market-data interfaces do not provide the required futures history. The futures-native
strategy was therefore **not run**. This is a data-availability block, not an alpha rejection.

Required inputs are `data/futures/contracts_daily.parquet` and
`data/futures/contracts_metadata.csv`. The audit requires at least 12 roots across three sleeves,
95% session coverage, and two simultaneously observed expiries on at least 60% of root sessions.

- [Frozen v23 data protocol](docs/MULTI_ASSET_PROTOCOL_V23.md)
- [v23 data-gate report](reports/futures_v23_data_gate/REPORT.md)
- [v23 machine-readable status](reports/futures_v23_data_gate/SUMMARY.json)
- [v23 audit implementation](scripts/audit_futures_v23_data.py)

## v22 ETF carry proxy: rejected at train-only admission

The next prespecified study added a 70/30 blend of trend and ETF cash-distribution carry. The carry
family used trailing dividends and capital-gains distributions, not price-derived pseudo-carry.
Its train-only calibration slope was **-1.75e-7**, so the protocol rejected the family without
reversing it and without evaluating a portfolio on reused development data.

The ETF archive contained 3,263 positive distribution events, but coverage was uneven: the metals
sleeve had only two assets and only three of eight commodity ETFs recorded distributions. This
proxy cannot identify futures curve, basis or roll carry. v23 therefore requires contract-level
data before a futures-native result can be claimed.

- [Frozen v22 protocol](docs/MULTI_ASSET_PROTOCOL_V22.md)
- [v22 report](reports/cross_asset_v22/REPORT.md)
- [v22 train calibration](reports/cross_asset_v22/train_calibration.csv)
- [v22 data-quality audit](reports/cross_asset_v22/distribution_quality_by_sleeve.csv)

## v21 structural repair: rejected

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
