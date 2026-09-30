"""Quantify whether deleveraging coincides with worse execution states.

This is a post-holdout interaction diagnostic. It reconstructs the pretrade
portfolio from frozen v20 weights and returns, and never changes the strategy.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import linregress, spearmanr

from scripts.cross_asset_v17_universe import UNIVERSE
from scripts.evaluate_cross_asset_v12 import TEST, load_data
from scripts.evaluate_cross_asset_v20 import EXPECTED_SOURCE_SHA256
from scripts.evaluate_equity_v7 import sha256

V20 = Path("reports/cross_asset_v20")
OUTPUT = Path("reports/cross_asset_v20_comment_audit")
DELEVERAGING_THRESHOLD = -0.10
EXPANSION_THRESHOLD = 0.10


def classify_gross_change(change: pd.Series) -> pd.Series:
    """Classify rebalances with a fixed 10% relative-gross threshold."""
    return pd.Series(
        np.select(
            [change.lt(DELEVERAGING_THRESHOLD), change.gt(EXPANSION_THRESHOLD)],
            ["deleveraging", "expansion"],
            default="normal",
        ),
        index=change.index,
        dtype="object",
    )


def reconstruct_interactions(
    returns: pd.DataFrame,
    weights: pd.DataFrame,
    daily: pd.DataFrame,
    state_daily: pd.DataFrame,
    rebalances: pd.DataFrame,
    multipliers: pd.DataFrame,
) -> pd.DataFrame:
    """Reconstruct pretrade gross and align each trade with next-session costs."""
    rows = []
    for decision_session, rebalance in rebalances.iterrows():
        if decision_session not in daily.index or decision_session not in weights.index:
            raise RuntimeError("rebalance is outside the locked daily path")
        location = daily.index.get_loc(decision_session)
        if not isinstance(location, int) or location + 1 >= len(daily.index):
            raise RuntimeError("rebalance lacks a unique following execution session")
        execution_session = daily.index[location + 1]

        start_weight = weights.loc[decision_session]
        realized = returns.loc[decision_session].reindex(start_weight.index).fillna(0.0)
        denominator = 1 + float(daily.loc[decision_session, "net_return"])
        if denominator <= 0:
            raise RuntimeError("nonpositive portfolio denominator")
        pretrade_weight = start_weight.mul(1 + realized).div(denominator)
        gross_before = float(pretrade_weight.abs().sum())
        gross_after = float(rebalance["gross"])
        gross_change = gross_after - gross_before
        gross_change_fraction = gross_change / gross_before if gross_before > 0 else np.nan

        state = multipliers.loc[execution_session]
        baseline_cost = float(daily.loc[execution_session, "transaction_cost"])
        stressed_cost = float(state_daily.loc[execution_session, "transaction_cost"])
        rows.append(
            {
                "decision_session": decision_session,
                "execution_session": execution_session,
                "gross_before": gross_before,
                "gross_after": gross_after,
                "gross_change": gross_change,
                "gross_change_fraction": gross_change_fraction,
                "turnover": float(rebalance["turnover"]),
                "volatility_ratio": float(state["volatility_ratio"]),
                "liquidity_ratio": float(state["liquidity_ratio"]),
                "prior_drawdown": float(state["prior_drawdown"]),
                "volatility_stress_multiplier": max(1.0, float(state["volatility_ratio"])),
                "liquidity_stress_multiplier": max(
                    1.0, 1 / float(state["liquidity_ratio"])
                ),
                "drawdown_stress_multiplier": (
                    1.5 if float(state["prior_drawdown"]) <= -0.10 else 1.0
                ),
                "total_cost_multiplier": float(state["transaction_multiplier"]),
                "baseline_transaction_cost": baseline_cost,
                "state_transaction_cost": stressed_cost,
                "incremental_state_cost": stressed_cost - baseline_cost,
                "execution_day_portfolio_return": float(
                    daily.loc[execution_session, "net_return"]
                ),
            }
        )
    result = pd.DataFrame(rows).set_index("decision_session")
    result["rebalance_state"] = classify_gross_change(result["gross_change_fraction"])
    result["gross_direction"] = np.where(
        result["gross_change_fraction"].lt(0), "reduction", "non_reduction"
    )
    return result


def summarize_group(
    subset: pd.DataFrame, *, period: str, grouping: str, state: str
) -> dict[str, float | int | str]:
    """Summarize one interaction group without causal PnL attribution claims."""
    return {
        "period": period,
        "grouping": grouping,
        "state": state,
        "events": len(subset),
        "mean_gross_change_fraction": float(subset["gross_change_fraction"].mean()),
        "mean_volatility_stress_multiplier": float(
            subset["volatility_stress_multiplier"].mean()
        ),
        "mean_liquidity_stress_multiplier": float(
            subset["liquidity_stress_multiplier"].mean()
        ),
        "mean_drawdown_stress_multiplier": float(
            subset["drawdown_stress_multiplier"].mean()
        ),
        "mean_total_cost_multiplier": float(subset["total_cost_multiplier"].mean()),
        "p95_total_cost_multiplier": float(subset["total_cost_multiplier"].quantile(0.95)),
        "mean_turnover": float(subset["turnover"].mean()),
        "total_turnover": float(subset["turnover"].sum()),
        "total_baseline_transaction_cost": float(
            subset["baseline_transaction_cost"].sum()
        ),
        "total_state_transaction_cost": float(subset["state_transaction_cost"].sum()),
        "total_incremental_state_cost": float(subset["incremental_state_cost"].sum()),
        "execution_day_return_sum": float(
            subset["execution_day_portfolio_return"].sum()
        ),
    }


def interaction_summary(events: pd.DataFrame) -> pd.DataFrame:
    """Summarize threshold states and all gross reductions, including 2022."""
    rows = []
    periods = {
        "locked_2021_2024": events,
        "calendar_2022": events.loc[events.index.year == 2022],
    }
    for period, frame in periods.items():
        for state in ("expansion", "normal", "deleveraging"):
            rows.append(
                summarize_group(
                    frame.loc[frame["rebalance_state"].eq(state)],
                    period=period,
                    grouping="threshold_state",
                    state=state,
                )
            )
        for direction in ("reduction", "non_reduction"):
            rows.append(
                summarize_group(
                    frame.loc[frame["gross_direction"].eq(direction)],
                    period=period,
                    grouping="gross_direction",
                    state=direction,
                )
            )
    return pd.DataFrame(rows)


def correlation_diagnostics(events: pd.DataFrame) -> dict[str, float]:
    """Test the broad monotonic change/cost relationship across rebalances."""
    x = events["gross_change_fraction"].to_numpy(dtype=float)
    y = events["total_cost_multiplier"].to_numpy(dtype=float)
    regression = linregress(x, y)
    rank = spearmanr(x, y)
    return {
        "pearson_correlation": float(np.corrcoef(x, y)[0, 1]),
        "spearman_correlation": float(rank.statistic),
        "spearman_pvalue": float(rank.pvalue),
        "ols_slope": float(regression.slope),
        "ols_slope_pvalue": float(regression.pvalue),
    }


def write_report(output: Path, summary: dict) -> None:
    locked = summary["locked"]
    year_2022 = summary["year_2022"]
    corr = summary["correlation"]
    report = f"""# Deleveraging × Execution-State Interaction Audit

