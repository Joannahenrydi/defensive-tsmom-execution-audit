"""Audit whether a contract-level futures archive can support the frozen v23 study."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.evaluate_equity_v7 import sha256

PROTOCOL = Path("docs/MULTI_ASSET_PROTOCOL_V23.md")
START = pd.Timestamp("2008-01-02")
END = pd.Timestamp("2024-12-31")
ROOT_SLEEVES = {
    "ES": "equity", "NQ": "equity", "RTY": "equity",
    "ZT": "rates", "ZF": "rates", "ZN": "rates", "ZB": "rates",
    "6E": "fx", "6J": "fx", "6B": "fx", "6A": "fx", "6C": "fx",
    "GC": "metals", "SI": "metals", "HG": "metals",
    "CL": "energy", "NG": "energy",
    "ZC": "agriculture", "ZW": "agriculture", "ZS": "agriculture",
}
DAILY_COLUMNS = {
    "date", "root", "contract", "settlement", "open", "high", "low",
    "volume", "open_interest",
}
METADATA_COLUMNS = {
    "root", "contract", "sleeve", "exchange", "currency", "multiplier", "tick_size",
    "expiry_date", "first_notice_date", "last_trade_date",
}


def read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    return pd.read_csv(path)


def audit_tables(daily: pd.DataFrame, metadata: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    problems: list[str] = []
    missing_daily = sorted(DAILY_COLUMNS - set(daily.columns))
    missing_metadata = sorted(METADATA_COLUMNS - set(metadata.columns))
    if missing_daily:
        problems.append(f"daily file missing columns: {','.join(missing_daily)}")
    if missing_metadata:
        problems.append(f"metadata file missing columns: {','.join(missing_metadata)}")
    if problems:
        return {
            "status": "V23_BLOCKED_DATA_QUALITY",
            "problems": problems,
            "admitted_roots": [],
            "admitted_sleeves": [],
            "orders_allowed": False,
        }, pd.DataFrame()

    daily = daily.copy()
    metadata = metadata.copy()
    daily["date"] = pd.to_datetime(daily["date"], errors="coerce")
    for column in ("expiry_date", "first_notice_date", "last_trade_date"):
        metadata[column] = pd.to_datetime(metadata[column], errors="coerce")
    if daily["date"].isna().any():
        problems.append("daily file contains invalid dates")
    if daily.duplicated(["date", "contract"]).any():
        problems.append("duplicate contract-date rows")
    if metadata.duplicated(["contract"]).any():
        problems.append("duplicate contract metadata rows")
    if not daily["root"].isin(ROOT_SLEEVES).all():
        problems.append("daily file contains roots outside the frozen universe")
    if not metadata["root"].isin(ROOT_SLEEVES).all():
        problems.append("metadata contains roots outside the frozen universe")
    if not set(daily["contract"]).issubset(set(metadata["contract"])):
        problems.append("daily file contains contracts without metadata")
    prices = daily[["settlement", "open", "high", "low"]].apply(
        pd.to_numeric, errors="coerce"
    )
    if prices.isna().any().any() or prices.le(0).any().any():
        problems.append("nonpositive or invalid contract prices")
    activity = daily[["volume", "open_interest"]].apply(pd.to_numeric, errors="coerce")
    if activity.isna().any().any() or activity.lt(0).any().any():
        problems.append("negative or invalid volume/open interest")
    contract_scale = metadata[["multiplier", "tick_size"]].apply(
        pd.to_numeric, errors="coerce"
    )
    if contract_scale.isna().any().any() or contract_scale.le(0).any().any():
        problems.append("nonpositive or invalid multiplier/tick size")
    cash_settled = metadata.get("cash_settled", pd.Series(False, index=metadata.index)).fillna(False)
    if (metadata["first_notice_date"].isna() & ~cash_settled.astype(bool)).any():
        problems.append("missing first notice date without cash-settled flag")
    if metadata[["expiry_date", "last_trade_date"]].isna().any().any():
        problems.append("missing expiry or last-trade date")

    expected_sessions = len(pd.bdate_range(START, END))
    root_rows = []
    for root in ROOT_SLEEVES:
        subset = daily.loc[daily["root"].eq(root) & daily["date"].between(START, END)]
        observed_sessions = int(subset["date"].nunique())
        by_session = subset.groupby("date")["contract"].nunique()
        curve_share = float(by_session.ge(2).mean()) if len(by_session) else 0.0
        root_rows.append(
            {
                "root": root,
                "sleeve": ROOT_SLEEVES[root],
                "first_date": subset["date"].min(),
                "last_date": subset["date"].max(),
                "contracts": int(subset["contract"].nunique()),
                "observed_sessions": observed_sessions,
                "session_coverage": observed_sessions / expected_sessions,
                "two_expiry_session_share": curve_share,
                "coverage_pass": bool(
                    observed_sessions / expected_sessions >= 0.95
                    and curve_share >= 0.60
                    and not subset.empty
                    and subset["date"].min() <= START
                    and subset["date"].max() >= END
                ),
            }
        )
    roots = pd.DataFrame(root_rows)
    admitted_roots = roots.loc[roots["coverage_pass"], "root"].tolist()
    admitted_sleeves = sorted(
        {ROOT_SLEEVES[root] for root in admitted_roots}
    )
    if len(admitted_roots) < 12:
        problems.append("fewer than 12 roots pass coverage and curve-depth requirements")
    if len(admitted_sleeves) < 3:
        problems.append("fewer than three sleeves pass the data gate")
    status = "V23_DATA_ADMITTED_RESEARCH_NOT_RUN" if not problems else "V23_BLOCKED_DATA_QUALITY"
    return {
        "status": status,
        "problems": problems,
        "admitted_roots": admitted_roots,
        "admitted_sleeves": admitted_sleeves,
        "required_root_count": 12,
        "required_sleeve_count": 3,
        "orders_allowed": False,
    }, roots


def write_report(output: Path, summary: dict) -> None:
    problems = "\n".join(f"- {problem}" for problem in summary.get("problems", []))
    missing = "\n".join(f"- `{path}`" for path in summary.get("missing_files", []))
    report = f"""# v23 Futures-Native Data Gate

