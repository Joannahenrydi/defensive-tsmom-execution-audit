# v27 Multi-Source Alpha Framework

## Decision

**V27_A_REJECTED_FAMILY_ADMISSION**

v27 changed the alpha hypothesis. Track A tested whether a causal 20-session group-residual
mean-reversion family had independent train evidence next to the frozen trend family. Track B
audited the contract-level futures inputs required for actual term-structure carry.

## Track A — train-only family admission

- Trend calibration: **ADMITTED**; slope
  **0.00005151**.
- Residual-MR calibration: **BLOCKED**; slope
  **-0.00002752**.
- Residual-MR five-session pooled correlation: **-0.0034**
  across **90,637** completed train labels.
- Trend/MR pooled train correlation: **-0.005**.
- MR standalone train Sharpe: **not run (slope gate failed)**.
- MR frozen-trade 2x-cost train Sharpe: **not run (slope gate failed)**.


Track-A reused-development portfolio evaluated: **No**. A family that fails admission is not
sign-flipped, blended or repaired.


## Track B — futures carry data gate

**V27_B_BLOCKED_DATA**. Missing inputs: data/futures/contracts_daily.parquet, data/futures/contracts_metadata.csv.
ETF distributions and price-derived pseudo-yields were not substituted for term-structure carry.

## Track C

**V27_C_NOT_RUN_CARRY_DATA_BLOCKED**. The full 40/30/30 blend was not run because every source must
first pass its own admission gate. Orders remain disabled.
