# Research Data Onboarding

Frozen on 2026-10-01 before any futures or alternative fundamental dataset was acquired. This
document changes the data layer, not a strategy parameter. No alpha evaluation may begin until a
source passes its own point-in-time and coverage gate.

## Priority 1: expiry-specific futures

The preferred first implementation is CME Globex contract data through Databento `GLBX.MDP3` or
an equivalent licensed CME archive. The source must provide:

- exchange-published settlement, cleared volume and open interest by contract and session;
- point-in-time instrument definitions with raw symbol, activation, last eligible trade time,
  tick size, contract size, currency and exchange;
- at least two live expiries on 60% of admitted root sessions; and
- an authoritative first-notice calendar for every physically delivered contract.

The initial roots are ES, NQ, RTY, ZT, ZF, ZN, ZB, 6E, 6J, 6B, 6A, 6C, GC, SI, HG, CL, NG, ZC,
ZW and ZS. At least 12 roots across three sleeves must pass. The source-native start for
`GLBX.MDP3` is used rather than fabricating 2008 history. The end of historical development is
2024-12-31; 2025 onward is not a clean holdout for this project.

Databento definitions expose the last eligible trade timestamp but do not establish a first-notice
date for deliverable contracts. Equity-index contracts can be marked cash settled. Rates, FX,
metals, energy and agricultural contracts remain blocked until a CME-derived notice calendar is
joined. Expiration is never substituted for first notice.

Accepted output remains:

```text
data/futures/contracts_daily.parquet
data/futures/contracts_metadata.csv
data/futures/contracts_metadata_history.parquet
```

Continuous or back-adjusted series are allowed only as derived signal inputs. They are not valid
PnL instruments and cannot be used to infer curve carry.

## Priority 2: point-in-time fundamentals

The primary source remains SEC Company Facts with accession and filing date on every fact. A
licensed alternative is admissible only when it retains an as-reported vintage. Sharadar SF1 is
supported through annual `ARY` observations because that dimension is documented as
point-in-time/as-reported and keyed by `datekey`.

Required fields are ticker, dimension, datekey, reportperiod, assets, revenue, gross profit, net
income and operating cash flow. `datekey` is treated as the filing date, and the signal becomes
available one U.S. business day later. The importer preserves every distinct datekey; it does not
replace an original filing with the latest restatement.

The following are not admissible:

- tables that retain only the latest restated value for each fiscal period;
- fundamentals timestamped only by fiscal-period end;
- vendor scores without their raw filing vintage; or
- current-universe exports presented as survivor-free history.

The existing v29 train, development, family-admission and portfolio gates remain unchanged. A new
provider may unblock the data gate but does not receive a lower alpha threshold.

## Credentials and cost control

API credentials are read only from `DATABENTO_API_KEY` or `NASDAQ_DATA_LINK_API_KEY`. They must
never be passed on the command line, written into manifests, committed or printed. Before a paid
historical request, obtain a provider cost estimate outside the research evaluator and cap the
requested roots and dates to this frozen universe. Acquiring data never authorizes an order.

The futures collector enforces this sequence:

```bash
python -m scripts.collect_databento_futures estimate
python -m scripts.collect_databento_futures download --approved-cost-usd REVIEWED_LIMIT
python -m scripts.collect_databento_futures normalize \
  --notice-calendar data/vendor/cme_first_notice_dates.csv
```

`estimate` makes only the provider metadata cost query. `download` refuses to run when the current
estimate exceeds the explicit reviewed cap. The API key is read from the environment and never
included in the output manifest.

## Provider references

- https://databento.com/docs/examples/futures/retrieving-oi-and-settlement-prices
- https://databento.com/docs/schemas-and-data-formats/instrument-definitions
- https://data.nasdaq.com/databases/SF1/documentation
- https://www.sec.gov/search-filings/edgar-application-programming-interfaces