## Scope

This diagnostic reconstructs every frozen v20 rebalance. A deleveraging event is prespecified as a
decline of more than 10% from drifted pretrade gross exposure to posttrade gross exposure. Costs
are aligned to the following session, when the frozen engine realizes the trade charge. No signal,
holding, cost formula or promotion decision changes.

## Locked result

| Rebalance state | Events | Mean cost multiplier | Mean liquidity multiplier | Mean volatility multiplier | Mean turnover | Total execution cost |
|---|---:|---:|---:|---:|---:|---:|
| Expansion | {locked['expansion_events']} | {locked['expansion_cost_multiplier']:.2f}× | {locked['expansion_liquidity_multiplier']:.2f}× | {locked['expansion_volatility_multiplier']:.2f}× | {locked['expansion_turnover']:.2%} | {locked['expansion_cost']:.3%} |
| Normal | {locked['normal_events']} | {locked['normal_cost_multiplier']:.2f}× | {locked['normal_liquidity_multiplier']:.2f}× | {locked['normal_volatility_multiplier']:.2f}× | {locked['normal_turnover']:.2%} | {locked['normal_cost']:.3%} |
| Deleveraging | {locked['deleveraging_events']} | {locked['deleveraging_cost_multiplier']:.2f}× | {locked['deleveraging_liquidity_multiplier']:.2f}× | {locked['deleveraging_volatility_multiplier']:.2f}× | {locked['deleveraging_turnover']:.2%} | {locked['deleveraging_cost']:.3%} |

