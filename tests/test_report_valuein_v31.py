import json

import pandas as pd

from scripts.report_valuein_v31 import build_report


def test_report_preserves_blocked_data_decision(tmp_path) -> None:
    processed = tmp_path / "processed"
    processed.mkdir()
    gate = {
        "status": "V31_BLOCKED_PIT_DATA",
        "components": {
            "membership_session_coverage": True,
            "one_train_event": True,
            "three_train_events": False,
            "sector_depth": True,
            "unique_entity_availability": True,
        },
        "snapshot": "snapshot_test",
        "first_event": "2021-01-01 00:00:00",
        "last_event": "2022-01-01 00:00:00",
        "train_events": 1,
        "entities_with_one_train_event": 1,
        "entities_with_three_train_events": 0,
        "train_sessions_with_400_members": 1,
        "sectors_with_ten_covered_entities": 1,
    }
    (processed / "DATA_GATE.json").write_text(json.dumps(gate))
    pd.DataFrame(
        {
            "availability_date": pd.to_datetime(["2021-01-01"]),
            "accession_id": ["A1"],
            "entity_id": [1],
            "restatement_flag": [False],
        }
    ).to_parquet(processed / "fundamental_events.parquet")
    pd.DataFrame(
        {
            "date": pd.to_datetime(["2021-01-04"]),
            "cik": ["1"],
        }
    ).to_parquet(processed / "sp500_membership_daily.parquet")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"plan": "sample"}))
    output = tmp_path / "report"
    summary = build_report(processed, manifest, output)
    assert summary["status"] == "V31_BLOCKED_PIT_DATA"
    assert summary["decision"] == "ALPHA_NOT_RUN"
    assert "three train events | FAIL" in (output / "REPORT.md").read_text()
    assert pd.read_csv(output / "v31_family_metrics.csv").empty
