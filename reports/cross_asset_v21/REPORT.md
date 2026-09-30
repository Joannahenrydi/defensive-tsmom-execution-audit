# v21 Defensive Long-Biased TSMOM

## Decision

**V21_REJECTED**

The protocol and eight-candidate matrix were frozen before execution. Candidate selection uses
2008–2016 only. The combined 2017–2024 period is explicitly reused development evidence, not a
fresh holdout. The 2022 result is diagnostic and cannot alter the selection.

| Candidate | Train Sharpe | Reused-dev Sharpe | Reused-dev CAGR | Reused-dev max DD | Short expectancy | Train qualified |
|---|---:|---:|---:|---:|---:|---:|
| A | 1.185 | 0.590 | 1.89% | -7.22% | -0.16% | False |
| B | 0.712 | 0.471 | 0.55% | -4.42% | -0.01% | False |
| C | 0.753 | 0.503 | 2.03% | -7.17% | -0.74% | False |
| D | 0.688 | 0.399 | 1.47% | -7.90% | -0.69% | True |
| E | 0.703 | 0.389 | 1.38% | -8.46% | -0.69% | True |
| F | 0.611 | 0.481 | 1.87% | -9.58% | -0.81% | True |
| G | 0.689 | 0.405 | 1.50% | -7.91% | -0.67% | True |
| H | 0.680 | 0.474 | 1.77% | -7.93% | -0.52% | True |

Train-selected candidate: **D**.


## Selected-candidate audit

- Reused-development Sharpe: **0.399**; CAGR:
  **1.47%**; maximum drawdown: **-7.90%**.
- Long net contribution: **17.78%**; short net contribution:
  **-5.54%**; annualized short expectancy:
  **-0.69%**.
- Frozen-trade 2x-cost Sharpe: **0.374**;
  one-session-delay Sharpe: **0.405**; state-cost Sharpe:
  **0.380**.
- Largest residual dynamic name-cap excess: **1.50%**.
- Failed gate components: **development_sharpe, short_expectancy, operational**.

The residual name-cap excess is not hidden. It occurs when a risk-off/cash signal requests a
faster liquidation than the 0.10% ADV constraint allows. The engine executes the maximum feasible
reduction and the operational gate fails until the risk cap is restored.


## Gate interpretation

- Historical research gate passed: **False**.
- Prospective validation required: **True**.
- Orders allowed: **No**.
- Selection used development data: **No**.

The structural gate requires the short book to have nonnegative standalone expectancy, at least
three positive sleeves, top-five contribution below 75%, controlled SPY dependence and positive
performance in at least three of four fixed regimes. Passing the historical gate would authorize
only a frozen prospective study. It would not establish an unbiased OOS result.
