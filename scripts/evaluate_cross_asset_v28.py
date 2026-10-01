"""Evaluate the frozen v28 cross-asset OHLCV alpha decomposition."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from features.alphas import forward_total_return_labels
from scripts.cross_asset_v17_universe import UNIVERSE
from scripts.evaluate_cross_asset_v12 import TRAIN, load_data
from scripts.evaluate_cross_asset_v13 import segment_metrics
from scripts.evaluate_cross_asset_v15 import calibrate_absolute
from scripts.evaluate_cross_asset_v19 import frozen_trade_cost_stress
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
    build_group_risk_budgets,
    group_contribution_table,
    risk_group_map,
)
from scripts.evaluate_cross_asset_v27 import run_track_a
from scripts.evaluate_equity_v7 import sha256

PROTOCOL = Path("docs/MULTI_ASSET_PROTOCOL_V28.md")
EXPECTED_SOURCE_SHA256 = "82347fef112a5f04dc2b5accf947f362eefe1a0a89f1c59bf143a369ab63e32e"
FAMILIES = (
    "overnight_gap_reversal",
    "intraday_reversal",
    "volume_shock_reversal",
)
STANDARDIZATION_WINDOW = 252
STANDARDIZATION_MINIMUM = 126
THRESHOLD_QUANTILE = 0.70


def read_adjusted_ohlcv(
    source: Path, data: dict[str, pd.DataFrame]
) -> dict[str, pd.DataFrame]:
    """Read aligned adjusted OHLC and raw volume from the frozen long table."""
    raw = pd.read_csv(
        source,
        usecols=["symbol", "date", "open", "high", "low", "close", "adj_close", "volume"],
        parse_dates=["date"],
    )
    raw = raw.loc[raw["symbol"].isin(data["close"].columns)].copy()
    index, columns = data["close"].index, data["close"].columns

    def pivot(field: str) -> pd.DataFrame:
        return raw.pivot(index="date", columns="symbol", values=field).reindex(
            index=index, columns=columns
        )

    close = pivot("close")
    adjusted_close = pivot("adj_close")
    adjustment = adjusted_close.div(close.where(close.gt(0)))
    return {
        "open": pivot("open") * adjustment,
        "high": pivot("high") * adjustment,
        "low": pivot("low") * adjustment,
        "close": adjusted_close,
        "volume": pivot("volume"),
    }


def remove_group_median(
    frame: pd.DataFrame, eligibility: pd.DataFrame, groups: pd.Series
) -> pd.DataFrame:
    """Remove the contemporaneous v26 risk-group median from an observed feature."""
    output = pd.DataFrame(np.nan, index=frame.index, columns=frame.columns)
    for group in RISK_GROUPS:
        names = groups.index[groups.eq(group)]
        observed = frame.loc[:, names].where(eligibility.loc[:, names])
        output.loc[:, names] = observed.sub(observed.median(axis=1), axis=0)
    return output.where(eligibility)


def causal_dislocation_signal(
    raw_feature: pd.DataFrame, eligibility: pd.DataFrame
) -> dict[str, pd.DataFrame]:
    """Standardize one feature using prior observations and activate its extreme tails."""
    reference = raw_feature.rolling(
        STANDARDIZATION_WINDOW, min_periods=STANDARDIZATION_MINIMUM
    )
    prior_mean = reference.mean().shift(1)
    prior_std = reference.std(ddof=1).shift(1)
    z_score = raw_feature.sub(prior_mean).div(prior_std.where(prior_std.gt(0))).clip(-5, 5)
    threshold = z_score.abs().rolling(
        STANDARDIZATION_WINDOW, min_periods=STANDARDIZATION_MINIMUM
    ).quantile(THRESHOLD_QUANTILE).shift(1)
    signal = np.tanh(z_score).where(z_score.abs().gt(threshold), 0.0).where(eligibility)
    return {
        "raw": raw_feature.where(eligibility),
        "z_score": z_score.where(eligibility),
        "threshold": threshold.where(eligibility),
        "signal": signal,
    }


def build_ohlcv_families(
    source: Path, data: dict[str, pd.DataFrame]
) -> dict[str, dict[str, pd.DataFrame]]:
    """Build the three frozen next-session OHLCV dislocation families."""
    bars = read_adjusted_ohlcv(source, data)
    groups = risk_group_map().reindex(data["returns"].columns)
    eligibility = data["eligibility"]
    overnight = -np.log(bars["open"].div(bars["close"].shift(1)))
    intraday = -np.log(bars["close"].div(bars["open"]))
    group_return_residual = remove_group_median(data["returns"], eligibility, groups)
    log_volume = np.log1p(bars["volume"].where(bars["volume"].ge(0)))
    volume_surprise = log_volume.sub(
        log_volume.rolling(60, min_periods=60).median().shift(1)
    )
    raw = {
        "overnight_gap_reversal": remove_group_median(overnight, eligibility, groups),
        "intraday_reversal": remove_group_median(intraday, eligibility, groups),
        "volume_shock_reversal": remove_group_median(
            -group_return_residual * volume_surprise.abs(), eligibility, groups
        ),
    }
    trend = build_dynamic_symmetric_tsmom(data)
    output = {}
    for family, feature in raw.items():
        fields = causal_dislocation_signal(feature, eligibility)
        fields["sizing_score"] = fields["signal"].div(
            trend["effective_volatility"].where(trend["effective_volatility"].gt(0))
        )
        output[family] = fields
    return output


def qualify_families(
    features: dict[str, dict[str, pd.DataFrame]], returns: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, list[str], dict[str, dict]]:
    """Apply the frozen train-only slope, rank-IC, stability and correlation gates."""
    labels, label_end = forward_total_return_labels(returns, 5)
    completed = label_end.le(TRAIN[1])
    rows = []
    daily_ics = {}
    calibrations = {}
    for family in FAMILIES:
        score = features[family]["sizing_score"]
        calibrations[family] = calibrate_absolute(score, returns)
        signal = score.loc[TRAIN[0] : TRAIN[1]].where(
            completed.loc[TRAIN[0] : TRAIN[1]]
        )
        target = labels.loc[TRAIN[0] : TRAIN[1]].where(
            completed.loc[TRAIN[0] : TRAIN[1]]
        )
        daily_ic = signal.corrwith(target, axis=1, method="spearman")
        daily_ics[family] = daily_ic
        annual = daily_ic.groupby(daily_ic.index.year).mean().dropna()
        mean_ic = float(daily_ic.mean())
        std_ic = float(daily_ic.std(ddof=1))
        icir = mean_ic / std_ic if std_ic > 0 else np.nan
        positive_years = int(annual.gt(0).sum())
        observed_years = int(annual.size)
        artifact = calibrations[family]
        statistical_pass = bool(
            artifact["status"] == "ADMITTED"
            and mean_ic > 0
            and icir >= 0.02
            and observed_years >= 6
            and positive_years >= 6
        )
        rows.append(
            {
                "family": family,
                "slope": artifact["slope"],
                "observations": artifact.get("observations", 0),
                "pooled_correlation": artifact.get("pooled_correlation", np.nan),
                "mean_rank_ic": mean_ic,
                "rank_ic_std": std_ic,
                "icir": icir,
                "positive_years": positive_years,
                "observed_years": observed_years,
                "statistical_pass": statistical_pass,
            }
        )
    qualification = pd.DataFrame(rows).set_index("family")
    ic_frame = pd.DataFrame(daily_ics)
    admitted = []
    ordered = qualification.loc[qualification["statistical_pass"]].sort_values(
        ["icir", "mean_rank_ic"], ascending=False
    ).index
    for family in ordered:
        if all(abs(ic_frame[family].corr(ic_frame[prior])) < 0.75 for prior in admitted):
            admitted.append(family)
        if len(admitted) == 2:
            break
    qualification["correlation_admitted"] = qualification.index.isin(admitted)
    annual_table = pd.DataFrame(daily_ics).groupby(ic_frame.index.year).mean()
    return qualification.reset_index(), annual_table, admitted, calibrations


def write_report(output: Path, summary: dict) -> None:
    rows = []
    for family, evidence in summary["families"].items():
        rows.append(
            f"| {family} | {evidence['slope']:.8f} | {evidence['mean_rank_ic']:.4f} | "
            f"{evidence['icir']:.4f} | {evidence['positive_years']}/"
            f"{evidence['observed_years']} | {evidence['decision']} |"
        )
    table = "\n".join(rows)
    standalone_rows = []
    for family, evidence in summary["families"].items():
        if "standalone_train_sharpe" not in evidence:
            continue
        sharpe = evidence["standalone_train_sharpe"]
        doubled = evidence["double_cost_train_sharpe"]
        sharpe_text = f"{sharpe:.3f}" if sharpe is not None else "cash / undefined"
        doubled_text = f"{doubled:.3f}" if doubled is not None else "cash / undefined"
        standalone_rows.append(f"| {family} | {sharpe_text} | {doubled_text} |")
    standalone_table = "\n".join(standalone_rows) or "| None | n/a | n/a |"
    report = f"""# v28 Cross-Asset OHLCV Information Decomposition

