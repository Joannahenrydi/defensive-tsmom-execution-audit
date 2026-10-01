"""Evaluate the frozen v27 multi-source alpha research program."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from backtest.cross_asset import CrossAssetResult
from backtest.cross_asset_budget import RiskBudgetConfig, run_risk_budget_backtest
from scripts.audit_futures_v23_data import audit_tables, read_table
from scripts.cross_asset_v17_universe import UNIVERSE
from scripts.evaluate_cross_asset_v12 import TRAIN, load_data
from scripts.evaluate_cross_asset_v13 import segment_metrics
from scripts.evaluate_cross_asset_v15 import calibrate_absolute
from scripts.evaluate_cross_asset_v19 import (
    COSTS,
    FACTOR_CAPS,
    frozen_trade_cost_stress,
    normalized_loadings,
)
from scripts.evaluate_cross_asset_v20 import (
    build_state_cost_multipliers,
    reprice_state_dependent_costs,
)
from scripts.evaluate_cross_asset_v24 import (
    build_dynamic_symmetric_tsmom,
    diagnostic_tables,
    operational_pass,
    segment_diagnostics,
)
from scripts.evaluate_cross_asset_v26 import (
    DEVELOPMENT,
    RISK_GROUPS,
    actual_group_risk_contributions,
    build_group_risk_budgets,
    group_contribution_table,
    risk_group_map,
)
from scripts.evaluate_equity_v7 import sha256

PROTOCOL = Path("docs/MULTI_ASSET_PROTOCOL_V27.md")
EXPECTED_SOURCE_SHA256 = "82347fef112a5f04dc2b5accf947f362eefe1a0a89f1c59bf143a369ab63e32e"
TREND_WEIGHT_A = 4 / 7
MEAN_REVERSION_WEIGHT_A = 3 / 7
BETA_WINDOW = 60
BETA_MINIMUM = 40
RESIDUAL_WINDOW = 20
STANDARDIZATION_WINDOW = 252
STANDARDIZATION_MINIMUM = 126
THRESHOLD_QUANTILE = 0.70


def build_leave_one_out_group_returns(
    returns: pd.DataFrame,
    eligibility: pd.DataFrame,
    groups: pd.Series,
) -> pd.DataFrame:
    """Return each asset's contemporaneous equal-weight peer-group return."""
    proxy = pd.DataFrame(np.nan, index=returns.index, columns=returns.columns)
    for group in RISK_GROUPS:
        names = groups.index[groups.eq(group)]
        observed = returns.loc[:, names].where(eligibility.loc[:, names])
        group_sum = observed.sum(axis=1, min_count=1)
        group_count = observed.notna().sum(axis=1)
        for name in names:
            own = observed[name]
            peer_count = group_count - own.notna().astype(int)
            proxy[name] = group_sum.sub(own.fillna(0.0)).div(
                peer_count.where(peer_count.ge(2))
            )
    return proxy


