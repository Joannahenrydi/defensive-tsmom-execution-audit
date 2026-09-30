# v20.1 Comment-Driven Structural Audit

## Status

This is a **post-holdout diagnostic**, not a new strategy version. It reads the immutable v20
holdings and returns. It does not change the signal, portfolio, costs, gates or the original
`LOCKED_PORTFOLIO_FAIL` decision.

## Questions and answers

| Comment concern | Evidence | Answer |
|---|---|---|
| Is the portfolio disguised equity beta? | Total SPY beta 0.172, HAC t-stat 19.70, R-squared 53.5%; long-book beta 0.175; short-book beta -0.003. Average net exposure was 52.6%. | **Yes: directional long dependence is confirmed.** |
| Does the short book have positive standalone expectancy after costs? | Locked short expectancy -0.18%, Sharpe -0.495. | **No.** |
| Is borrow drag the only reason the short book fails? | Locked borrow-free short expectancy -0.07%. | **No. It remains negative before borrow over the full holdout.** |
| Did shorts provide defense in 2022? | 2022 borrow-free short contribution 0.14%; after borrow -0.07%; long contribution -9.12%. | **Weak gross defense existed, but borrow reversed it and its size was immaterial versus the long loss.** |
| Would replacing ETF shorts with futures solve the problem? | Zero-borrow counterfactual is still negative over 2021–2024. | **Borrow removal alone is insufficient. A real futures test still requires contract-level roll, carry, margin and execution data.** |
| Does deleveraging occur under worse execution conditions? | Tail deleveraging mean cost multiplier 2.24× versus 1.43× otherwise; liquidity multiplier 1.04× versus 1.07×. | **Tail interaction exists, but is volatility/drawdown-driven and economically small.** |

## Equity-beta attribution

The total portfolio's annualized regression alpha versus SPY was
-1.84%; the HAC beta t-stat was 19.70.
The long book explains essentially all measured market beta, while the short book has near-zero
beta and negative standalone expectancy. The portfolio therefore cannot be presented as an
uncorrelated or symmetric long-short CTA.

## Borrow-free counterfactual

The counterfactual keeps the exact ETF holdings and transaction costs but sets borrow to zero. It
is deliberately labelled **borrow-free ETF proxy**, not a futures backtest.

- Locked 2021–2024: -0.07% annualized short expectancy before
  borrow, versus -0.18% after borrow.
- 2022: 0.14% contribution before borrow, versus
  -0.07% after borrow.

Borrow drag explains the sign flip in 2022, but it does not explain the multi-year failure because
the full-holdout short gross edge is already negative. Actual futures may improve financing and
short implementation, but they also introduce roll yield, basis, contract selection, collateral,
margin and different execution costs. Those cannot be inferred from ETF returns.

## Research disposition

- Evidence questions raised in the comments: **resolved**.
- Frozen v20 strategy: **still rejected**.
- Symmetric long-short claim: **rejected**.
- Futures implementation claim: **not made without futures data**.
- Paper/live orders: **disabled**.

The next admissible strategy is a separately frozen futures-native study. The consumed 2021–2024
ETF holdout cannot be used for parameter selection.

## Deleveraging interaction closure

The [rebalance-level interaction audit](DELEVERAGING_INTERACTION.md) reconstructs drifted pretrade
gross exposure and aligns trades with following-session costs. Only two of 100 rebalances reduced
gross by more than 10%. Their average cost multiplier was 2.24×, but their liquidity multiplier was
not worse than other rebalances. The single 2022 event cost 0.006% of NAV, just 0.066% of that
year's absolute arithmetic loss. Gross change had Pearson correlation 0.093 and Spearman
correlation 0.015 (p=0.883) with the cost multiplier. Aaron's concern is therefore closed as a
descriptive tail interaction that is too small to explain the failure, with futures margin correctly
left outside the cash-ETF evidence.
