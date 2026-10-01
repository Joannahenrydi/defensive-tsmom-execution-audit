import json

from scripts.audit_v30_v32_readiness import (
    fundamental_readiness,
    futures_readiness,
    integration_readiness,
)


def test_missing_futures_core_blocks_alpha(tmp_path) -> None:
    result = futures_readiness(tmp_path)
    assert result["status"] == "V30_BLOCKED_FUTURES_DATA"
    assert not result["alpha_diagnostics_allowed"]
    assert not result["portfolio_evaluation_allowed"]


def test_core_without_cost_and_margin_allows_only_diagnostics(tmp_path) -> None:
    for name in (
        "contracts_daily.parquet",
        "contracts_metadata.csv",
        "contracts_metadata_history.parquet",
    ):
        (tmp_path / name).touch()
    result = futures_readiness(tmp_path)
    assert result["status"] == "V30_ALPHA_DIAGNOSTICS_ONLY_COST_DATA_BLOCKED"
    assert result["alpha_diagnostics_allowed"]
    assert not result["portfolio_evaluation_allowed"]


def test_latest_restatement_gate_does_not_admit_v31(tmp_path) -> None:
    gate = tmp_path / "gate.json"
    gate.write_text(json.dumps({"status": "V29_BLOCKED_SEC_DATA_QUALITY"}))
    result = fundamental_readiness(gate, tmp_path / "fallback.json", tmp_path / "events.csv")
    assert result["status"] == "V31_BLOCKED_PIT_DATA"
    assert not result["alpha_evaluation_allowed"]


def test_v32_requires_both_historical_admissions() -> None:
    v30 = {"status": "V30_HISTORICAL_GATE_PASS_PROSPECTIVE_REQUIRED"}
    v31 = {"status": "V31_BLOCKED_PIT_DATA"}
    result = integration_readiness(v30, v31)
    assert result["status"] == "V32_NOT_RUN_COMPONENT_BLOCKED"
    assert not result["integration_evaluation_allowed"]
