"""Write a reviewable report for the Valuein v31 point-in-time data gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def build_report(processed: Path, download_manifest: Path, output: Path) -> dict:
    gate = json.loads((processed / "DATA_GATE.json").read_text())
    events = pd.read_parquet(processed / "fundamental_events.parquet")
    membership = pd.read_parquet(processed / "sp500_membership_daily.parquet")
    download = json.loads(download_manifest.read_text())

    event_year = events.assign(year=events["availability_date"].dt.year).groupby("year").agg(
        events=("accession_id", "size"),
        entities=("entity_id", "nunique"),
        amendments=("restatement_flag", "sum"),
    )
    member_daily = membership.groupby("date")["cik"].nunique()
    member_year = member_daily.rename("members").reset_index().assign(
        year=lambda frame: frame["date"].dt.year
    ).groupby("year").agg(
        membership_sessions=("members", "size"),
        minimum_members=("members", "min"),
        median_members=("members", "median"),
        maximum_members=("members", "max"),
    )
    coverage = member_year.join(event_year, how="outer").reset_index()
    component_rows = [
        {"gate": name, "passed": bool(passed)}
        for name, passed in gate["components"].items()
    ]

    output.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(output / "coverage_by_year.csv", index=False)
    pd.DataFrame(component_rows).to_csv(output / "gate_components.csv", index=False)
    (output / "DATA_GATE.json").write_text(json.dumps(gate, indent=2) + "\n")
    summary = {
        "status": gate["status"],
        "decision": "ALPHA_NOT_RUN",
        "reason": (
            "The public Valuein sample begins in 2021. Only two entities have three "
            "annual as-filed events inside the frozen 2018-2022 train window, versus "
            "the required 200."
        ),
        "snapshot": gate["snapshot"],
        "plan": download["plan"],
        "events": len(events),
        "membership_rows": len(membership),
        "orders_allowed": False,
    }
    (output / "SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n")
    (output / "v31_decision.json").write_text(json.dumps(summary, indent=2) + "\n")
    pd.DataFrame(columns=[
        "family",
        "train_rank_ic",
        "train_icir",
        "train_slope",
        "admitted",
    ]).to_csv(output / "v31_family_metrics.csv", index=False)
    pd.DataFrame(columns=[
        "portfolio",
        "segment",
        "net_sharpe",
        "cagr",
        "max_drawdown",
        "status",
    ]).to_csv(output / "v31_portfolio_metrics.csv", index=False)

    checks = "\n".join(
        f"| {name.replace('_', ' ')} | {'PASS' if passed else 'FAIL'} |"
        for name, passed in gate["components"].items()
    )
    report = f"""# v31 Valuein Point-in-Time Data Gate

## Decision

**{gate['status']} — alpha and portfolio evaluation were not run.**

The public Valuein `{download['plan']}` snapshot `{gate['snapshot']}` was downloaded and normalized
successfully. The pipeline used `value_as_filed`, the later of filing/fact `accepted_at`, a one
business-day availability delay, amendments as separate events, SCD ticker validity, and historical
S&P 500 effective/removal dates.

| Frozen component | Result |
|---|---|
{checks}

## Coverage

- Normalized annual events: **{len(events):,}**
- First availability date: **{gate['first_event'][:10]}**
- Last availability date: **{gate['last_event'][:10]}**
- Train events: **{gate['train_events']:,}**
- Entities with at least one train event: **{gate['entities_with_one_train_event']:,}**
- Entities with three train events: **{gate['entities_with_three_train_events']:,} / 200 required**
- Train membership sessions with at least 400 names: **{gate['train_sessions_with_400_members']:,}**
- Sectors with at least ten covered entities: **{gate['sectors_with_ten_covered_entities']}**
- Amendments preserved as separate events: **{int(events['restatement_flag'].sum())}**

The public sample starts in 2021, so it cannot support the frozen 2018–2022 training requirement.
This is a history-depth block, not evidence against quality or conservative-growth alpha. A
Valuein plan with full historical coverage can rerun the identical normalizer and gate without
changing the research rules.

## Research disposition

- v30 remains blocked on expiry-specific futures, first-notice, cost and margin data.
- v31 fundamental IC, standalone portfolio and integration were not run.
- v32 remains stopped because its independently admitted components do not exist.
- Orders remain disabled.
"""
    (output / "REPORT.md").write_text(report)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--processed", type=Path, default=Path("data/processed/valuein_v31")
    )
    parser.add_argument("--download-manifest", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path, default=Path("reports/valuein_v31_data_gate")
    )
    arguments = parser.parse_args()
    print(json.dumps(build_report(
        arguments.processed,
        arguments.download_manifest,
        arguments.output,
    ), indent=2))
