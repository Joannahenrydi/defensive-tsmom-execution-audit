# Deleveraging × Execution-State Interaction Audit

## Scope

This diagnostic reconstructs every frozen v20 rebalance. A deleveraging event is prespecified as a
decline of more than 10% from drifted pretrade gross exposure to posttrade gross exposure. Costs
are aligned to the following session, when the frozen engine realizes the trade charge. No signal,
holding, cost formula or promotion decision changes.

## Locked result

| Rebalance state | Events | Mean cost multiplier | Mean liquidity multiplier | Mean volatility multiplier | Mean turnover | Total execution cost |
|---|---:|---:|---:|---:|---:|---:|
| Expansion | 1 | 4.00× | 1.30× | 2.28× | 10.17% | 0.008% |
| Normal | 97 | 1.40× | 1.07× | 1.15× | 1.59% | 0.041% |
| Deleveraging | 2 | 2.24× | 1.04× | 1.45× | 10.27% | 0.009% |

The two tail deleveraging events occurred at an average 2.24×
cost multiplier versus 1.43× for other rebalances. This tail
interaction is present descriptively, but it was driven by volatility and the drawdown stress
rather than liquidity: the deleveraging liquidity multiplier was
1.04× versus
1.07× for other events.

Across all 100 rebalances, gross change and the cost multiplier had Pearson correlation
0.093 and Spearman correlation 0.015
(p=0.883). The data therefore do not support a broad monotonic claim that
larger gross reductions systematically coincide with worse execution states. The tail comparison
is based on only two events and must not be treated as a stable estimate.

## 2022 teardown

- Deleveraging events: **1**.
- Decision/execution date: **2022-03-07 / 2022-03-08**.
- Cost multiplier: **2.84×**.
- Liquidity multiplier: **1.00×**.
- Volatility multiplier: **1.90×**.
- State-dependent transaction cost: **0.006% of NAV**.
- Increment above baseline cost: **0.004% of NAV**.
- State cost as a share of the absolute 2022 arithmetic loss: **0.066%**.

The 2022 interaction existed, but its direct cost was economically immaterial relative to the
portfolio loss. Execution cost did not cause the 2022 failure; gross long-book performance did.
The execution-day return is reported in the event file only as context and is not attributed
causally to the rebalance.

## Margin scope

The implementation trades unlevered cash ETFs. Futures-style variation margin, initial-margin
changes and margin-driven liquidation cannot be identified from this dataset. They remain an
explicit requirement of the separately frozen futures-native research specification rather than a
fabricated multiplier in this audit.

## Decision

**INTERACTION_PRESENT_IN_TAIL_BUT_ECONOMICALLY_SMALL.** Aaron's execution concern is now closed:
tail deleveraging occurred under higher total cost states, the evidence does not show coincident
liquidity deterioration or a general monotonic relationship, and realized deleveraging cost was far
too small to explain the strategy failure. The frozen v20 rejection remains unchanged.