def build_residual_mean_reversion(
    data: dict[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    """Build the frozen causal 20-session residual mean-reversion family."""
    returns = data["returns"]
    eligibility = data["eligibility"]
    groups = risk_group_map().reindex(returns.columns)
    if groups.isna().any():
        raise ValueError("every residual-MR asset must map to a v26 risk group")
    peer_return = build_leave_one_out_group_returns(returns, eligibility, groups)
    beta = pd.DataFrame(np.nan, index=returns.index, columns=returns.columns)
    for name in returns.columns:
        covariance = returns[name].rolling(BETA_WINDOW, min_periods=BETA_MINIMUM).cov(
            peer_return[name]
        )
        variance = peer_return[name].rolling(
            BETA_WINDOW, min_periods=BETA_MINIMUM
        ).var()
        beta[name] = covariance.div(variance.where(variance.gt(0))).shift(1)
    residual_return = returns.sub(beta * peer_return)
    residual_20 = residual_return.rolling(
        RESIDUAL_WINDOW, min_periods=RESIDUAL_WINDOW
    ).sum()
    reference = residual_20.rolling(
        STANDARDIZATION_WINDOW, min_periods=STANDARDIZATION_MINIMUM
    )
    prior_mean = reference.mean().shift(1)
    prior_standard_deviation = reference.std(ddof=1).shift(1)
    residual_z = residual_20.sub(prior_mean).div(
        prior_standard_deviation.where(prior_standard_deviation.gt(0))
    ).clip(-5, 5)
    threshold = residual_z.abs().rolling(
        STANDARDIZATION_WINDOW, min_periods=STANDARDIZATION_MINIMUM
    ).quantile(THRESHOLD_QUANTILE).shift(1)
    signal = -np.tanh(residual_z).where(residual_z.abs().gt(threshold), 0.0)
    signal = signal.where(eligibility)
    trend = build_dynamic_symmetric_tsmom(data)
    sizing_score = signal.div(
        trend["effective_volatility"].where(trend["effective_volatility"].gt(0))
    )
    return {
        "peer_group_return": peer_return.where(eligibility),
        "beta": beta.where(eligibility),
        "residual_return": residual_return.where(eligibility),
        "residual_20": residual_20.where(eligibility),
        "residual_z": residual_z.where(eligibility),
        "threshold": threshold.where(eligibility),
        "signal": signal,
        "sizing_score": sizing_score.where(eligibility),
    }


def pooled_score_correlation(
    left: pd.DataFrame, right: pd.DataFrame, period: tuple[pd.Timestamp, pd.Timestamp]
) -> dict[str, float | int]:
    """Report pooled and daily cross-sectional correlation on aligned observations."""
    left = left.loc[period[0] : period[1]]
    right = right.loc[period[0] : period[1]]
    usable = np.isfinite(left.to_numpy()) & np.isfinite(right.to_numpy())
    observations = int(usable.sum())
    if observations < 2:
        return {
            "pooled_correlation": np.nan,
            "mean_daily_cross_sectional_correlation": np.nan,
            "observations": observations,
        }
    pooled = float(np.corrcoef(left.to_numpy()[usable], right.to_numpy()[usable])[0, 1])
    daily = left.corrwith(right, axis=1).replace([np.inf, -np.inf], np.nan)
    return {
        "pooled_correlation": pooled,
        "mean_daily_cross_sectional_correlation": float(daily.mean()),
        "observations": observations,
    }


def run_track_a(
    score: pd.DataFrame,
    risk_scaler: pd.Series,
    group_budgets: pd.DataFrame,
    data: dict[str, pd.DataFrame],
    *,
    signal_delay: int = 0,
) -> CrossAssetResult:
    """Run an ETF alpha family through the frozen v27 portfolio construction."""
    if signal_delay:
        score = score.shift(signal_delay)
        risk_scaler = risk_scaler.shift(signal_delay).fillna(1.0)
        group_budgets = group_budgets.shift(signal_delay).fillna(0.25)
    return run_risk_budget_backtest(
        score,
        data["returns"],
        data["adv"],
        data["eligibility"] & score.notna(),
        normalized_loadings(),
        FACTOR_CAPS,
        risk_group_map(),
        group_budgets,
        risk_scaler=risk_scaler,
        config=RiskBudgetConfig(
            rebalance_every=10,
            max_gross=1.0,
            max_name=0.10,
            max_turnover=0.25,
            max_participation=0.001,
            annual_volatility_cap=0.08,
            net_cap=1.0,
            max_long_gross=1.0,
            max_short_gross=0.50,
            liquidity_limited_cap_reduction=True,
        ),
        costs=COSTS,
    )


def audit_carry_inputs(contracts: Path, metadata: Path) -> tuple[dict, pd.DataFrame]:
    """Run the contract-level futures carry data gate without fabricating a proxy."""
    missing = [str(path) for path in (contracts, metadata) if not path.exists()]
    if missing:
        return (
            {
                "status": "V27_B_BLOCKED_DATA",
                "reason": "REQUIRED_CONTRACT_ARCHIVE_NOT_FOUND",
                "missing_files": missing,
                "strategy_backtest_run": False,
                "orders_allowed": False,
            },
            pd.DataFrame(
                columns=[
                    "root",
                    "sleeve",
                    "first_date",
                    "last_date",
                    "contracts",
                    "observed_sessions",
                    "session_coverage",
                    "two_expiry_session_share",
                    "coverage_pass",
                ]
            ),
        )
    result, roots = audit_tables(read_table(contracts), read_table(metadata))
    admitted = result["status"] == "V23_DATA_ADMITTED_RESEARCH_NOT_RUN"
    result.update(
        status="V27_B_DATA_ADMITTED_RESEARCH_PENDING" if admitted else "V27_B_BLOCKED_DATA",
        reason=None if admitted else "CONTRACT_ARCHIVE_FAILED_QUALITY_GATE",
        strategy_backtest_run=False,
        contracts_sha256=sha256(contracts),
        metadata_sha256=sha256(metadata),
        orders_allowed=False,
    )
    return result, roots


def write_blocked_report(output: Path, summary: dict) -> None:
    admission = summary["track_a"]["admission"]
    carry = summary["track_b"]
    report = f"""# v27 Multi-Source Alpha Framework

## Decision

**{summary['status']}**

v27 changed the alpha hypothesis. Track A tested whether a causal 20-session group-residual
mean-reversion family had independent train evidence next to the frozen trend family. Track B
audited the contract-level futures inputs required for actual term-structure carry.

## Track A — train-only family admission

- Trend calibration: **{admission['trend_status']}**; slope
  **{admission['trend_slope']:.8f}**.
- Residual-MR calibration: **{admission['mean_reversion_status']}**; slope
  **{admission['mean_reversion_slope']:.8f}**.
- Trend/MR pooled train correlation: **{admission['pooled_correlation']:.3f}**.
- MR standalone train Sharpe: **{admission['mean_reversion_train_sharpe']:.3f}**.
- MR frozen-trade 2x-cost train Sharpe:
  **{admission['mean_reversion_double_cost_train_sharpe']:.3f}**.

Track-A reused-development portfolio evaluated: **No**. A family that fails admission is not
sign-flipped, blended or repaired.

## Track B — futures carry data gate

**{carry['status']}**. Missing inputs: {', '.join(carry.get('missing_files', [])) or 'none'}.
ETF distributions and price-derived pseudo-yields were not substituted for term-structure carry.

## Track C

**{summary['track_c']['status']}**. The full 40/30/30 blend was not run because every source must
first pass its own admission gate. Orders remain disabled.
"""
    (output / "REPORT.md").write_text(report)


def main(source: Path, contracts: Path, metadata: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    if sha256(source) != EXPECTED_SOURCE_SHA256:
        raise RuntimeError("source does not match the frozen 45-ETF archive")
    carry_audit, carry_roots = audit_carry_inputs(contracts, metadata)
    carry_roots.to_csv(output / "futures_carry_root_coverage.csv", index=False)
    (output / "track_b_carry_data_gate.json").write_text(
        json.dumps(carry_audit, indent=2, default=str) + "\n"
    )

    train_data = load_data(source, TRAIN[1], UNIVERSE)
    train_trend = build_dynamic_symmetric_tsmom(train_data)
    train_mr = build_residual_mean_reversion(train_data)
    calibrations = {
        "trend": calibrate_absolute(train_trend["sizing_score"], train_data["returns"]),
        "mean_reversion": calibrate_absolute(
            train_mr["sizing_score"], train_data["returns"]
        ),
    }
    calibration_table = pd.DataFrame(
        [{"family": family, **artifact} for family, artifact in calibrations.items()]
    )
    calibration_table.to_csv(output / "train_family_calibration.csv", index=False)
    correlation = pooled_score_correlation(
        train_trend["sizing_score"], train_mr["sizing_score"], TRAIN
    )
    pd.DataFrame([correlation]).to_csv(output / "train_alpha_correlation.csv", index=False)

    mr_train_sharpe = np.nan
    mr_double_train_sharpe = np.nan
    mr_result = None
    if calibrations["mean_reversion"]["status"] == "ADMITTED":
        groups = risk_group_map()
        train_budgets, _ = build_group_risk_budgets(train_data["returns"], groups)
        mr_score = train_mr["sizing_score"] * calibrations["mean_reversion"]["slope"]
        mr_result = run_track_a(
            mr_score,
            train_trend["risk_scaler"],
            train_budgets,
            train_data,
        )
        mr_double = frozen_trade_cost_stress(mr_result, transaction_multiplier=2.0)
        mr_train_sharpe = float(segment_metrics(mr_result, *TRAIN)["sharpe"])
        mr_double_train_sharpe = float(segment_metrics(mr_double, *TRAIN)["sharpe"])
        mr_result.daily.to_csv(output / "track_a_mr_train_daily.csv")
        mr_result.rebalances.to_csv(output / "track_a_mr_train_rebalances.csv")

    admission_components = {
        "trend_positive_slope": calibrations["trend"]["status"] == "ADMITTED",
        "mean_reversion_positive_slope": calibrations["mean_reversion"]["status"]
        == "ADMITTED",
        "mean_reversion_train_sharpe": bool(mr_train_sharpe > 0),
        "mean_reversion_double_cost_train_sharpe": bool(mr_double_train_sharpe > 0),
        "independent_score_correlation": bool(
            abs(correlation["pooled_correlation"]) < 0.75
        ),
    }
    track_a_admitted = all(admission_components.values())
    admission = {
        "passed": track_a_admitted,
        "components": admission_components,
        "trend_status": calibrations["trend"]["status"],
        "trend_slope": float(calibrations["trend"]["slope"]),
        "mean_reversion_status": calibrations["mean_reversion"]["status"],
        "mean_reversion_slope": float(calibrations["mean_reversion"]["slope"]),
        "pooled_correlation": float(correlation["pooled_correlation"]),
        "mean_daily_cross_sectional_correlation": float(
            correlation["mean_daily_cross_sectional_correlation"]
        ),
        "mean_reversion_train_sharpe": float(mr_train_sharpe),
        "mean_reversion_double_cost_train_sharpe": float(mr_double_train_sharpe),
    }

    freeze = {
        "protocol_sha256": sha256(PROTOCOL),
        "source_sha256": sha256(source),
        "costs": asdict(COSTS),
        "track_a_weights": {
            "trend": TREND_WEIGHT_A,
            "mean_reversion": MEAN_REVERSION_WEIGHT_A,
        },
        "family_calibrations": calibrations,
        "reused_development": True,
        "fresh_holdout_available": False,
    }
    (output / "frozen_run_inputs.json").write_text(
        json.dumps(freeze, indent=2, default=str) + "\n"
    )

    if not track_a_admitted:
        track_c_status = (
            "V27_C_NOT_RUN_CARRY_DATA_BLOCKED"
            if carry_audit["status"] == "V27_B_BLOCKED_DATA"
            else "V27_C_NOT_RUN_TRACK_A_FAMILY_REJECTED"
        )
        summary = {
            "status": "V27_A_REJECTED_FAMILY_ADMISSION",
            "reason": "RESIDUAL_MEAN_REVERSION_FAILED_TRAIN_ONLY_GATE",
            "track_a": {
                "status": "V27_A_REJECTED_FAMILY_ADMISSION",
                "admission": admission,
                "development_portfolio_evaluated": False,
            },
            "track_b": carry_audit,
            "track_c": {"status": track_c_status, "portfolio_evaluated": False},
            "historical_gate_passed": False,
            "prospective_validation_required": True,
            "orders_allowed": False,
        }
        (output / "SUMMARY.json").write_text(
            json.dumps(summary, indent=2, default=str) + "\n"
        )
        write_blocked_report(output, summary)
        print(json.dumps(summary, indent=2, default=str))
        return

    data = load_data(source, DEVELOPMENT[1], UNIVERSE)
    trend = build_dynamic_symmetric_tsmom(data)
    mr = build_residual_mean_reversion(data)
    groups = risk_group_map()
    budgets, target_contributions = build_group_risk_budgets(data["returns"], groups)
    trend_score = trend["sizing_score"] * calibrations["trend"]["slope"]
    mr_score = mr["sizing_score"] * calibrations["mean_reversion"]["slope"]
    composite = TREND_WEIGHT_A * trend_score + MEAN_REVERSION_WEIGHT_A * mr_score
    baseline = run_track_a(composite, trend["risk_scaler"], budgets, data)
    doubled = frozen_trade_cost_stress(baseline, transaction_multiplier=2.0)
    delayed = run_track_a(
        composite, trend["risk_scaler"], budgets, data, signal_delay=1
    )
    state_cost = reprice_state_dependent_costs(
        baseline, build_state_cost_multipliers(data)
    )
    trend_only = run_track_a(trend_score, trend["risk_scaler"], budgets, data)
    mr_only = run_track_a(mr_score, trend["risk_scaler"], budgets, data)

    tables = diagnostic_tables(baseline, data)
    train = segment_diagnostics(baseline, data, tables, TRAIN, "train")
    development = segment_diagnostics(
        baseline, data, tables, DEVELOPMENT, "development"
    )
    robustness = pd.DataFrame(
        [
            {"evaluation": "baseline", **segment_metrics(baseline, *DEVELOPMENT)},
            {
                "evaluation": "frozen_trade_double_cost",
                **segment_metrics(doubled, *DEVELOPMENT),
            },
            {"evaluation": "signal_delay_1", **segment_metrics(delayed, *DEVELOPMENT)},
            {
                "evaluation": "state_dependent_cost",
                **segment_metrics(state_cost, *DEVELOPMENT),
            },
        ]
    )
    source_counterfactuals = []
    for family, result in (("trend", trend_only), ("mean_reversion", mr_only)):
        for segment, period in (("train", TRAIN), ("development", DEVELOPMENT)):
            source_counterfactuals.append(
                {"family": family, "segment": segment, **segment_metrics(result, *period)}
            )
    source_counterfactuals = pd.DataFrame(source_counterfactuals)
    group_contribution = group_contribution_table(baseline, data, groups)
    actual_rc = actual_group_risk_contributions(
        baseline, data["returns"], groups, target_contributions, budgets
    )
    robust = robustness.set_index("evaluation")
    positive_groups = int(
        group_contribution.query("segment == 'development'")[
            "gross_return_contribution"
        ].gt(0).sum()
    )
    positive_regimes = int(tables["regimes"]["net_arithmetic_contribution"].gt(0).sum())
    gate_components = {
        "train_sharpe": bool(train["sharpe"] > 0.50),
        "development_sharpe": bool(development["sharpe"] > 0.50),
        "train_cagr": bool(train["cagr"] > 0),
        "development_cagr": bool(development["cagr"] > 0),
        "train_drawdown": bool(train["max_drawdown"] >= -0.15),
        "development_drawdown": bool(development["max_drawdown"] >= -0.15),
        "double_cost": bool(robust.loc["frozen_trade_double_cost", "sharpe"] > 0),
        "signal_delay": bool(robust.loc["signal_delay_1", "sharpe"] > 0),
        "state_cost": bool(robust.loc["state_dependent_cost", "sharpe"] > 0),
        "spy_r_squared": bool(development["spy_r_squared"] < 0.50),
        "concentration": bool(development["top_5_absolute_contribution_share"] < 0.75),
        "positive_groups": bool(positive_groups >= 3),
        "positive_regimes": bool(positive_regimes >= 3),
        "train_operational": operational_pass(train),
        "development_operational": operational_pass(development),
    }
    passed = all(gate_components.values())
    track_a_status = (
        "V27_A_HISTORICAL_GATE_PASS_PROSPECTIVE_REQUIRED"
        if passed
        else "V27_A_REJECTED_PORTFOLIO_GATE"
    )
    track_c_status = (
        "V27_C_NOT_RUN_CARRY_DATA_BLOCKED"
        if carry_audit["status"] == "V27_B_BLOCKED_DATA"
        else "V27_C_RESEARCH_PENDING_CARRY_CALIBRATION"
    )
    summary = {
        "status": track_a_status,
        "reason": None if passed else "TRACK_A_FAILED_FROZEN_PORTFOLIO_GATE",
        "track_a": {
            "status": track_a_status,
            "admission": admission,
            "development_portfolio_evaluated": True,
            "gate_components": gate_components,
            "train": train,
            "development": development,
            "positive_development_groups": positive_groups,
            "positive_development_regimes": positive_regimes,
        },
        "track_b": carry_audit,
        "track_c": {"status": track_c_status, "portfolio_evaluated": False},
        "historical_gate_passed": passed,
        "prospective_validation_required": True,
        "orders_allowed": False,
    }
    baseline.daily.to_csv(output / "track_a_daily.csv")
    baseline.weights.to_csv(output / "track_a_weights.csv.gz", compression="gzip")
    baseline.rebalances.to_csv(output / "track_a_rebalances.csv")
    robustness.to_csv(output / "track_a_robustness.csv", index=False)
    source_counterfactuals.to_csv(output / "source_counterfactuals.csv", index=False)
    group_contribution.to_csv(output / "group_return_contributions.csv", index=False)
    actual_rc.to_csv(output / "actual_group_risk_contributions.csv", index=False)
    for name, table in tables.items():
        table.to_csv(output / f"{name}.csv", index=name == "book_daily")
    (output / "SUMMARY.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n"
    )
    write_blocked_report(output, summary)
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("output/cross_asset_etfs_v17/etf_daily.csv"),
    )
    parser.add_argument(
        "--contracts",
        type=Path,
        default=Path("data/futures/contracts_daily.parquet"),
    )
    parser.add_argument(
        "--metadata",
        type=Path,
        default=Path("data/futures/contracts_metadata.csv"),
    )
    parser.add_argument("--output", type=Path, default=Path("reports/cross_asset_v27"))
    arguments = parser.parse_args()
    main(
        arguments.source,
        arguments.contracts,
        arguments.metadata,
        arguments.output,
    )
