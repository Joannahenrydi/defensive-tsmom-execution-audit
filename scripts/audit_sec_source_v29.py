"""Audit fallback SEC-derived files against the frozen v29 point-in-time gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from scripts.collect_sec_fundamentals_v29 import canonical_ticker
from scripts.evaluate_equity_v7 import sha256

FUNDAMENTAL_REQUIRED = {
    "cik",
    "ticker",
    "metric",
    "fiscal_year",
    "fiscal_period",
    "end_date",
    "value",
    "unit",
    "quality",
}
FILING_REQUIRED = {"accession", "cik", "form", "report_date", "filed"}
FACT_VINTAGE_REQUIRED = {"accession", "filed"}


def schema_audit(
    fundamental_columns: set[str], filing_columns: set[str]
) -> dict[str, object]:
    """Return the non-negotiable schema checks for causal fact vintages."""
    fundamental_base = FUNDAMENTAL_REQUIRED.issubset(fundamental_columns)
    filing_base = FILING_REQUIRED.issubset(filing_columns)
    fact_vintage = FACT_VINTAGE_REQUIRED.issubset(fundamental_columns)
    return {
        "fundamental_schema_present": fundamental_base,
        "filing_schema_present": filing_base,
        "fact_rows_have_accession_and_filed": fact_vintage,
        "point_in_time_reconstruction_possible": (
            fundamental_base and filing_base and fact_vintage
        ),
        "missing_fact_vintage_columns": sorted(
            FACT_VINTAGE_REQUIRED - fundamental_columns
        ),
    }


def count_csv_rows(path: Path, chunksize: int = 250_000) -> int:
    """Count compressed CSV rows without holding the complete file in memory."""
    return sum(len(chunk) for chunk in pd.read_csv(path, chunksize=chunksize))


def candidate_mapping_summary(candidates: pd.DataFrame, companies: pd.DataFrame) -> dict:
    """Measure current ticker/CIK mapping while exposing ambiguous tickers."""
    candidate_symbols = candidates["symbol"].map(canonical_ticker)
    company_symbols = companies["ticker"].map(canonical_ticker)
    counts = company_symbols.value_counts()
    unique_company_symbols = set(counts[counts.eq(1)].index)
    ambiguous_company_symbols = set(counts[counts.gt(1)].index)
    mapped = candidate_symbols.isin(unique_company_symbols)
    ambiguous = candidate_symbols.isin(ambiguous_company_symbols)
    return {
        "candidate_symbols": int(candidate_symbols.nunique()),
        "uniquely_mapped_symbols": int(mapped.sum()),
        "ambiguous_symbols": int(ambiguous.sum()),
        "mapping_gate_pass": int(mapped.sum()) >= 400,
    }


def run_audit(candidates_path: Path, mirror_dir: Path, output: Path) -> dict:
    """Audit downloaded mirror files and write a fail-closed data decision."""
    fundamentals_path = mirror_dir / "us-public-company-fundamentals.csv.gz"
    filings_path = mirror_dir / "filing-timeliness.csv.gz"
    companies_path = mirror_dir / "companies.csv.gz"
    for path in (candidates_path, fundamentals_path, filings_path, companies_path):
        if not path.exists():
            raise FileNotFoundError(path)

    fundamental_columns = set(pd.read_csv(fundamentals_path, nrows=0).columns)
    filing_columns = set(pd.read_csv(filings_path, nrows=0).columns)
    schema = schema_audit(fundamental_columns, filing_columns)
    candidates = pd.read_csv(candidates_path, usecols=["symbol"])
    companies = pd.read_csv(companies_path, dtype={"cik": str, "ticker": str})
    mapping = candidate_mapping_summary(candidates, companies)

    filings = pd.read_csv(
        filings_path,
        usecols=["accession", "cik", "form", "report_date", "filed"],
        dtype={"accession": str, "cik": str, "form": str},
    )
    annual = filings.loc[filings["form"].isin(["10-K", "10-K/A"])].copy()
    annual["report_date"] = pd.to_datetime(annual["report_date"], errors="coerce")
    annual["filed"] = pd.to_datetime(annual["filed"], errors="coerce")
    duplicated_periods = annual.duplicated(["cik", "report_date"], keep=False)

    components = {
        "official_company_facts_accessible": False,
        "mapping_gate": bool(mapping["mapping_gate_pass"]),
        "mirror_base_schema": bool(
            schema["fundamental_schema_present"] and schema["filing_schema_present"]
        ),
        "fact_level_vintage": bool(schema["fact_rows_have_accession_and_filed"]),
        "point_in_time_reconstruction": bool(
            schema["point_in_time_reconstruction_possible"]
        ),
    }
    result = {
        "status": "V29_BLOCKED_SEC_DATA_QUALITY",
        "decision": "ALPHA_NOT_RUN",
        "reason": (
            "The official Company Facts endpoints returned HTTP 403 from the current "
            "host. The accessible normalized mirror keeps the latest value for each "
            "company/metric/period but omits the fact-level accession and filed date. "
            "Its separate filing table cannot identify which filing supplied each value, "
            "so later amendments or comparative restatements could be backfilled."
        ),
        "components": components,
        "source_access": {
            "attempted_on": "2026-10-01",
            "company_facts_api": {
                "url_pattern": (
                    "https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json"
                ),
                "result": "HTTP 403 Akamai response from current host",
            },
            "official_quarterly_archive": {
                "url_pattern": (
                    "https://www.sec.gov/files/dera/data/"
                    "financial-statement-data-sets/YYYYqN.zip"
                ),
                "result": "HTTP 403 Akamai response from current host",
            },
        },
        "mapping": mapping,
        "schema": schema,
        "mirror": {
            "provider": "SequelSEC",
            "snapshot_date": "2026-09-18",
            "license": "CC BY 4.0",
            "fundamental_rows": count_csv_rows(fundamentals_path),
            "filing_rows": len(filings),
            "annual_filings": len(annual),
            "annual_filings_in_ambiguous_cik_report_date_keys": int(
                duplicated_periods.sum()
            ),
            "fundamentals_sha256": sha256(fundamentals_path),
            "filings_sha256": sha256(filings_path),
            "companies_sha256": sha256(companies_path),
        },
        "candidates_sha256": sha256(candidates_path),
        "orders_allowed": False,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "DATA_GATE.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument(
        "--mirror-dir", type=Path, default=Path("data/raw/sec_v29_mirror")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("reports/equity_v29_data_gate")
    )
    arguments = parser.parse_args()
    print(
        json.dumps(
            run_audit(arguments.candidates, arguments.mirror_dir, arguments.output),
            indent=2,
        )
    )
