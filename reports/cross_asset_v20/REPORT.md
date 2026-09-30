# v20 Locked Execution and Short-Book Audit

## Decision

- Total portfolio: **LOCKED_PORTFOLIO_FAIL**
- Structural classification: **LONG_DRIVEN_NOT_SYMMETRIC**
- Locked test evaluated exactly once: **Yes**
- Orders allowed: **No**

| Locked 2021–2024 evaluation | Net Sharpe | Net CAGR | Max drawdown |
|---|---:|---:|---:|
| Baseline frozen v19 | 0.150 | 0.51% | -11.03% |
| Frozen trades, 2x transaction cost | 0.147 | 0.50% | -11.03% |
| Frozen trades, state-dependent costs | 0.131 | 0.44% | -11.22% |

## Short-book evidence

The baseline short book produced locked annualized arithmetic expectancy of
**-0.18%** and Sharpe of
**-0.495** after allocated transaction costs and borrow. In 2022 alone its
net arithmetic contribution was **-0.07%** with Sharpe
**-0.125**.

The long and short books are evaluated as standalone contribution streams on the same portfolio
capital base. Their daily net returns reconcile exactly to total portfolio net return.

## State-dependent execution stress

The stress retains every baseline holding and trade. Transaction and borrow charges rise only when
lagged volatility, liquidity or drawdown conditions worsen. The locked average transaction-cost
multiplier was **1.48x**, its 95th percentile was
**2.84x**, and its maximum was
**4.00x**.

## Interpretation

The total-portfolio result and the short-book result are separate prespecified decisions. A
portfolio pass does not validate a symmetric long-short CTA claim. No parameter was changed after
the holdout was read, and this run cannot authorize paper or live orders.
