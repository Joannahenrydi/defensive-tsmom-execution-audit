import json

import pandas as pd

from scripts.audit_futures_v23_data import audit_tables, main


def test_missing_contract_archive_blocks_without_running_strategy(tmp_path):
    output = tmp_path / "report"
    main(tmp_path / "missing.parquet", tmp_path / "missing.csv", output)
    summary = json.loads((output / "SUMMARY.json").read_text())
    assert summary["status"] == "V23_BLOCKED_DATA_UNAVAILABLE"
    assert not summary["strategy_backtest_run"]
    assert not summary["orders_allowed"]


def test_missing_required_columns_fail_data_quality_gate():
    summary, roots = audit_tables(pd.DataFrame({"date": []}), pd.DataFrame({"root": []}))
    assert summary["status"] == "V23_BLOCKED_DATA_QUALITY"
    assert any("daily file missing columns" in item for item in summary["problems"])
    assert roots.empty


def test_continuous_like_archive_without_contract_depth_is_not_admitted():
    dates = pd.bdate_range("2008-01-02", "2024-12-31")
    daily = pd.DataFrame({
        "date": dates,
        "root": "ES",
        "contract": "ES_CONTINUOUS",
        "settlement": 100.0,
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "volume": 1000.0,
        "open_interest": 1000.0,
    })
    metadata = pd.DataFrame({
        "root": ["ES"],
        "contract": ["ES_CONTINUOUS"],
        "sleeve": ["equity"],
        "exchange": ["CME"],
        "currency": ["USD"],
        "multiplier": [50.0],
        "tick_size": [0.25],
        "expiry_date": ["2025-01-01"],
        "first_notice_date": [None],
        "last_trade_date": ["2025-01-01"],
        "cash_settled": [True],
    })
    summary, roots = audit_tables(daily, metadata)
    assert summary["status"] == "V23_BLOCKED_DATA_QUALITY"
    assert roots.loc[roots.root.eq("ES"), "two_expiry_session_share"].iloc[0] == 0
    assert "ES" not in summary["admitted_roots"]
