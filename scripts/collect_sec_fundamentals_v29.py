"""Collect and normalize filing-date SEC Company Facts for the frozen v29 study."""

from __future__ import annotations

import argparse
import gzip
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.evaluate_equity_v7 import sha256

TICKER_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
FORMS = {"10-K", "10-K/A"}
TRAIN_START = pd.Timestamp("2018-01-02")
TRAIN_END = pd.Timestamp("2022-12-30")
CONCEPTS = {
    "assets": ("Assets",),
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ),
    "gross_profit": ("GrossProfit",),
    "net_income": ("NetIncomeLoss", "ProfitLoss"),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
}
FLOW_CONCEPTS = {"revenue", "gross_profit", "net_income", "operating_cash_flow"}


def canonical_ticker(value: str) -> str:
    """Normalize common class-share separators for ticker/CIK matching."""
    return str(value).strip().upper().replace(".", "-").replace("/", "-")


def fetch_json(url: str, user_agent: str, retries: int = 4) -> dict:
    """Fetch one SEC JSON resource with declared identity and bounded retries."""
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept-Encoding": "gzip, deflate",
            "Accept": "application/json",
        },
    )
    delay = 1.0
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = response.read()
                if response.headers.get("Content-Encoding") == "gzip":
                    payload = gzip.decompress(payload)
                return json.loads(payload)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            if attempt + 1 == retries:
                raise
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("unreachable SEC fetch retry state")


def ticker_mapping(payload: dict, candidates: pd.DataFrame) -> pd.DataFrame:
    """Map candidate symbols to the current SEC ticker/CIK association table."""
    fields = payload["fields"]
    mapping = pd.DataFrame(payload["data"], columns=fields)
    mapping["canonical_symbol"] = mapping["ticker"].map(canonical_ticker)
    duplicates = mapping["canonical_symbol"].duplicated(keep=False)
    mapping["mapping_ambiguous"] = duplicates
    candidates = candidates.copy()
    candidates["canonical_symbol"] = candidates["symbol"].map(canonical_ticker)
    merged = candidates.merge(
        mapping[["canonical_symbol", "cik", "name", "exchange", "mapping_ambiguous"]],
        on="canonical_symbol",
        how="left",
        suffixes=("_candidate", "_sec"),
    )
    merged["mapped"] = merged["cik"].notna() & ~merged["mapping_ambiguous"].fillna(False)
    return merged


def extract_company_facts(payload: dict, symbol: str, sector: str) -> pd.DataFrame:
    """Extract frozen annual concepts from one Company Facts response."""
    us_gaap = payload.get("facts", {}).get("us-gaap", {})
    rows = []
    for canonical, tags in CONCEPTS.items():
        for priority, tag in enumerate(tags):
            concept = us_gaap.get(tag, {})
            for item in concept.get("units", {}).get("USD", []):
                if item.get("form") not in FORMS or item.get("fp") != "FY":
                    continue
                filed = pd.to_datetime(item.get("filed"), errors="coerce")
                end = pd.to_datetime(item.get("end"), errors="coerce")
                value = pd.to_numeric(item.get("val"), errors="coerce")
                if pd.isna(filed) or pd.isna(end) or not np.isfinite(value):
                    continue
                start = pd.to_datetime(item.get("start"), errors="coerce")
                if canonical in FLOW_CONCEPTS:
                    if pd.isna(start):
                        continue
                    duration = (end - start).days
                    if duration < 300 or duration > 430:
                        continue
                rows.append(
                    {
                        "symbol": symbol,
                        "sector": sector,
                        "cik": int(payload["cik"]),
                        "entity_name": payload.get("entityName"),
                        "concept": canonical,
                        "tag": tag,
                        "tag_priority": priority,
                        "accession": item.get("accn"),
                        "form": item.get("form"),
                        "fiscal_year": item.get("fy"),
                        "period_start": start,
                        "period_end": end,
                        "filed": filed,
                        "value": float(value),
                    }
                )
    if not rows:
        return pd.DataFrame()
    facts = pd.DataFrame(rows)
    facts = facts.loc[facts["accession"].notna()].copy()
    latest_period = facts.groupby("accession")["period_end"].transform("max")
    facts = facts.loc[facts["period_end"].eq(latest_period)]
    facts = facts.sort_values("tag_priority").drop_duplicates(
        ["accession", "concept"], keep="first"
    )
    return facts


