"""Fail-closed readiness audit for the frozen v30, v31 and v32 studies."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.evaluate_equity_v7 import sha256

V30_PROTOCOL = Path("docs/MULTI_ASSET_PROTOCOL_V30.md")
V31_PROTOCOL = Path("docs/EQUITY_RESEARCH_PROTOCOL_V31.md")
V32_PROTOCOL = Path("docs/MULTI_ASSET_PROTOCOL_V32.md")


def futures_readiness(data_dir: Path) -> dict:
    core = [
        data_dir / "contracts_daily.parquet",
        data_dir / "contracts_metadata.csv",
        data_dir / "contracts_metadata_history.parquet",
    ]
    operational = [
        data_dir / "root_cost_schedule.csv",
        data_dir / "margins_daily.parquet",
    ]
    missing_core = [str(path) for path in core if not path.exists()]
    missing_operational = [str(path) for path in operational if not path.exists()]
    if missing_core:
        status = "V30_BLOCKED_FUTURES_DATA"
        alpha_diagnostics_allowed = False
    elif missing_operational:
        status = "V30_ALPHA_DIAGNOSTICS_ONLY_COST_DATA_BLOCKED"
        alpha_diagnostics_allowed = True
    else:
        status = "V30_INPUTS_PRESENT_QUALITY_GATE_REQUIRED"
        alpha_diagnostics_allowed = True
    return {
        "status": status,
        "missing_core_files": missing_core,
        "missing_operational_files": missing_operational,
        "alpha_diagnostics_allowed": alpha_diagnostics_allowed,
        "portfolio_evaluation_allowed": not missing_core and not missing_operational,
        "protocol_sha256": sha256(V30_PROTOCOL),
        "orders_allowed": False,
    }


def fundamental_readiness(
    preferred_gate: Path,
    fallback_gate: Path,
    preferred_events: Path,
) -> dict:
    gate_path = preferred_gate if preferred_gate.exists() else fallback_gate
    if not gate_path.exists():
        return {
            "status": "V31_BLOCKED_PIT_DATA",
            "reason": "NO_POINT_IN_TIME_DATA_GATE",
            "protocol_sha256": sha256(V31_PROTOCOL),
            "orders_allowed": False,
        }
    gate = json.loads(gate_path.read_text())
    admitted = gate.get("status") in {
        "V29_DATA_ADMITTED_ALPHA_NOT_RUN",
        "V31_VALUEIN_DATA_ADMITTED_ALPHA_NOT_RUN",
    }
    events_present = preferred_events.exists()
    if not admitted or not events_present:
        status = "V31_BLOCKED_PIT_DATA"
    else:
        status = "V31_INPUTS_PRESENT_ALPHA_GATE_REQUIRED"
    return {
        "status": status,
        "source_gate": str(gate_path),
        "source_status": gate.get("status"),
        "events_present": events_present,
        "alpha_evaluation_allowed": bool(admitted and events_present),
        "protocol_sha256": sha256(V31_PROTOCOL),
        "orders_allowed": False,
    }


def integration_readiness(v30: dict, v31: dict) -> dict:
    ready = (
        v30["status"] == "V30_HISTORICAL_GATE_PASS_PROSPECTIVE_REQUIRED"
        and v31["status"] == "V31_HISTORICAL_GATE_PASS_PROSPECTIVE_REQUIRED"
    )
    return {
        "status": (
            "V32_INPUTS_ADMITTED_INTEGRATION_GATE_REQUIRED"
            if ready
            else "V32_NOT_RUN_COMPONENT_BLOCKED"
        ),
        "v30_status": v30["status"],
        "v31_status": v31["status"],
        "integration_evaluation_allowed": ready,
        "protocol_sha256": sha256(V32_PROTOCOL),
        "orders_allowed": False,
    }


def write_report(output: Path, v30: dict, v31: dict, v32: dict) -> None:
    report = f"""# v30–v32 Research Readiness

## Current decision

- **v30 Futures Trend + Carry:** `{v30['status']}`
- **v31 Trend + PIT Fundamentals:** `{v31['status']}`
- **v32 Integrated Multi-Source Portfolio:** `{v32['status']}`

No alpha or portfolio result was generated. The current workspace does not contain an admitted
expiry-specific futures archive or an admitted as-reported fundamental event file. This is a data
availability decision, not an alpha rejection.

## v30

Missing core files:
{chr(10).join(f'- `{item}`' for item in v30.get('missing_core_files', [])) or '- None'}

Missing operational files:
{chr(10).join(f'- `{item}`' for item in v30.get('missing_operational_files', [])) or '- None'}

Contract-level alpha diagnostics require the core files and the v30 quality gate. Portfolio
admission additionally requires costs and margin. Continuous futures or ETF prices cannot replace
these inputs.

## v31

- Source gate: `{v31.get('source_gate', 'not found')}`
- Source status: `{v31.get('source_status', 'not evaluated')}`
- As-reported event file present: `{v31.get('events_present', False)}`

Latest-restatement fundamentals remain inadmissible. Only SEC accession/filed facts or a licensed
as-reported vintage such as SF1 `ARY` can unblock the alpha gate.

## v32

v32 remains stopped until every included v30 and v31 component independently passes its frozen
family and standalone portfolio gates. It will not fill a missing component with a price proxy or
retune sleeve weights on reused history. Orders remain disabled.
"""
    (output / "REPORT.md").write_text(report)


def run(
    futures_dir: Path,
    preferred_fundamental_gate: Path,
    fallback_fundamental_gate: Path,
    fundamental_events: Path,
    output: Path,
) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    v30 = futures_readiness(futures_dir)
    v31 = fundamental_readiness(
        preferred_fundamental_gate,
        fallback_fundamental_gate,
        fundamental_events,
    )
    v32 = integration_readiness(v30, v31)
    result = {"v30": v30, "v31": v31, "v32": v32, "orders_allowed": False}
    (output / "SUMMARY.json").write_text(json.dumps(result, indent=2) + "\n")
    (output / "v30_data_gate.json").write_text(json.dumps(v30, indent=2) + "\n")
    (output / "v30_decision.json").write_text(json.dumps(v30, indent=2) + "\n")
    (output / "v31_decision.json").write_text(json.dumps(v31, indent=2) + "\n")
    (output / "v32_decision.json").write_text(json.dumps(v32, indent=2) + "\n")
    write_report(output, v30, v31, v32)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--futures-dir", type=Path, default=Path("data/futures"))
    parser.add_argument(
        "--fundamental-gate",
        type=Path,
        default=Path("data/processed/valuein_v31/DATA_GATE.json"),
    )
    parser.add_argument(
        "--fallback-fundamental-gate",
        type=Path,
        default=Path("reports/equity_v29_data_gate/DATA_GATE.json"),
    )
    parser.add_argument(
        "--fundamental-events",
        type=Path,
        default=Path("data/processed/valuein_v31/fundamental_events.parquet"),
    )
    parser.add_argument(
        "--output", type=Path, default=Path("reports/multisource_v30_v32_readiness")
    )
    arguments = parser.parse_args()
    print(json.dumps(run(
        arguments.futures_dir,
        arguments.fundamental_gate,
        arguments.fallback_fundamental_gate,
        arguments.fundamental_events,
        arguments.output,
    ), indent=2))
