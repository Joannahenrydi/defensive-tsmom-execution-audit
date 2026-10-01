# v29 — SEC Filing-Date Fundamental Alpha Protocol

Frozen on 2026-10-01 before SEC Company Facts were downloaded or any v29 signal result was read.
v27 and v28 showed that low-correlation price families can still lack enough economic edge after
costs. v29 therefore adds issuer accounting information rather than another price transformation.

## Evidence and limitations

- Train and family admission: 2018-01-02 through 2022-12-30.
- Reused development: 2023-01-03 through 2024-12-31.
- 2025–2026 is not used for selection and is not called a clean holdout because related equity
  research has already inspected that period.
- The 503-symbol candidate file is a current security snapshot, not historical index membership.
- Current SEC ticker/CIK associations are used to locate issuers. This creates mapping and survivor
  limitations even though accounting observations are reconstructed by filing date.
- Orders remain disabled in every v29 state.

## Source and access discipline

Use the SEC `data.sec.gov/api/xbrl/companyfacts/CIK##########.json` endpoint and the official
`company_tickers_exchange.json` mapping. No API key is required. The collector must declare a user
agent, stay below five requests per second, cache raw responses, retry transient failures and
record response hashes. Official references:

- https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data

## Point-in-time reconstruction

Use annual `10-K` and `10-K/A` US-GAAP facts. Each observation is keyed by CIK, accession number,
fiscal year, period end and `filed` date. A filing becomes usable on the next U.S. business day
after `filed`; no fact may be backfilled to its fiscal-period end. Amendments become new events on
their own filing date.

Use these canonical concepts, with frozen tag priority recorded in code:

- assets;
- revenue;
- gross profit;
- net income; and
- operating cash flow.

Duration facts must span 300–430 days. Assets are instant facts. Values must be finite, assets and
revenue must be positive, and ratios are winsorized cross-sectionally only after they become
available.

## Frozen alpha families

For each filing event compute:

```text
profitability       = net_income / assets
gross_profitability = gross_profit / assets
cash_profitability  = operating_cash_flow / assets
accrual_quality     = (operating_cash_flow - net_income) / assets
asset_growth        = -(assets / prior_annual_assets - 1)
revenue_growth      = revenue / prior_annual_revenue - 1
```

The quality family is the equal-weight mean of available profitability, gross profitability, cash
profitability and accrual quality ranks. The conservative-growth family is the equal-weight mean
of asset-growth and revenue-growth ranks. Ranks are cross-sectional and sector neutral on each
decision date. Require at least two component metrics, at least five eligible names per sector and
at least 100 names in the full cross-section. Signals are carried forward for at most 400 calendar
days and are delayed one business day after filing.

## Data gate

Before alpha evaluation require:

- at least 400 of 503 candidate symbols mapped uniquely to a CIK;
- at least 250 symbols with one usable annual event during 2018–2022;
- at least 200 symbols with three usable annual events by the end of train;
- at least eight sectors with ten covered symbols; and
- no duplicate symbol-date event after amendment ordering.

Failure is `V29_BLOCKED_SEC_DATA_QUALITY`, not an alpha rejection.

## Train-only alpha admission

Each family predicts 21-session forward total return using labels completed inside train. Require
positive mean daily rank IC, ICIR at least 0.02, at least four positive train calendar years, and
positive zero-intercept pooled slope. A negative family is not reversed. Admit at most two families
with daily IC correlation below 0.75.

Each statistically admitted family must then produce positive standalone train net Sharpe and
positive frozen-trade doubled-transaction-cost train Sharpe under the existing market/sector/beta
neutral equity portfolio and cost model. Only admitted families may be blended, at equal weight.
Reused development is read only after the train gate passes.

## Required outputs and decision

Report mapping coverage, concept coverage, filings by year, amendment counts, filing-to-availability
lag, missingness by sector, train IC, annual IC, family correlation, standalone portfolio results,
long/short attribution, turnover, costs, beta, sector exposure and every constraint. An evaluated
candidate must exceed net Sharpe 0.50, have positive CAGR, maximum drawdown at least -15%, positive
2x-cost and one-session-delay Sharpe, and pass all operational constraints in train and reused
development.

Possible states are `V29_BLOCKED_SEC_DATA_QUALITY`, `V29_REJECTED_FAMILY_ADMISSION`,
`V29_REJECTED_PORTFOLIO_GATE`, and `V29_HISTORICAL_GATE_PASS_PROSPECTIVE_REQUIRED`.
