"""Collect and normalize Valuein point-in-time fundamentals for v31."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

BASE_URL = "https://data.valuein.biz"
TABLES = (
    "references",
    "security",
    "filing",
    "fact",
    "index_membership",
    "standard_concept",
    "ratio",
)
CONCEPTS = {
    "TotalAssets": "assets",
    "TotalRevenue": "revenue",
    "GrossProfit": "gross_profit",
    "NetIncome": "net_income",
    "OperatingCashFlow": "operating_cash_flow",
}
FLOW_CONCEPTS = {"revenue", "gross_profit", "net_income", "operating_cash_flow"}
ANNUAL_FORMS = {"10-K", "10-K/A"}
TRAIN_START = pd.Timestamp("2018-01-02")
TRAIN_END = pd.Timestamp("2022-12-30")
DEVELOPMENT_END = pd.Timestamp("2024-12-31")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def endpoint(plan: str, table: str | None = None) -> str:
    if plan == "sample":
        suffix = "/v1/sample/manifest" if table is None else f"/v1/sample/{table}"
    else:
        suffix = "/v1/manifest" if table is None else f"/v1/{plan}/{table}"
    return f"{BASE_URL}{suffix}"


def _headers(plan: str) -> dict[str, str]:
    if plan == "sample":
        return {}
    token = os.environ.get("VALUEIN_TOKEN", "").strip()
    if not token:
        raise RuntimeError("VALUEIN_TOKEN is required for non-sample plans")
    return {"Authorization": f"Bearer {token}"}


def _request(
    session: Any,
    url: str,
    headers: dict[str, str],
    stream: bool,
    retries: int = 4,
) -> Any:
    delay = 1.0
    for attempt in range(retries):
        response = session.get(url, headers=headers, stream=stream, timeout=180)
        if response.status_code == 429:
            if attempt + 1 == retries:
                response.raise_for_status()
            time.sleep(float(response.headers.get("Retry-After", delay)))
            continue
        if response.status_code == 503 or response.status_code >= 500:
            if attempt + 1 == retries:
                response.raise_for_status()
            time.sleep(delay)
            delay *= 2
            continue
        response.raise_for_status()
        return response
    raise RuntimeError("unreachable Valuein retry state")


def fetch_manifest(plan: str, session: Any) -> dict:
    response = _request(session, endpoint(plan), _headers(plan), stream=False)
    return response.json()


def _total_size(content_range: str | None) -> int:
    match = re.fullmatch(r"bytes\s+\d+-\d+/(\d+)", content_range or "")
    if not match:
        raise RuntimeError(f"Valuein response lacks a valid Content-Range: {content_range!r}")
    return int(match.group(1))


def _download_table(
    session: Any,
    url: str,
    headers: dict[str, str],
    destination: Path,
    attempts: int = 12,
) -> Any:
    """Download one table with byte-range resume and exact-size validation."""
    import requests

    probe_headers = {**headers, "Range": "bytes=0-0"}
    probe = _request(session, url, probe_headers, stream=True)
    total = _total_size(probe.headers.get("Content-Range"))
    response_headers = dict(probe.headers)
    probe.close()
    if destination.exists() and destination.stat().st_size == total:
        return response_headers

    temporary = destination.with_suffix(".parquet.part")
    if temporary.exists() and temporary.stat().st_size > total:
        temporary.unlink()
    last_error: Exception | None = None
    for _ in range(attempts):
        offset = temporary.stat().st_size if temporary.exists() else 0
        if offset == total:
            temporary.replace(destination)
            return response_headers
        range_headers = {**headers, "Range": f"bytes={offset}-"}
        response = None
        try:
            response = _request(session, url, range_headers, stream=True)
            if response.status_code != 206:
                raise RuntimeError(
                    f"Valuein resume expected HTTP 206, received {response.status_code}"
                )
            mode = "ab" if offset else "wb"
            with temporary.open(mode) as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)
            response_headers = dict(response.headers)
        except (requests.RequestException, OSError, RuntimeError) as exc:
            last_error = exc
            time.sleep(1)
        finally:
            if response is not None:
                response.close()
    actual = temporary.stat().st_size if temporary.exists() else 0
    if actual != total:
        raise RuntimeError(
            f"Valuein download incomplete after resume attempts: {actual}/{total} bytes"
        ) from last_error
    temporary.replace(destination)
    return response_headers


def download_tables(plan: str, raw_dir: Path, tables: tuple[str, ...] = TABLES) -> dict:
    """Download one immutable Valuein snapshot without persisting the bearer token."""
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError("install the valuein dependency: pip install -e '.[valuein]'") from exc
    session = requests.Session()
    manifest = fetch_manifest(plan, session)
    available = set(manifest.get("tables", []))
    invalid = sorted(set(tables) - available)
    if invalid:
        raise ValueError(f"tables absent from Valuein manifest: {','.join(invalid)}")
    snapshot = str(manifest.get("snapshot", "unknown"))
    snapshot_dir = raw_dir / snapshot
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / "provider_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n"
    )
    records = []
    headers = _headers(plan)
    for table in tables:
        destination = snapshot_dir / f"{table}.parquet"
        response_headers = _download_table(
            session, endpoint(plan, table), headers, destination
        )
        records.append(
            {
                "table": table,
                "file": str(destination),
                "bytes": destination.stat().st_size,
                "sha256": sha256(destination),
                "etag": response_headers.get("ETag"),
                "request_id": response_headers.get("X-Request-ID"),
            }
        )
    result = {
        "status": "VALUEIN_SNAPSHOT_DOWNLOADED_NORMALIZATION_REQUIRED",
        "plan": plan,
        "snapshot": snapshot,
        "last_updated": manifest.get("last_updated"),
        "schema_version": manifest.get("schema_version"),
        "tables": records,
        "credentials_persisted": False,
        "orders_allowed": False,
    }
    (snapshot_dir / "DOWNLOAD_MANIFEST.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def _read_fact_subset(path: Path) -> pd.DataFrame:
    columns = [
        "fact_id",
        "entity_id",
        "accession_id",
        "standard_concept",
        "priority",
        "value_as_filed",
        "unit",
        "period_start",
        "period_end",
        "fiscal_year",
        "fiscal_period",
        "accepted_at",
        "period_span_days",
        "restated",
    ]
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError("install the valuein dependency: pip install -e '.[valuein]'") from exc
    table = pq.read_table(
        path,
        columns=columns,
        filters=[("standard_concept", "in", list(CONCEPTS))],
    )
    return table.to_pandas()


def _security_mapping(references: pd.DataFrame, security: pd.DataFrame) -> pd.DataFrame:
    required_reference = {"cik", "sector", "security_id"}
    required_security = {
        "id",
        "entity_id",
        "symbol",
        "valid_from",
        "valid_to",
        "is_primary_ticker",
    }
    missing = sorted(
        (required_reference - set(references.columns))
        | (required_security - set(security.columns))
    )
    if missing:
        raise ValueError(f"Valuein security mapping missing columns: {','.join(missing)}")
    reference_mapping = references.loc[
        references["security_id"].notna(), ["security_id", "cik", "sector"]
    ].drop_duplicates("security_id")
    mapping = security[list(required_security)].merge(
        reference_mapping,
        left_on="id",
        right_on="security_id",
        how="left",
        validate="many_to_one",
    )
    mapping["valid_from"] = pd.to_datetime(mapping["valid_from"], errors="coerce")
    mapping["valid_to"] = pd.to_datetime(mapping["valid_to"], errors="coerce")
    mapping["cik"] = mapping["cik"].astype("string")
    return mapping.dropna(subset=["entity_id", "symbol", "cik", "valid_from"])


def normalize_fundamental_events(
    facts: pd.DataFrame,
    filings: pd.DataFrame,
    security_mapping: pd.DataFrame,
) -> pd.DataFrame:
    """Build as-filed annual events using accepted timestamps and SCD tickers."""
    filing_columns = {
        "entity_id",
        "accession_id",
        "filing_date",
        "form_type",
        "is_amendment",
        "accepted_at",
        "report_date",
    }
    missing = sorted(filing_columns - set(filings.columns))
    if missing:
        raise ValueError(f"filing table missing columns: {','.join(missing)}")
    annual = filings.loc[
        filings["form_type"].astype(str).str.upper().isin(ANNUAL_FORMS),
        list(filing_columns),
    ].copy()
    annual = annual.rename(columns={"accepted_at": "filing_accepted_at"})
    joined = facts.merge(
        annual,
        on=["entity_id", "accession_id"],
        how="inner",
        validate="many_to_one",
    )
    joined["fact_accepted_at"] = pd.to_datetime(joined["accepted_at"], utc=True, errors="coerce")
    joined["filing_accepted_at"] = pd.to_datetime(
        joined["filing_accepted_at"], utc=True, errors="coerce"
    )
    joined["accepted_at"] = joined[["fact_accepted_at", "filing_accepted_at"]].max(axis=1)
    joined["filing_date"] = pd.to_datetime(joined["filing_date"], errors="coerce")
    joined["report_date"] = pd.to_datetime(joined["report_date"], errors="coerce")
    joined["period_end"] = pd.to_datetime(joined["period_end"], errors="coerce")
    joined["period_start"] = pd.to_datetime(joined["period_start"], errors="coerce")
    joined["value"] = pd.to_numeric(joined["value_as_filed"], errors="coerce")
    joined["concept"] = joined["standard_concept"].map(CONCEPTS)
    joined["period_span_days"] = pd.to_numeric(joined["period_span_days"], errors="coerce")
    is_flow = joined["concept"].isin(FLOW_CONCEPTS)
    joined = joined.loc[
        joined["accepted_at"].notna()
        & joined["period_end"].notna()
        & joined["period_end"].eq(joined["report_date"])
        & joined["value"].map(np.isfinite)
        & (~is_flow | joined["period_span_days"].between(300, 430))
    ].copy()
    joined["availability_date"] = (
        joined["accepted_at"].dt.tz_convert(None).dt.normalize() + pd.offsets.BDay(1)
    )
    joined = joined.merge(
        security_mapping,
        on="entity_id",
        how="inner",
        validate="many_to_many",
    )
    valid_ticker = joined["availability_date"].ge(joined["valid_from"]) & (
        joined["valid_to"].isna() | joined["availability_date"].le(joined["valid_to"])
    )
    joined = joined.loc[valid_ticker].copy()
    joined["priority"] = pd.to_numeric(joined["priority"], errors="coerce").fillna(999)
    joined = joined.sort_values(
        ["entity_id", "accession_id", "concept", "is_primary_ticker", "priority"],
        ascending=[True, True, True, False, True],
    ).drop_duplicates(["entity_id", "accession_id", "concept"], keep="first")

    index = [
        "symbol",
        "cik",
        "sector",
        "entity_id",
        "accession_id",
        "form_type",
        "is_amendment",
        "filing_date",
        "accepted_at",
        "availability_date",
        "period_end",
        "fiscal_year",
    ]
    events = joined.pivot(index=index, columns="concept", values="value").reset_index()
    events = events.sort_values(["entity_id", "availability_date", "period_end", "accession_id"])
    denominator = events.get("assets", pd.Series(np.nan, index=events.index)).where(
        lambda value: value.gt(0)
    )
    events["profitability"] = events.get("net_income", np.nan) / denominator
    events["gross_profitability"] = events.get("gross_profit", np.nan) / denominator
    events["cash_profitability"] = events.get("operating_cash_flow", np.nan) / denominator
    events["accrual_quality"] = (
        events.get("operating_cash_flow", np.nan) - events.get("net_income", np.nan)
    ) / denominator
    events["asset_growth"] = np.nan
    events["revenue_growth"] = np.nan
    for locations in events.groupby("entity_id").groups.values():
        history: dict[pd.Timestamp, dict[str, float]] = {}
        ordered = sorted(locations, key=lambda location: events.loc[location, "availability_date"])
        for location in ordered:
            period = events.loc[location, "period_end"]
            prior_periods = [candidate for candidate in history if candidate < period]
            if prior_periods:
                prior = history[max(prior_periods)]
                assets = events.loc[location].get("assets", np.nan)
                revenue = events.loc[location].get("revenue", np.nan)
                if np.isfinite(assets) and prior.get("assets", 0) > 0:
                    events.loc[location, "asset_growth"] = -(assets / prior["assets"] - 1)
                if np.isfinite(revenue) and prior.get("revenue", 0) > 0:
                    events.loc[location, "revenue_growth"] = revenue / prior["revenue"] - 1
            history[period] = {
                "assets": events.loc[location].get("assets", np.nan),
                "revenue": events.loc[location].get("revenue", np.nan),
            }
    events["restatement_flag"] = events["is_amendment"].fillna(False).astype(bool)
    return events.replace([np.inf, -np.inf], np.nan)


def build_daily_membership(
    membership: pd.DataFrame,
    security_mapping: pd.DataFrame,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Reconstruct S&P 500 membership and the valid ticker on every session."""
    required = {"cik", "index_name", "effective_date", "removal_date"}
    missing = sorted(required - set(membership.columns))
    if missing:
        raise ValueError(f"index membership missing columns: {','.join(missing)}")
    members = membership.loc[
        membership["index_name"].astype(str).str.upper().str.replace(" ", "").isin(
            {"SP500", "S&P500"}
        )
    ].copy()
    members["cik"] = members["cik"].astype("string")
    members["effective_date"] = pd.to_datetime(members["effective_date"], errors="coerce")
    members["removal_date"] = pd.to_datetime(members["removal_date"], errors="coerce")
    mapping = security_mapping.loc[security_mapping["is_primary_ticker"].fillna(False)].copy()
    records = []
    for date in pd.DatetimeIndex(sessions).normalize():
        active = members.loc[
            members["effective_date"].le(date)
            & (members["removal_date"].isna() | members["removal_date"].gt(date))
        ]
        candidates = active[["cik"]].drop_duplicates().merge(mapping, on="cik", how="inner")
        valid = candidates.loc[
            candidates["valid_from"].le(date)
            & (candidates["valid_to"].isna() | candidates["valid_to"].ge(date))
        ].copy()
        valid["date"] = date
        records.append(valid[["date", "cik", "entity_id", "symbol", "sector"]])
    if not records:
        return pd.DataFrame(columns=["date", "cik", "entity_id", "symbol", "sector"])
    return pd.concat(records, ignore_index=True).drop_duplicates(["date", "cik"])