## Decision

**{summary['status']}**

The strategy backtest was not run. v23 requires expiry-specific contracts, settlement, volume,
open interest, contract dates, multipliers and tick sizes. Continuous Yahoo-style tickers or ETF
prices cannot satisfy this gate.

## Missing inputs

{missing or '- None'}

## Quality issues

{problems or '- Not evaluated because required files are absent.'}

## Provider finding

Alpaca's official historical and streaming market-data documentation currently lists stocks,
crypto, options and news. It does not expose the contract-level futures archive required here:

- https://docs.alpaca.markets/us/docs/historical-api
- https://docs.alpaca.markets/us/docs/streaming-market-data

Alpaca credentials therefore do not unblock v23. A separately licensed futures history is needed.
This is a data-identification block, not evidence that Trend + Carry fails in futures. Orders remain
disabled.
"""
    (output / "REPORT.md").write_text(report)


def main(contracts: Path, metadata: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    missing = [str(path) for path in (contracts, metadata) if not path.exists()]
    if missing:
        summary = {
            "status": "V23_BLOCKED_DATA_UNAVAILABLE",
            "reason": "REQUIRED_CONTRACT_ARCHIVE_NOT_FOUND",
            "missing_files": missing,
            "problems": [],
            "admitted_roots": [],
            "admitted_sleeves": [],
            "protocol_sha256": sha256(PROTOCOL),
            "strategy_backtest_run": False,
            "orders_allowed": False,
        }
        pd.DataFrame(columns=[
            "root", "sleeve", "first_date", "last_date", "contracts",
            "observed_sessions", "session_coverage", "two_expiry_session_share",
            "coverage_pass",
        ]).to_csv(output / "root_coverage.csv", index=False)
    else:
        summary, roots = audit_tables(read_table(contracts), read_table(metadata))
        summary.update(
            protocol_sha256=sha256(PROTOCOL),
            strategy_backtest_run=False,
            contracts_sha256=sha256(contracts),
            metadata_sha256=sha256(metadata),
        )
        roots.to_csv(output / "root_coverage.csv", index=False)
    (output / "SUMMARY.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    write_report(output, summary)
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--contracts", type=Path, default=Path("data/futures/contracts_daily.parquet")
    )
    parser.add_argument(
        "--metadata", type=Path, default=Path("data/futures/contracts_metadata.csv")
    )
    parser.add_argument("--output", type=Path, default=Path("reports/futures_v23_data_gate"))
    arguments = parser.parse_args()
    main(arguments.contracts, arguments.metadata, arguments.output)
