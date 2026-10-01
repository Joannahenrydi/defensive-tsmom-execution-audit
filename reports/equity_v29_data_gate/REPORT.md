# v29 SEC Filing-Date Fundamentals — Data-Gate Report

## Decision

`V29_BLOCKED_SEC_DATA_QUALITY`

The alpha study was not run and no orders are allowed. The block is source-specific rather than a
fundamental-alpha rejection.

## What was tested

The frozen v29 protocol requires each accounting value to retain its SEC accession number and
filing date. That is necessary to release an observation one business day after filing and to
preserve later amendments as separate events.

The official SEC Company Facts API and quarterly Financial Statement Data Set archive both
returned HTTP 403 Akamai responses from the current host on 2026-10-01. An accessible SequelSEC
snapshot was then audited as a possible fallback. Its provenance, row counts and hashes were
recorded before any alpha calculation.

| Check | Result |
|---|---:|
| Candidate symbols | 503 |
| Current symbols uniquely mapped to CIK | **500** |
| Normalized fundamental rows | 3,346,388 |
| Filing-timeliness rows | 184,550 |
| Annual filing rows | 45,689 |
| Fundamental rows include `accession` | **No** |
| Fundamental rows include `filed` | **No** |
| Point-in-time reconstruction possible | **No** |

## Why the mirror cannot be used for this backtest

The mirror's fundamental table retains one value per company, metric and period from the latest
filing that reported it. Its separate filing-timeliness table has accession and filing dates, but
there is no fact-to-accession key. Joining only on CIK and period end cannot establish which filing
supplied a value: later annual filings can repeat comparative periods and amendments can revise
them. The audit found 2,822 annual filing rows in duplicated CIK/report-date keys, but the more
fundamental failure is that even a unique filing-date row cannot prove the vintage of a selected
fact.

Using the mirror would therefore permit later restatements to appear at an earlier date. That
violates the frozen protocol's point-in-time rule. The data was rejected rather than silently
treated as originally reported.

## Reproducibility and next valid input

- [Machine-readable gate](DATA_GATE.json)
- [Source audit](../../scripts/audit_sec_source_v29.py)
- [Official collector](../../scripts/collect_sec_fundamentals_v29.py)
- [Frozen protocol](../../docs/EQUITY_RESEARCH_PROTOCOL_V29.md)
- SEC API documentation: https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- SequelSEC filing-timeliness dataset: https://sequelsec.com/datasets/filing-timeliness
- SequelSEC fundamentals snapshot: https://doi.org/10.5281/zenodo.22832210

v29 can resume without changing its alpha rules when accession-level Company Facts JSON, official
quarterly SEC files, or an equivalent source retaining `accession`, `filed`, concept, value and
period is available. A latest-value fundamentals table is not an acceptable substitute.
