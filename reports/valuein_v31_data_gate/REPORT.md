# v31 Valuein Point-in-Time Data Gate

## Decision

**V31_BLOCKED_PIT_DATA — alpha and portfolio evaluation were not run.**

The public Valuein `sample` snapshot `snapshot_20261001` was downloaded and normalized
successfully. The pipeline used `value_as_filed`, the later of filing/fact `accepted_at`, a one
business-day availability delay, amendments as separate events, SCD ticker validity, and historical
S&P 500 effective/removal dates.

| Frozen component | Result |
|---|---|
| membership session coverage | PASS |
| one train event | PASS |
| three train events | FAIL |
| sector depth | PASS |
| unique entity availability | PASS |

## Coverage

- Normalized annual events: **3,351**
- First availability date: **2021-02-12**
- Last availability date: **2026-09-29**
- Train events: **829**
- Entities with at least one train event: **657**
- Entities with three train events: **2 / 200 required**
- Train membership sessions with at least 400 names: **1,304**
- Sectors with at least ten covered entities: **10**
- Amendments preserved as separate events: **27**

The public sample starts in 2021, so it cannot support the frozen 2018–2022 training requirement.
This is a history-depth block, not evidence against quality or conservative-growth alpha. A
Valuein plan with full historical coverage can rerun the identical normalizer and gate without
changing the research rules.

## Research disposition

- v30 remains blocked on expiry-specific futures, first-notice, cost and margin data.
- v31 fundamental IC, standalone portfolio and integration were not run.
- v32 remains stopped because its independently admitted components do not exist.
- Orders remain disabled.
