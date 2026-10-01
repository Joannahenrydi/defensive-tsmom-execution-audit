# v30–v32 Research Readiness

## Current decision

- **v30 Futures Trend + Carry:** `V30_BLOCKED_FUTURES_DATA`
- **v31 Trend + PIT Fundamentals:** `V31_BLOCKED_PIT_DATA`
- **v32 Integrated Multi-Source Portfolio:** `V32_NOT_RUN_COMPONENT_BLOCKED`

No alpha or portfolio result was generated. The current workspace does not contain an admitted
expiry-specific futures archive or an admitted as-reported fundamental event file. This is a data
availability decision, not an alpha rejection.

## v30

Missing core files:
- `data/futures/contracts_daily.parquet`
- `data/futures/contracts_metadata.csv`
- `data/futures/contracts_metadata_history.parquet`

Missing operational files:
- `data/futures/root_cost_schedule.csv`
- `data/futures/margins_daily.parquet`

Contract-level alpha diagnostics require the core files and the v30 quality gate. Portfolio
admission additionally requires costs and margin. Continuous futures or ETF prices cannot replace
these inputs.

## v31

- Source gate: `reports/equity_v29_data_gate/DATA_GATE.json`
- Source status: `V29_BLOCKED_SEC_DATA_QUALITY`
- As-reported event file present: `False`

Latest-restatement fundamentals remain inadmissible. Only SEC accession/filed facts or a licensed
as-reported vintage such as SF1 `ARY` can unblock the alpha gate.

## v32

v32 remains stopped until every included v30 and v31 component independently passes its frozen
family and standalone portfolio gates. It will not fill a missing component with a price proxy or
retune sleeve weights on reused history. Orders remain disabled.
