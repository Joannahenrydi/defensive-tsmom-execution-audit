"""Estimate, collect and normalize expiry-specific CME futures data from Databento."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from scripts.audit_futures_v23_data import ROOT_SLEEVES, audit_tables
from scripts.evaluate_equity_v7 import sha256

DATASET = "GLBX.MDP3"
SCHEMAS = ("definition", "ohlcv-1d", "statistics")
CASH_SETTLED_ROOTS = {"ES", "NQ", "RTY"}
STAT_NAMES = {
    1: "official_open",
    3: "settlement",
    4: "official_low",
    5: "official_high",
    6: "cleared_volume",
    9: "open_interest",
}


def _time_column(frame: pd.DataFrame, names: tuple[str, ...]) -> pd.Series:
    for name in names:
        if name in frame.columns:
            return pd.to_datetime(frame[name], utc=True, errors="coerce")
    return pd.to_datetime(frame.index, utc=True, errors="coerce")


def attach_contract_asof(
    events: pd.DataFrame, definitions: pd.DataFrame, event_time_names: tuple[str, ...]
) -> pd.DataFrame:
    """Attach the most recent point-in-time raw symbol to each instrument event."""
    if events.empty:
        return events.copy()
    left = events.copy()
    right = definitions.copy()
    left["_event_time"] = _time_column(left, event_time_names)
    right["_definition_time"] = _time_column(right, ("ts_recv", "ts_event"))
    right = right.dropna(subset=["instrument_id", "raw_symbol", "_definition_time"])
    pieces = []
    for instrument_id, group in left.groupby("instrument_id", sort=False):
        mapping = right.loc[right["instrument_id"].eq(instrument_id), [
            "_definition_time",
            "raw_symbol",
        ]].sort_values("_definition_time")
        if mapping.empty:
            continue
        joined = pd.merge_asof(
            group.sort_values("_event_time"),
            mapping,
            left_on="_event_time",
            right_on="_definition_time",
            direction="backward",
        )
        pieces.append(joined)
    return pd.concat(pieces, ignore_index=True) if pieces else pd.DataFrame()


def normalize_root_frames(
    root: str,
    definitions: pd.DataFrame,
    bars: pd.DataFrame,
    statistics: pd.DataFrame,
    notices: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Normalize one parent product into daily rows and point-in-time metadata."""
    definitions = definitions.copy()
    class_text = definitions["instrument_class"].astype(str).str.upper()
    definitions = definitions.loc[class_text.isin({"F", "FUTURE", "INSTRUMENTCLASS.FUTURE"})]
    definitions["definition_time"] = _time_column(definitions, ("ts_recv", "ts_event"))
    definitions["root"] = root
    definitions["contract"] = definitions["raw_symbol"].astype(str)
    definitions["sleeve"] = ROOT_SLEEVES[root]
    definitions["expiry_date"] = pd.to_datetime(
        definitions["expiration"], utc=True, errors="coerce"
    ).dt.tz_localize(None)
    definitions["last_trade_date"] = definitions["expiry_date"]
    definitions["tick_size"] = pd.to_numeric(
        definitions["min_price_increment"], errors="coerce"
    )
    unit_qty = pd.to_numeric(
        definitions.get("unit_of_measure_qty", np.nan), errors="coerce"
    )
    contract_multiplier = pd.to_numeric(
        definitions.get("contract_multiplier", np.nan), errors="coerce"
    )
    definitions["multiplier"] = unit_qty.where(unit_qty.gt(0), contract_multiplier)
    definitions["cash_settled"] = root in CASH_SETTLED_ROOTS
    definitions["first_notice_date"] = pd.NaT

    if notices is not None and not notices.empty:
        notice = notices.copy()
        notice["contract"] = notice["contract"].astype(str)
        notice["first_notice_date"] = pd.to_datetime(
            notice["first_notice_date"], errors="coerce"
        )
        definitions = definitions.drop(columns="first_notice_date").merge(
            notice[["contract", "first_notice_date"]], on="contract", how="left"
        )

    bars = attach_contract_asof(bars, definitions, ("ts_event", "ts_recv"))
    statistics = attach_contract_asof(statistics, definitions, ("ts_recv", "ts_event"))
    if bars.empty or statistics.empty:
        return pd.DataFrame(), pd.DataFrame(), definitions

    bars["date"] = bars["_event_time"].dt.tz_localize(None).dt.normalize()
    bar_columns = ["date", "raw_symbol", "open", "high", "low", "volume"]
    bars = (
        bars.sort_values("_event_time")
        .drop_duplicates(["date", "raw_symbol"], keep="last")[bar_columns]
        .rename(columns={"raw_symbol": "contract", "volume": "bar_volume"})
    )

    statistics["date"] = pd.to_datetime(
        statistics["ts_ref"], utc=True, errors="coerce"
    ).dt.tz_localize(None).dt.normalize()
    statistics["stat_name"] = pd.to_numeric(
        statistics["stat_type"], errors="coerce"
    ).map(STAT_NAMES)
    statistics = statistics.dropna(subset=["date", "raw_symbol", "stat_name"])
    statistics["stat_value"] = np.where(
        statistics["stat_name"].isin(
            ["cleared_volume", "open_interest"]
        ),
        pd.to_numeric(statistics.get("quantity"), errors="coerce"),
        pd.to_numeric(statistics.get("price"), errors="coerce"),
    )
    latest = statistics.sort_values("_event_time").drop_duplicates(
        ["date", "raw_symbol", "stat_name"], keep="last"
    )
    stats_wide = latest.pivot(
        index=["date", "raw_symbol"], columns="stat_name", values="stat_value"
    ).reset_index().rename(columns={"raw_symbol": "contract"})
    daily = bars.merge(stats_wide, on=["date", "contract"], how="inner")
    daily["root"] = root
    daily["volume"] = daily["cleared_volume"].where(
        daily["cleared_volume"].notna(), daily["bar_volume"]
    )
    daily = daily[[
        "date",
        "root",
        "contract",
        "settlement",
        "open",
        "high",
        "low",
        "volume",
        "open_interest",
    ]]

    latest_definitions = (
        definitions.sort_values("definition_time")
        .drop_duplicates("contract", keep="last")
        .rename(columns={"raw_symbol": "vendor_symbol"})
    )
    metadata = latest_definitions[[
        "root",
        "contract",
        "sleeve",
        "exchange",
        "currency",
        "multiplier",
        "tick_size",
        "expiry_date",
        "first_notice_date",
        "last_trade_date",
        "cash_settled",
    ]]
    history_columns = [
        "definition_time",
        "root",
        "contract",
        "instrument_id",
        "security_update_action",
        "exchange",
        "currency",
        "multiplier",
        "tick_size",
        "expiry_date",
        "last_trade_date",
    ]
    history = definitions[[column for column in history_columns if column in definitions]]
    return daily, metadata, history