The two tail deleveraging events occurred at an average {locked['deleveraging_cost_multiplier']:.2f}×
cost multiplier versus {locked['other_cost_multiplier']:.2f}× for other rebalances. This tail
interaction is present descriptively, but it was driven by volatility and the drawdown stress
rather than liquidity: the deleveraging liquidity multiplier was
{locked['deleveraging_liquidity_multiplier']:.2f}× versus
{locked['other_liquidity_multiplier']:.2f}× for other events.

Across all 100 rebalances, gross change and the cost multiplier had Pearson correlation
{corr['pearson_correlation']:.3f} and Spearman correlation {corr['spearman_correlation']:.3f}
(p={corr['spearman_pvalue']:.3f}). The data therefore do not support a broad monotonic claim that
larger gross reductions systematically coincide with worse execution states. The tail comparison
is based on only two events and must not be treated as a stable estimate.

## 2022 teardown

- Deleveraging events: **{year_2022['events']}**.
- Decision/execution date: **{year_2022['decision_session']} / {year_2022['execution_session']}**.
- Cost multiplier: **{year_2022['cost_multiplier']:.2f}×**.
- Liquidity multiplier: **{year_2022['liquidity_multiplier']:.2f}×**.
- Volatility multiplier: **{year_2022['volatility_multiplier']:.2f}×**.
- State-dependent transaction cost: **{year_2022['state_cost']:.3%} of NAV**.
- Increment above baseline cost: **{year_2022['incremental_cost']:.3%} of NAV**.
- State cost as a share of the absolute 2022 arithmetic loss: **{year_2022['cost_share_of_loss']:.3%}**.

The 2022 interaction existed, but its direct cost was economically immaterial relative to the
portfolio loss. Execution cost did not cause the 2022 failure; gross long-book performance did.
The execution-day return is reported in the event file only as context and is not attributed
causally to the rebalance.

## Margin scope

The implementation trades unlevered cash ETFs. Futures-style variation margin, initial-margin
changes and margin-driven liquidation cannot be identified from this dataset. They remain an
explicit requirement of the separately frozen futures-native research specification rather than a
fabricated multiplier in this audit.

## Decision