def valuein_data_gate(events: pd.DataFrame, membership: pd.DataFrame) -> dict:
    train_events = events.loc[events["availability_date"].between(TRAIN_START, TRAIN_END)]
    per_entity = train_events.groupby("entity_id")["accession_id"].nunique()
    train_membership = membership.loc[membership["date"].between(TRAIN_START, TRAIN_END)]
    member_counts = train_membership.groupby("date")["cik"].nunique()
    covered = set(train_events["entity_id"])
    sectors = (
        train_membership.loc[train_membership["entity_id"].isin(covered)]
        .groupby("sector")["entity_id"]
        .nunique()
    )
    components = {
        "membership_session_coverage": int(member_counts.ge(400).sum())
        >= int(0.95 * len(pd.bdate_range(TRAIN_START, TRAIN_END))),
        "one_train_event": int(per_entity.ge(1).sum()) >= 250,
        "three_train_events": int(per_entity.ge(3).sum()) >= 200,
        "sector_depth": int(sectors.ge(10).sum()) >= 8,
        "unique_entity_availability": not events.duplicated(
            ["entity_id", "availability_date"]
        ).any(),
    }
    return {
        "status": (
            "V31_VALUEIN_DATA_ADMITTED_ALPHA_NOT_RUN"
            if all(components.values())
            else "V31_BLOCKED_PIT_DATA"
        ),
        "components": components,
        "first_event": events["availability_date"].min(),
        "last_event": events["availability_date"].max(),
        "train_events": len(train_events),
        "entities_with_one_train_event": int(per_entity.ge(1).sum()),
        "entities_with_three_train_events": int(per_entity.ge(3).sum()),
        "train_membership_sessions": int(member_counts.size),
        "train_sessions_with_400_members": int(member_counts.ge(400).sum()),
        "sectors_with_ten_covered_entities": int(sectors.ge(10).sum()),
        "orders_allowed": False,
    }


