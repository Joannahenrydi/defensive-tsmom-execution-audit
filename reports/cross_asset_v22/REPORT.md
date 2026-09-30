# v22 ETF Trend + Distribution-Carry

## Decision

**V22_REJECTED**

The distribution-carry family failed the prespecified train-only admission gate. Its slope was **-0.00000018**, so the signal was not reversed and no portfolio or reused-development result was evaluated.

## Data-quality finding

The archive contained 3,263 positive cash distribution events and 1 event above the frozen 25% quality bound. Metals had only two assets and commodity distributions appeared in only three of eight assets. Cash distributions therefore provide uneven cross-asset coverage and cannot stand in for contract-level curve and roll carry.

## Research disposition

v22 is rejected before portfolio evaluation. The next admissible step is the v23 futures data gate. Orders remain disabled.