def build_filing_events(facts: pd.DataFrame) -> pd.DataFrame:
    """Build filing-date ratios and causal prior-annual growth features."""
    columns = [
        "symbol",
        "sector",
        "cik",
        "entity_name",
        "accession",
        "form",
        "fiscal_year",
        "period_end",
        "filed",
    ]
    if facts.empty:
        return pd.DataFrame(columns=columns)
    events = (
        facts.pivot_table(
            index=columns,
            columns="concept",
            values="value",
            aggfunc="first",
        )
        .reset_index()
        .sort_values(["symbol", "filed", "period_end", "accession"])
    )
    events["available_at"] = events["filed"] + pd.offsets.BDay(1)
    ratio_denominator = events["assets"].where(events["assets"].gt(0))
    events["profitability"] = events.get("net_income", np.nan) / ratio_denominator
    events["gross_profitability"] = events.get("gross_profit", np.nan) / ratio_denominator
    events["cash_profitability"] = (
        events.get("operating_cash_flow", np.nan) / ratio_denominator
    )
    events["accrual_quality"] = (
        events.get("operating_cash_flow", np.nan) - events.get("net_income", np.nan)
    ) / ratio_denominator
    events["asset_growth"] = np.nan
    events["revenue_growth"] = np.nan
    for locations in events.groupby("symbol").groups.values():
        history: dict[pd.Timestamp, dict[str, float]] = {}
        for location in sorted(locations, key=lambda loc: events.loc[loc, "filed"]):
            end = events.loc[location, "period_end"]
            prior_ends = [period for period in history if period < end]
            if prior_ends:
                prior = history[max(prior_ends)]
                assets = events.loc[location].get("assets", np.nan)
                revenue = events.loc[location].get("revenue", np.nan)
                if np.isfinite(assets) and prior.get("assets", 0) > 0:
                    events.loc[location, "asset_growth"] = -(assets / prior["assets"] - 1)
                if np.isfinite(revenue) and prior.get("revenue", 0) > 0:
                    events.loc[location, "revenue_growth"] = revenue / prior["revenue"] - 1
            history[end] = {
                "assets": events.loc[location].get("assets", np.nan),
                "revenue": events.loc[location].get("revenue", np.nan),
            }
    events = events.replace([np.inf, -np.inf], np.nan)
    return events