def request_costs(client: Any, roots: list[str], start: str, end: str) -> dict:
    """Get provider estimates without triggering billable time-series downloads."""
    symbols = [f"{root}.FUT" for root in roots]
    costs = {
        schema: float(
            client.metadata.get_cost(
                dataset=DATASET,
                symbols=symbols,
                stype_in="parent",
                schema=schema,
                start=start,
                end=end,
            )
        )
        for schema in SCHEMAS
    }
    costs["total"] = sum(costs.values())
    return costs


def _client() -> Any:
    key = os.environ.get("DATABENTO_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "DATABENTO_API_KEY is required and must not be passed on the command line"
        )
    try:
        import databento as db
    except ImportError as exc:
        raise RuntimeError(
            "install the optional futures dependency: pip install -e '.[futures]'"
        ) from exc
    return db.Historical(key=key)


def estimate(roots: list[str], start: str, end: str, output: Path) -> dict:
    client = _client()
    costs = request_costs(client, roots, start, end)
    result = {
        "status": "COST_ESTIMATE_ONLY",
        "dataset": DATASET,
        "roots": roots,
        "start": start,
        "end": end,
        "estimated_cost_usd": costs,
        "download_executed": False,
        "orders_allowed": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    return result


def download(
    roots: list[str], start: str, end: str, raw_dir: Path, approved_cost_usd: float
) -> dict:
    """Download only after the caller supplies a reviewed maximum provider charge."""
    if approved_cost_usd <= 0:
        raise ValueError("approved_cost_usd must be positive")
    client = _client()
    costs = request_costs(client, roots, start, end)
    if costs["total"] > approved_cost_usd:
        raise RuntimeError(
            f"estimated cost ${costs['total']:.2f} exceeds approved cap ${approved_cost_usd:.2f}"
        )
    raw_dir.mkdir(parents=True, exist_ok=True)
    symbols = [f"{root}.FUT" for root in roots]
    manifest = []
    for schema in SCHEMAS:
        path = raw_dir / f"{schema}.dbn.zst"
        store = client.timeseries.get_range(
            dataset=DATASET,
            symbols=symbols,
            stype_in="parent",
            schema=schema,
            start=start,
            end=end,
        )
        store.to_file(path)
        manifest.append({"schema": schema, "path": str(path), "sha256": sha256(path)})
    result = {
        "status": "RAW_DATABENTO_DOWNLOAD_COMPLETE_NORMALIZATION_REQUIRED",
        "dataset": DATASET,
        "roots": roots,
        "start": start,
        "end": end,
        "estimated_cost_usd": costs,
        "approved_cost_cap_usd": approved_cost_usd,
        "files": manifest,
        "orders_allowed": False,
    }
    (raw_dir / "MANIFEST.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def normalize_download(
    raw_dir: Path,
    output_dir: Path,
    roots: list[str],
    notices_path: Path | None,
    start: str,
    end: str,
) -> dict:
    """Convert cached DBN files and run the contract-level data gate."""
    try:
        import databento as db
    except ImportError as exc:
        raise RuntimeError(
            "install the optional futures dependency: pip install -e '.[futures]'"
        ) from exc
    files = {schema: raw_dir / f"{schema}.dbn.zst" for schema in SCHEMAS}
    missing = [str(path) for path in files.values() if not path.exists()]
    if missing:
        raise FileNotFoundError(f"missing raw Databento files: {missing}")
    frames = {
        schema: db.DBNStore.from_file(path).to_df().reset_index()
        for schema, path in files.items()
    }
    notices = pd.read_csv(notices_path) if notices_path else None
    daily_frames = []
    metadata_frames = []
    history_frames = []
    definitions = frames["definition"]
    for root in roots:
        root_definitions = definitions.loc[
            definitions["asset"].astype(str).eq(root)
        ].copy()
        daily, metadata, history = normalize_root_frames(
            root,
            root_definitions,
            frames["ohlcv-1d"],
            frames["statistics"],
            notices,
        )
        if not daily.empty:
            daily_frames.append(daily)
        if not metadata.empty:
            metadata_frames.append(metadata)
        if not history.empty:
            history_frames.append(history)
    daily = pd.concat(daily_frames, ignore_index=True) if daily_frames else pd.DataFrame()
    metadata = (
        pd.concat(metadata_frames, ignore_index=True) if metadata_frames else pd.DataFrame()
    )
    history = (
        pd.concat(history_frames, ignore_index=True) if history_frames else pd.DataFrame()
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    daily_path = output_dir / "contracts_daily.parquet"
    metadata_path = output_dir / "contracts_metadata.csv"
    history_path = output_dir / "contracts_metadata_history.parquet"
    daily.to_parquet(daily_path, index=False)
    metadata.to_csv(metadata_path, index=False)
    history.to_parquet(history_path, index=False)
    gate, root_coverage = audit_tables(
        daily,
        metadata,
        start=pd.Timestamp(start),
        end=pd.Timestamp(end) - pd.Timedelta(days=1),
    )
    gate.update(
        source="Databento GLBX.MDP3",
        source_native_start=start,
        historical_end_exclusive=end,
        notice_calendar_supplied=notices_path is not None,
        contracts_sha256=sha256(daily_path),
        metadata_sha256=sha256(metadata_path),
        metadata_history_sha256=sha256(history_path),
        orders_allowed=False,
    )
    root_coverage.to_csv(output_dir / "root_coverage.csv", index=False)
    (output_dir / "DATA_GATE.json").write_text(
        json.dumps(gate, indent=2, default=str) + "\n"
    )
    return gate


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["estimate", "download", "normalize"])
    parser.add_argument("--roots", nargs="+", default=list(ROOT_SLEEVES))
    parser.add_argument("--start", default="2010-06-07")
    parser.add_argument("--end", default="2025-01-01")
    parser.add_argument(
        "--estimate-output",
        type=Path,
        default=Path("data/futures/COST_ESTIMATE.json"),
    )
    parser.add_argument("--raw-dir", type=Path, default=Path("data/futures/raw_databento"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/futures"))
    parser.add_argument("--notice-calendar", type=Path)
    parser.add_argument("--approved-cost-usd", type=float, default=0.0)
    arguments = parser.parse_args()
    unknown_roots = sorted(set(arguments.roots) - set(ROOT_SLEEVES))
    if unknown_roots:
        raise ValueError(f"roots outside frozen universe: {unknown_roots}")
    if arguments.mode == "estimate":
        result = estimate(
            arguments.roots,
            arguments.start,
            arguments.end,
            arguments.estimate_output,
        )
    elif arguments.mode == "download":
        result = download(
            arguments.roots,
            arguments.start,
            arguments.end,
            arguments.raw_dir,
            arguments.approved_cost_usd,
        )
    else:
        result = normalize_download(
            arguments.raw_dir,
            arguments.output_dir,
            arguments.roots,
            arguments.notice_calendar,
            arguments.start,
            arguments.end,
        )
    print(json.dumps(result, indent=2))
