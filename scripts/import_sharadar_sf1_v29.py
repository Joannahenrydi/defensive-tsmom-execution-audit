"""Normalize a licensed Sharadar SF1 ARY export for the frozen v29 study."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.collect_sec_fundamentals_v29 import build_filing_events, canonical_ticker, data_gate
from scripts.evaluate_equity_v7 import sha256

SF1_FIELDS = {
    "assets": "assets",
    "revenue": "revenue",
    "gp": "gross_profit",
    "netinc": "net_income",
    "ncfo": "operating_cash_flow",
}
REQUIRED_COLUMNS = {
    "ticker",
    "dimension",
    "datekey",
    "reportperiod",
    *SF1_FIELDS,
}


def normalize_sf1(sf1: pd.DataFrame, candidates: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Convert as-reported annual SF1 rows into accession-like filing events."""
    missing = sorted(REQUIRED_COLUMNS - set(sf1.columns))
    if missing:
        return pd.DataFrame(), {
            "status": "V29_BLOCKED_SEC_DATA_QUALITY",
            "reason": "MISSING_SF1_COLUMNS",
            "missing_columns": missing,
            "orders_allowed": False,
        }
    ary = sf1.loc[sf1["dimension"].astype(str).str.upper().eq("ARY")].copy()
    ary["symbol"] = ary["ticker"].map(canonical_ticker)
    ary["filed"] = pd.to_datetime(ary["datekey"], errors="coerce")
    ary["period_end"] = pd.to_datetime(ary["reportperiod"], errors="coerce")
    ary = ary.dropna(subset=["symbol", "filed", "period_end"])
    candidates = candidates.copy()
    candidates["symbol"] = candidates["symbol"].map(canonical_ticker)
    ary = ary.merge(candidates[["symbol", "sector"]], on="symbol", how="inner")
    for source in SF1_FIELDS:
        ary[source] = pd.to_numeric(ary[source], errors="coerce")
    duplicate = ary.duplicated(["symbol", "filed", "period_end"], keep=False)
    if duplicate.any():
        return pd.DataFrame(), {
            "status": "V29_BLOCKED_SEC_DATA_QUALITY",
            "reason": "DUPLICATE_SF1_VINTAGE",
            "duplicate_rows": int(duplicate.sum()),
            "orders_allowed": False,
        }

    rows: list[dict] = []
    for record in ary.itertuples(index=False):
        accession = f"SF1-ARY-{record.symbol}-{record.period_end:%Y%m%d}-{record.filed:%Y%m%d}"
        for source, concept in SF1_FIELDS.items():
            value = getattr(record, source)
            if not np.isfinite(value):
                continue
            rows.append(
                {
                    "symbol": record.symbol,
                    "sector": record.sector,
                    "cik": record.symbol,
                    "entity_name": record.symbol,
                    "accession": accession,
                    "form": "SF1-ARY",
                    "fiscal_year": record.period_end.year,
                    "period_end": record.period_end,
                    "filed": record.filed,
                    "concept": concept,
                    "value": float(value),
                }
            )
    facts = pd.DataFrame(rows)
    events = build_filing_events(facts)
    summary = {
        "status": "V29_SF1_NORMALIZED_DATA_GATE_NOT_RUN",
        "provider": "Sharadar SF1",
        "dimension": "ARY",
        "candidate_rows": len(candidates),
        "as_reported_rows": len(ary),
        "events": len(events),
        "orders_allowed": False,
    }
    return events, summary


def run(sf1_path: Path, candidates_path: Path, output: Path) -> dict:
    sf1 = pd.read_csv(sf1_path)
    candidates = pd.read_csv(candidates_path)
    events, summary = normalize_sf1(sf1, candidates)
    output.mkdir(parents=True, exist_ok=True)
    if events.empty:
        (output / "DATA_GATE.json").write_text(json.dumps(summary, indent=2) + "\n")
        return summary
    events_path = output / "annual_fundamental_events.csv.gz"
    events.to_csv(events_path, index=False, compression="gzip")
    mapping = candidates.copy()
    mapping["symbol"] = mapping["symbol"].map(canonical_ticker)
    mapping["mapped"] = mapping["symbol"].isin(events["symbol"])
    gate, sector_coverage = data_gate(mapping, events)
    gate.update(
        provider="Sharadar SF1 ARY",
        provider_file_sha256=sha256(sf1_path),
        candidates_sha256=sha256(candidates_path),
        annual_events_sha256=sha256(events_path),
        orders_allowed=False,
    )
    sector_coverage.to_csv(output / "sector_coverage.csv", index=False)
    (output / "DATA_GATE.json").write_text(json.dumps(gate, indent=2) + "\n")
    return gate


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sf1", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("data/raw/sf1_v29"))
    arguments = parser.parse_args()
    print(json.dumps(run(arguments.sf1, arguments.candidates, arguments.output), indent=2))