def data_gate(mapping: pd.DataFrame, events: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    """Evaluate the frozen mapping, event-depth and sector-coverage requirements."""
    usable = events.loc[events["available_at"].between(TRAIN_START, TRAIN_END)].copy()
    per_symbol = usable.groupby("symbol")["accession"].nunique()
    covered_symbols = set(per_symbol.index)
    sector_coverage = (
        mapping.loc[mapping["symbol"].isin(covered_symbols)]
        .groupby("sector")["symbol"]
        .nunique()
        .rename("covered_symbols")
        .reset_index()
    )
    components = {
        "unique_cik_mapping": int(mapping["mapped"].sum()) >= 400,
        "one_train_event": int(per_symbol.ge(1).sum()) >= 250,
        "three_train_events": int(per_symbol.ge(3).sum()) >= 200,
        "sector_depth": int(sector_coverage["covered_symbols"].ge(10).sum()) >= 8,
        "unique_symbol_date": not events.duplicated(["symbol", "available_at"]).any(),
    }
    summary = {
        "status": "V29_DATA_ADMITTED_ALPHA_NOT_RUN" if all(components.values()) else "V29_BLOCKED_SEC_DATA_QUALITY",
        "components": components,
        "candidate_symbols": int(mapping["symbol"].nunique()),
        "uniquely_mapped_symbols": int(mapping["mapped"].sum()),
        "symbols_with_one_train_event": int(per_symbol.ge(1).sum()),
        "symbols_with_three_train_events": int(per_symbol.ge(3).sum()),
        "sectors_with_ten_covered_symbols": int(
            sector_coverage["covered_symbols"].ge(10).sum()
        ),
        "usable_train_events": len(usable),
        "orders_allowed": False,
    }
    return summary, sector_coverage


def main(
    candidates_path: Path,
    output: Path,
    user_agent: str,
    requests_per_second: float,
) -> None:
    if not user_agent.strip():
        raise ValueError("a declared SEC user agent is required")
    if requests_per_second <= 0 or requests_per_second > 5:
        raise ValueError("requests_per_second must be in (0, 5]")
    output.mkdir(parents=True, exist_ok=True)
    raw_dir = output / "companyfacts"
    raw_dir.mkdir(exist_ok=True)
    candidates = pd.read_csv(candidates_path)
    ticker_file = output / "company_tickers_exchange.json"
    if ticker_file.exists():
        ticker_payload = json.loads(ticker_file.read_text())
    else:
        ticker_payload = fetch_json(TICKER_URL, user_agent)
        ticker_file.write_text(json.dumps(ticker_payload))
    mapping = ticker_mapping(ticker_payload, candidates)
    mapping.to_csv(output / "ticker_cik_mapping.csv", index=False)

    fact_frames = []
    request_rows = []
    interval = 1 / requests_per_second
    for row in mapping.loc[mapping["mapped"]].itertuples(index=False):
        cik = int(row.cik)
        path = raw_dir / f"CIK{cik:010d}.json"
        fetched = False
        if not path.exists():
            payload = fetch_json(COMPANY_FACTS_URL.format(cik=cik), user_agent)
            path.write_text(json.dumps(payload))
            fetched = True
            time.sleep(interval)
        else:
            payload = json.loads(path.read_text())
        request_rows.append(
            {
                "symbol": row.symbol,
                "cik": cik,
                "cached": not fetched,
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
        )
        facts = extract_company_facts(payload, row.symbol, row.sector)
        if not facts.empty:
            fact_frames.append(facts)
    facts = pd.concat(fact_frames, ignore_index=True) if fact_frames else pd.DataFrame()
    events = build_filing_events(facts)
    events.to_csv(output / "annual_fundamental_events.csv.gz", index=False, compression="gzip")
    pd.DataFrame(request_rows).to_csv(output / "request_manifest.csv", index=False)
    gate, sector_coverage = data_gate(mapping, events)
    sector_coverage.to_csv(output / "sector_coverage.csv", index=False)
    gate.update(
        source="SEC Company Facts",
        candidates_sha256=sha256(candidates_path),
        ticker_mapping_sha256=sha256(ticker_file),
        annual_events_sha256=sha256(output / "annual_fundamental_events.csv.gz"),
        raw_files=len(request_rows),
        total_raw_bytes=int(sum(row["bytes"] for row in request_rows)),
        collected_at=pd.Timestamp.now(tz="UTC").isoformat(),
    )
    (output / "DATA_GATE.json").write_text(json.dumps(gate, indent=2) + "\n")
    print(json.dumps(gate, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--candidates",
        type=Path,
        default=Path("output/equities_2026-09-20_sip_r2/equity_candidates.csv"),
    )
    parser.add_argument("--output", type=Path, default=Path("data/raw/sec_v29"))
    parser.add_argument(
        "--user-agent",
        default=os.environ.get("SEC_USER_AGENT", ""),
        help="Declared SEC bot identity, preferably project plus contact URL/email",
    )
    parser.add_argument("--requests-per-second", type=float, default=4.0)
    arguments = parser.parse_args()
    main(
        arguments.candidates,
        arguments.output,
        arguments.user_agent,
        arguments.requests_per_second,
    )