def normalize_snapshot(snapshot_dir: Path, output: Path) -> dict:
    paths = {table: snapshot_dir / f"{table}.parquet" for table in TABLES}
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise FileNotFoundError(f"missing Valuein tables: {missing}")
    references = pd.read_parquet(paths["references"])
    security = pd.read_parquet(paths["security"])
    filings = pd.read_parquet(paths["filing"])
    membership = pd.read_parquet(paths["index_membership"])
    facts = _read_fact_subset(paths["fact"])
    mapping = _security_mapping(references, security)
    events = normalize_fundamental_events(facts, filings, mapping)
    sessions = pd.bdate_range(TRAIN_START, DEVELOPMENT_END)
    daily_membership = build_daily_membership(membership, mapping, sessions)
    gate = valuein_data_gate(events, daily_membership)

    output.mkdir(parents=True, exist_ok=True)
    events.to_parquet(output / "fundamental_events.parquet", index=False)
    daily_membership.to_parquet(output / "sp500_membership_daily.parquet", index=False)
    mapping.to_parquet(output / "security_mapping_scd.parquet", index=False)
    gate.update(
        source="Valuein",
        snapshot=snapshot_dir.name,
        raw_hashes={name: sha256(path) for name, path in paths.items()},
        as_filed_value_used=True,
        accepted_at_used=True,
        historical_membership_used=True,
        orders_allowed=False,
    )
    (output / "DATA_GATE.json").write_text(json.dumps(gate, indent=2, default=str) + "\n")
    return gate


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="mode", required=True)
    download_parser = subparsers.add_parser("download")
    download_parser.add_argument("--plan", choices=["sample", "sp500", "pro", "full"], default="sample")
    download_parser.add_argument("--raw-dir", type=Path, default=Path("data/raw/valuein"))
    normalize_parser = subparsers.add_parser("normalize")
    normalize_parser.add_argument("--snapshot-dir", type=Path, required=True)
    normalize_parser.add_argument("--output", type=Path, default=Path("data/processed/valuein_v31"))
    arguments = parser.parse_args()
    if arguments.mode == "download":
        result = download_tables(arguments.plan, arguments.raw_dir)
    else:
        result = normalize_snapshot(arguments.snapshot_dir, arguments.output)
    print(json.dumps(result, indent=2, default=str))