## Decision

**{summary['status']}**

The three OHLCV hypotheses were frozen before evaluation. Current-session bars affect only the
next session. Every feature was risk-group residualized and standardized with prior observations.

| Family | Five-day slope | Mean rank IC | ICIR | Positive years | Decision |
|---|---:|---:|---:|---:|---|
{table}

Statistically admitted families: **{', '.join(summary['statistically_admitted']) or 'none'}**.
Portfolio-admitted families: **{', '.join(summary['portfolio_admitted']) or 'none'}**.
Reused-development portfolio evaluated: **{summary['development_portfolio_evaluated']}**.

| Train standalone family | Net Sharpe | Frozen-trade 2x-cost Sharpe |
|---|---:|---:|
{standalone_table}

An undefined Sharpe denotes an all-cash optimizer result: after calibrated expected return and
costs, the frozen objective found no trade with positive net value. It is a failed admission, not
missing performance.

No rejected feature was sign-flipped, assigned a different horizon or repaired after viewing its
train statistics. Orders remain disabled.
"""
    (output / "REPORT.md").write_text(report)


def main(source: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    if sha256(source) != EXPECTED_SOURCE_SHA256:
        raise RuntimeError("source does not match the frozen 45-ETF archive")
    train_data = load_data(source, TRAIN[1], UNIVERSE)
    train_features = build_ohlcv_families(source, train_data)
    qualification, annual_ic, statistically_admitted, calibrations = qualify_families(
        train_features, train_data["returns"]
    )
    qualification.to_csv(output / "train_family_qualification.csv", index=False)
    annual_ic.to_csv(output / "train_annual_rank_ic.csv", index_label="year")
    ic_series = {}
    labels, label_end = forward_total_return_labels(train_data["returns"], 5)
    completed = label_end.le(TRAIN[1])
    for family in FAMILIES:
        ic_series[family] = train_features[family]["sizing_score"].where(
            completed
        ).corrwith(labels.where(completed), axis=1, method="spearman")
    pd.DataFrame(ic_series).corr().to_csv(output / "train_daily_ic_correlation.csv")

    groups = risk_group_map()
    train_budgets, _ = build_group_risk_budgets(train_data["returns"], groups)
    trend = build_dynamic_symmetric_tsmom(train_data)
    standalone_rows = []
    portfolio_admitted = []
    for family in statistically_admitted:
        score = train_features[family]["sizing_score"] * calibrations[family]["slope"]
        result = run_track_a(score, trend["risk_scaler"], train_budgets, train_data)
        doubled = frozen_trade_cost_stress(result, transaction_multiplier=2.0)
        metrics = segment_metrics(result, *TRAIN)
        doubled_metrics = segment_metrics(doubled, *TRAIN)
        passed = bool(metrics["sharpe"] > 0 and doubled_metrics["sharpe"] > 0)
        standalone_rows.append(
            {
                "family": family,
                "status": result.status,
                "train_sharpe": metrics["sharpe"],
                "train_cagr": metrics["cagr"],
                "train_max_drawdown": metrics["max_drawdown"],
                "double_cost_train_sharpe": doubled_metrics["sharpe"],
                "passed": passed,
            }
        )
        if passed:
            portfolio_admitted.append(family)
    standalone = pd.DataFrame(
        standalone_rows,
        columns=[
            "family",
            "status",
            "train_sharpe",
            "train_cagr",
            "train_max_drawdown",
            "double_cost_train_sharpe",
            "passed",
        ],
    )
    standalone.to_csv(output / "standalone_train_portfolios.csv", index=False)

    evidence = {}
    qualification_indexed = qualification.set_index("family")
    standalone_indexed = standalone.set_index("family") if not standalone.empty else standalone
    for family in FAMILIES:
        row = qualification_indexed.loc[family]
        if not bool(row["statistical_pass"]):
            decision = "REJECTED_STATISTICAL_GATE"
        elif family not in statistically_admitted:
            decision = "REJECTED_ADMISSION_RANK_OR_DIVERSIFICATION_CAP"
        elif family not in portfolio_admitted:
            decision = "REJECTED_STANDALONE_PORTFOLIO_GATE"
        else:
            decision = "ADMITTED"
        evidence[family] = {
            "slope": float(row["slope"]),
            "mean_rank_ic": float(row["mean_rank_ic"]),
            "icir": float(row["icir"]),
            "positive_years": int(row["positive_years"]),
            "observed_years": int(row["observed_years"]),
            "decision": decision,
        }
        if family in statistically_admitted:
            train_sharpe = float(standalone_indexed.loc[family, "train_sharpe"])
            doubled_sharpe = float(
                standalone_indexed.loc[family, "double_cost_train_sharpe"]
            )
            evidence[family]["standalone_train_sharpe"] = (
                train_sharpe if np.isfinite(train_sharpe) else None
            )
            evidence[family]["double_cost_train_sharpe"] = (
                doubled_sharpe if np.isfinite(doubled_sharpe) else None
            )

    freeze = {
        "protocol_sha256": sha256(PROTOCOL),
        "source_sha256": sha256(source),
        "trend_weight": 0.60,
        "ohlcv_weight": 0.40,
        "family_calibrations": calibrations,
        "statistically_admitted": statistically_admitted,
        "portfolio_admitted": portfolio_admitted,
        "reused_development": True,
    }
    (output / "frozen_run_inputs.json").write_text(
        json.dumps(freeze, indent=2, default=str) + "\n"
    )

    if not statistically_admitted or not portfolio_admitted:
        status = (
            "V28_REJECTED_FAMILY_QUALIFICATION"
            if not statistically_admitted
            else "V28_REJECTED_STANDALONE_TRAIN"
        )
        summary = {
            "status": status,
            "reason": "NO_OHLCV_FAMILY_PASSED_FROZEN_TRAIN_ADMISSION",
            "families": evidence,
            "statistically_admitted": statistically_admitted,
            "portfolio_admitted": portfolio_admitted,
            "development_portfolio_evaluated": False,
            "historical_gate_passed": False,
            "orders_allowed": False,
        }
        (output / "SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n")
        write_report(output, summary)
        print(json.dumps(summary, indent=2))
        return

    data = load_data(source, DEVELOPMENT[1], UNIVERSE)
    features = build_ohlcv_families(source, data)
    trend = build_dynamic_symmetric_tsmom(data)
    budgets, _ = build_group_risk_budgets(data["returns"], groups)
    trend_calibration = calibrate_absolute(trend["sizing_score"], data["returns"])
    trend_score = trend["sizing_score"] * trend_calibration["slope"]
    family_weight = 0.40 / len(portfolio_admitted)
    composite = 0.60 * trend_score + sum(
        family_weight * features[family]["sizing_score"] * calibrations[family]["slope"]
        for family in portfolio_admitted
    )
    baseline = run_track_a(composite, trend["risk_scaler"], budgets, data)
    doubled = frozen_trade_cost_stress(baseline, transaction_multiplier=2.0)
    delayed = run_track_a(composite, trend["risk_scaler"], budgets, data, signal_delay=1)
    state = reprice_state_dependent_costs(baseline, build_state_cost_multipliers(data))
    tables = diagnostic_tables(baseline, data)
    train_metrics = segment_diagnostics(baseline, data, tables, TRAIN, "train")
    development_metrics = segment_diagnostics(
        baseline, data, tables, DEVELOPMENT, "development"
    )
    robustness = {
        "double_cost": segment_metrics(doubled, *DEVELOPMENT)["sharpe"],
        "signal_delay": segment_metrics(delayed, *DEVELOPMENT)["sharpe"],
        "state_cost": segment_metrics(state, *DEVELOPMENT)["sharpe"],
    }
    group_contribution = group_contribution_table(baseline, data, groups)
    positive_groups = int(
        group_contribution.query("segment == 'development'")[
            "gross_return_contribution"
        ].gt(0).sum()
    )
    positive_regimes = int(tables["regimes"]["net_arithmetic_contribution"].gt(0).sum())
    gate = {
        "train_sharpe": bool(train_metrics["sharpe"] > 0.50),
        "development_sharpe": bool(development_metrics["sharpe"] > 0.50),
        "train_cagr": bool(train_metrics["cagr"] > 0),
        "development_cagr": bool(development_metrics["cagr"] > 0),
        "train_drawdown": bool(train_metrics["max_drawdown"] >= -0.15),
        "development_drawdown": bool(development_metrics["max_drawdown"] >= -0.15),
        "double_cost": bool(robustness["double_cost"] > 0),
        "signal_delay": bool(robustness["signal_delay"] > 0),
        "state_cost": bool(robustness["state_cost"] > 0),
        "spy_r_squared": bool(development_metrics["spy_r_squared"] < 0.50),
        "concentration": bool(
            development_metrics["top_5_absolute_contribution_share"] < 0.75
        ),
        "positive_groups": bool(positive_groups >= 3),
        "positive_regimes": bool(positive_regimes >= 3),
        "train_operational": operational_pass(train_metrics),
        "development_operational": operational_pass(development_metrics),
    }
    passed = all(gate.values())
    summary = {
        "status": (
            "V28_HISTORICAL_GATE_PASS_PROSPECTIVE_REQUIRED"
            if passed
            else "V28_REJECTED_PORTFOLIO_GATE"
        ),
        "reason": None if passed else "OHLCV_BLEND_FAILED_FROZEN_PORTFOLIO_GATE",
        "families": evidence,
        "statistically_admitted": statistically_admitted,
        "portfolio_admitted": portfolio_admitted,
        "development_portfolio_evaluated": True,
        "train": train_metrics,
        "development": development_metrics,
        "robustness_sharpe": robustness,
        "gate_components": gate,
        "historical_gate_passed": passed,
        "orders_allowed": False,
    }
    baseline.daily.to_csv(output / "daily.csv")
    baseline.weights.to_csv(output / "weights.csv.gz", compression="gzip")
    baseline.rebalances.to_csv(output / "rebalances.csv")
    group_contribution.to_csv(output / "group_return_contributions.csv", index=False)
    for name, table in tables.items():
        table.to_csv(output / f"{name}.csv", index=name == "book_daily")
    (output / "SUMMARY.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n"
    )
    write_report(output, summary)
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("output/cross_asset_etfs_v17/etf_daily.csv"),
    )
    parser.add_argument("--output", type=Path, default=Path("reports/cross_asset_v28"))
    arguments = parser.parse_args()
    main(arguments.source, arguments.output)