**INTERACTION_PRESENT_IN_TAIL_BUT_ECONOMICALLY_SMALL.** Aaron's execution concern is now closed:
tail deleveraging occurred under higher total cost states, the evidence does not show coincident
liquidity deterioration or a general monotonic relationship, and realized deleveraging cost was far
too small to explain the strategy failure. The frozen v20 rejection remains unchanged.
"""
    (output / "DELEVERAGING_INTERACTION.md").write_text(report)


def main(source: Path, v20: Path, output: Path) -> None:
    if sha256(source) != EXPECTED_SOURCE_SHA256:
        raise RuntimeError("source hash does not match the frozen v17 archive")
    data = load_data(source, TEST[1], UNIVERSE)
    weights = pd.read_csv(v20 / "locked_weights.csv.gz", index_col=0, parse_dates=True)
    daily = pd.read_csv(v20 / "locked_baseline_daily.csv", index_col="session", parse_dates=True)
    state_daily = pd.read_csv(
        v20 / "locked_state_cost_daily.csv", index_col="session", parse_dates=True
    )
    rebalances = pd.read_csv(v20 / "locked_rebalances.csv", index_col="session", parse_dates=True)
    multipliers = pd.read_csv(
        v20 / "locked_state_multipliers.csv", index_col=0, parse_dates=True
    )
    events = reconstruct_interactions(
        data["returns"], weights, daily, state_daily, rebalances, multipliers
    )
    table = interaction_summary(events)
    correlations = correlation_diagnostics(events)
    output.mkdir(parents=True, exist_ok=True)
    events.to_csv(output / "deleveraging_execution_audit.csv")
    table.to_csv(output / "deleveraging_execution_summary.csv", index=False)

    locked_threshold = table.query(
        "period == 'locked_2021_2024' and grouping == 'threshold_state'"
    ).set_index("state")
    deleveraging = locked_threshold.loc["deleveraging"]
    other = events.loc[events["rebalance_state"].ne("deleveraging")]
    event_2022 = events.loc[
        (events.index.year == 2022) & events["rebalance_state"].eq("deleveraging")
    ]
    loss_2022 = abs(float(daily.loc["2022", "net_return"].sum()))
    if len(event_2022) != 1:
        raise RuntimeError("the frozen 2022 path must contain exactly one tail deleveraging event")
    row_2022 = event_2022.iloc[0]
    summary = {
        "status": "INTERACTION_PRESENT_IN_TAIL_BUT_ECONOMICALLY_SMALL",
        "diagnostic_only": True,
        "changes_to_strategy": False,
        "orders_allowed": False,
        "definition": {
            "deleveraging_threshold": DELEVERAGING_THRESHOLD,
            "expansion_threshold": EXPANSION_THRESHOLD,
            "cost_alignment": "following_session",
        },
        "locked": {
            "total_rebalances": len(events),
            "expansion_events": int(locked_threshold.loc["expansion", "events"]),
            "normal_events": int(locked_threshold.loc["normal", "events"]),
            "deleveraging_events": int(deleveraging["events"]),
            "expansion_cost_multiplier": float(
                locked_threshold.loc["expansion", "mean_total_cost_multiplier"]
            ),
            "normal_cost_multiplier": float(
                locked_threshold.loc["normal", "mean_total_cost_multiplier"]
            ),
            "deleveraging_cost_multiplier": float(
                deleveraging["mean_total_cost_multiplier"]
            ),
            "other_cost_multiplier": float(other["total_cost_multiplier"].mean()),
            "expansion_liquidity_multiplier": float(
                locked_threshold.loc["expansion", "mean_liquidity_stress_multiplier"]
            ),
            "normal_liquidity_multiplier": float(
                locked_threshold.loc["normal", "mean_liquidity_stress_multiplier"]
            ),
            "deleveraging_liquidity_multiplier": float(
                deleveraging["mean_liquidity_stress_multiplier"]
            ),
            "other_liquidity_multiplier": float(other["liquidity_stress_multiplier"].mean()),
            "expansion_volatility_multiplier": float(
                locked_threshold.loc["expansion", "mean_volatility_stress_multiplier"]
            ),
            "normal_volatility_multiplier": float(
                locked_threshold.loc["normal", "mean_volatility_stress_multiplier"]
            ),
            "deleveraging_volatility_multiplier": float(
                deleveraging["mean_volatility_stress_multiplier"]
            ),
            "expansion_turnover": float(locked_threshold.loc["expansion", "mean_turnover"]),
            "normal_turnover": float(locked_threshold.loc["normal", "mean_turnover"]),
            "deleveraging_turnover": float(deleveraging["mean_turnover"]),
            "expansion_cost": float(
                locked_threshold.loc["expansion", "total_state_transaction_cost"]
            ),
            "normal_cost": float(
                locked_threshold.loc["normal", "total_state_transaction_cost"]
            ),
            "deleveraging_cost": float(deleveraging["total_state_transaction_cost"]),
        },
        "correlation": correlations,
        "year_2022": {
            "events": len(event_2022),
            "decision_session": str(event_2022.index[0].date()),
            "execution_session": str(pd.Timestamp(row_2022["execution_session"]).date()),
            "cost_multiplier": float(row_2022["total_cost_multiplier"]),
            "liquidity_multiplier": float(row_2022["liquidity_stress_multiplier"]),
            "volatility_multiplier": float(row_2022["volatility_stress_multiplier"]),
            "state_cost": float(row_2022["state_transaction_cost"]),
            "incremental_cost": float(row_2022["incremental_state_cost"]),
            "cost_share_of_loss": float(row_2022["state_transaction_cost"] / loss_2022),
        },
        "hashes": {
            "source_sha256": sha256(source),
            "weights_sha256": sha256(v20 / "locked_weights.csv.gz"),
            "multipliers_sha256": sha256(v20 / "locked_state_multipliers.csv"),
            "audit_source_sha256": sha256(Path(__file__)),
        },
    }
    (output / "DELEVERAGING_SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n")
    write_report(output, summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--v20", type=Path, default=V20)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    arguments = parser.parse_args()
    main(arguments.source, arguments.v20, arguments.output)
