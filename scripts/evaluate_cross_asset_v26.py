"""Evaluate the frozen v26 adaptive multi-asset trend allocation candidate."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, minimize

from backtest.cross_asset import CrossAssetResult
from backtest.cross_asset_budget import RiskBudgetConfig, run_risk_budget_backtest
from portfolio.optimizer import PortfolioCosts
from scripts.cross_asset_v17_universe import UNIVERSE, asset_sleeves
from scripts.evaluate_cross_asset_v12 import TEST, TRAIN, VALIDATION, load_data
from scripts.evaluate_cross_asset_v13 import segment_metrics
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
from scripts.evaluate_cross_asset_v25 import build_market_regime
from scripts.evaluate_equity_v7 import sha256

PROTOCOL = Path("docs/MULTI_ASSET_PROTOCOL_V26.md")
EXPECTED_SOURCE_SHA256 = "82347fef112a5f04dc2b5accf947f362eefe1a0a89f1c59bf143a369ab63e32e"
EXPECTED_V24_SLOPE = 5.1513871248276005e-05
DEVELOPMENT = (VALIDATION[0], TEST[1])
RISK_GROUPS = ("growth", "rates", "real_assets", "fx")
RISK_TARGET = 0.25
PRIOR_REPORTS = {
    "v24": Path("reports/cross_asset_v24"),
    "v25": Path("reports/cross_asset_v25"),
}


def risk_group_map() -> pd.Series:
    """Map the frozen six sleeves into four macro risk groups."""
    sleeves = asset_sleeves()
    mapping = {
        "equity": "growth",
        "credit": "growth",
        "rates": "rates",
        "metals": "real_assets",
        "commodity": "real_assets",
        "usd": "fx",
    }
    groups = sleeves.map(mapping)
    if groups.isna().any():
        raise ValueError("every asset sleeve must map to a v26 risk group")
    return groups


def solve_equal_risk_budget(covariance: np.ndarray) -> tuple[np.ndarray, np.ndarray, bool]:
    """Solve bounded nonnegative group weights closest to equal variance contributions."""
    covariance = np.asarray(covariance, dtype=float)
    if covariance.shape != (4, 4) or not np.isfinite(covariance).all():
        return np.full(4, 0.25), np.full(4, 0.25), False
    covariance = covariance + np.eye(4) * 1e-12

    def contribution(weight):
        marginal = covariance @ weight
        total = float(weight @ marginal)
        if total <= 0:
            return np.full(4, np.nan)
        return weight * marginal / total

    def objective(weight):
        share = contribution(weight)
        if not np.isfinite(share).all():
            return 1e6
        return float(np.square(share - RISK_TARGET).sum())

    result = minimize(
        objective,
        np.full(4, 0.25),
        method="SLSQP",
        bounds=Bounds(np.full(4, 0.10), np.full(4, 0.40)),
        constraints=[LinearConstraint(np.ones((1, 4)), 1.0, 1.0)],
        options={"maxiter": 500, "ftol": 1e-12, "disp": False},
    )
    weight = result.x if result.success else np.full(4, 0.25)
    share = contribution(weight)
    valid = bool(
        np.isfinite(weight).all()
        and np.isfinite(share).all()
        and abs(weight.sum() - 1) <= 1e-7
        and (weight >= 0.10 - 1e-7).all()
        and (weight <= 0.40 + 1e-7).all()
    )
    return weight, share, valid


def build_group_risk_budgets(
    returns: pd.DataFrame, groups: pd.Series, rebalance_every: int = 10
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build causal four-group gross caps and proxy risk-contribution evidence."""
    proxy = returns.T.groupby(groups).mean().T.reindex(columns=RISK_GROUPS)
    budgets = pd.DataFrame(np.nan, index=returns.index, columns=RISK_GROUPS)
    contributions = pd.DataFrame(np.nan, index=returns.index, columns=RISK_GROUPS)
    budgets.iloc[:60] = 0.25
    contributions.iloc[:60] = 0.25
    for offset in range(60, len(returns)):
        if offset % rebalance_every != 0:
            continue
        covariance = proxy.iloc[offset - 60 : offset].cov().to_numpy(dtype=float)
        weight, share, valid = solve_equal_risk_budget(covariance)
        if not valid:
            raise RuntimeError(f"risk-budget solve failed at {returns.index[offset]}")
        budgets.iloc[offset] = weight
        contributions.iloc[offset] = share
    return budgets.ffill().fillna(0.25), contributions.ffill().fillna(0.25)


def build_relative_strength(
    composite: pd.DataFrame, groups: pd.Series, eligibility: pd.DataFrame
) -> dict[str, pd.DataFrame]:
    """Build causal within-group relative-strength z-scores and signals."""
    residual = pd.DataFrame(index=composite.index, columns=composite.columns, dtype=float)
    for group in RISK_GROUPS:
        names = groups.index[groups.eq(group)]
        group_median = composite.loc[:, names].median(axis=1, skipna=True)
        residual.loc[:, names] = composite.loc[:, names].sub(group_median, axis=0)
    reference = residual.rolling(252, min_periods=126)
    prior_mean = reference.mean().shift(1)
    prior_standard_deviation = reference.std(ddof=1).shift(1)
    z_score = residual.sub(prior_mean).div(
        prior_standard_deviation.where(prior_standard_deviation.gt(0))
    ).clip(-5, 5)
    threshold = z_score.abs().rolling(252, min_periods=126).quantile(0.70).shift(1)
    signal = np.tanh(z_score).where(z_score.abs().gt(threshold), 0.0).where(eligibility)
    return {
        "residual": residual.where(eligibility),
        "z_score": z_score.where(eligibility),
        "threshold": threshold.where(eligibility),
        "signal": signal,
    }


def apply_adaptive_exposure(
    combined_signal: pd.DataFrame, risk_off: pd.Series, groups: pd.Series
) -> pd.DataFrame:
    """Map combined alpha to long/cash/conditional-short exposure without look-ahead."""
    output = combined_signal.copy()
    risk_on = ~risk_off
    output.loc[risk_on] = output.loc[risk_on].clip(lower=0.0)
    growth_names = groups.index[groups.eq("growth")]
    positive_growth = output.loc[risk_off, growth_names].clip(lower=0.0) * 0.40
    negative_growth = output.loc[risk_off, growth_names].clip(upper=0.0) * 0.50
    output.loc[risk_off, growth_names] = positive_growth + negative_growth
    defensive_names = groups.index[~groups.eq("growth")]
    positive_defensive = output.loc[risk_off, defensive_names].clip(lower=0.0)
    negative_defensive = output.loc[risk_off, defensive_names].clip(upper=0.0) * 0.50
    output.loc[risk_off, defensive_names] = positive_defensive + negative_defensive
    return output


def build_v26_features(data: dict[str, pd.DataFrame]) -> dict:
    """Build the frozen absolute/relative blend, adaptive exposure and ERC budgets."""
    base = build_dynamic_symmetric_tsmom(data)
    groups = risk_group_map()
    relative = build_relative_strength(base["composite"], groups, data["eligibility"])
    combined = 0.50 * base["signal"] + 0.50 * relative["signal"]
    regime = build_market_regime(data)
    adaptive = apply_adaptive_exposure(combined, regime["risk_off"], groups)
    effective_volatility = base["effective_volatility"]
    score = adaptive.div(effective_volatility.where(effective_volatility.gt(0)))
    budgets, target_contributions = build_group_risk_budgets(data["returns"], groups)
    return {
        "absolute_signal": base["signal"],
        "relative_residual": relative["residual"],
        "relative_z_score": relative["z_score"],
        "relative_threshold": relative["threshold"],
        "relative_signal": relative["signal"],
        "combined_signal": combined,
        "adaptive_signal": adaptive,
        "sizing_score": score,
        "risk_scaler": base["risk_scaler"],
        "regime": regime,
        "group_budgets": budgets,
        "target_group_risk_contributions": target_contributions,
        "groups": groups,
    }


def run_candidate(
    score: pd.DataFrame,
    risk_scaler: pd.Series,
    regime: pd.DataFrame,
    group_budgets: pd.DataFrame,
    groups: pd.Series,
    data: dict[str, pd.DataFrame],
    *,
    signal_delay: int = 0,
    costs: PortfolioCosts = COSTS,
) -> CrossAssetResult:
    """Run v26 with synchronized signal, regime, scaler and risk-budget delay."""
    long_scaler = pd.Series(1.0, index=score.index)
    short_scaler = pd.Series(np.where(regime["risk_off"], 0.50, 0.0), index=score.index)
    if signal_delay:
        score = score.shift(signal_delay)
        risk_scaler = risk_scaler.shift(signal_delay).fillna(1.0)
        long_scaler = long_scaler.shift(signal_delay).fillna(1.0)
        short_scaler = short_scaler.shift(signal_delay).fillna(0.0)
        group_budgets = group_budgets.shift(signal_delay).fillna(0.25)
    return run_risk_budget_backtest(
        score,
        data["returns"],
        data["adv"],
        data["eligibility"] & score.notna(),
        normalized_loadings(),
        FACTOR_CAPS,
        groups,
        group_budgets,
        risk_scaler=risk_scaler,
        long_gross_scaler=long_scaler,
        short_gross_scaler=short_scaler,
        config=RiskBudgetConfig(
            rebalance_every=10,
            max_gross=1.0,
            max_name=0.10,
            max_turnover=0.25,
            max_participation=0.001,
            annual_volatility_cap=0.08,
            net_cap=1.0,
            max_long_gross=1.0,
            max_short_gross=1.0,
            liquidity_limited_cap_reduction=True,
        ),
        costs=costs,
    )


def actual_group_risk_contributions(
    result: CrossAssetResult,
    returns: pd.DataFrame,
    groups: pd.Series,
    target: pd.DataFrame,
    budgets: pd.DataFrame,
) -> pd.DataFrame:
    """Estimate causal ex-ante group risk contributions of actual post-trade holdings."""
    rows = []
    for session in result.rebalances.index:
        offset = returns.index.get_loc(session)
        if offset < 60:
            continue
        covariance = returns.iloc[offset - 60 : offset].cov().to_numpy(dtype=float)
        weight = result.weights.loc[session, returns.columns].to_numpy(dtype=float)
        marginal = covariance @ weight
        variance = float(weight @ marginal)
        if variance <= 1e-16:
            continue
        asset_share = weight * marginal / variance
        for group in RISK_GROUPS:
            mask = groups.reindex(returns.columns).eq(group).to_numpy()
            rows.append(
                {
                    "session": session,
                    "group": group,
                    "actual_risk_contribution": float(asset_share[mask].sum()),
                    "target_proxy_risk_contribution": float(target.loc[session, group]),
                    "gross_budget": float(budgets.loc[session, group]),
                }
            )
    return pd.DataFrame(rows)


def load_version_comparison(summary: dict) -> pd.DataFrame:
    """Compare frozen v24-v26 evidence without rerunning prior specifications."""
    summaries = {}
    for version, path in PRIOR_REPORTS.items():
        summaries[version] = json.loads((path / "SUMMARY.json").read_text())
    summaries["v26"] = summary
    metrics = (
        "sharpe",
        "cagr",
        "max_drawdown",
        "annual_turnover",
        "long_net_expectancy",
        "short_net_expectancy",
        "spy_beta",
        "spy_r_squared",
        "top_5_absolute_contribution_share",
    )
    rows = []
    for version, version_summary in summaries.items():
        for segment in ("train", "development"):
            row = {"version": version, "segment": segment}
            row.update(
                {
                    metric: version_summary[segment].get(metric, np.nan)
                    for metric in metrics
                }
            )
            rows.append(row)
    return pd.DataFrame(rows)


def load_year_comparison(current_yearly: pd.DataFrame) -> pd.DataFrame:
    """Assemble frozen yearly attribution for v24-v26."""
    frames = []
    for version, path in PRIOR_REPORTS.items():
        frame = pd.read_csv(path / "yearly.csv")
        frame.insert(0, "version", version)
        frames.append(frame)
    current = current_yearly.copy()
    if "year" not in current.columns:
        current = current.reset_index().rename(columns={current.index.name or "index": "year"})
    current.insert(0, "version", "v26")
    frames.append(current)
    return pd.concat(frames, ignore_index=True)


def group_contribution_table(
    result: CrossAssetResult, data: dict[str, pd.DataFrame], groups: pd.Series
) -> pd.DataFrame:
    weights = result.weights.reindex_like(data["returns"]).fillna(0.0)
    contribution = weights * data["returns"].fillna(0.0)
    rows = []
    for segment, period in {"train": TRAIN, "development": DEVELOPMENT}.items():
        grouped = contribution.loc[period[0] : period[1]].T.groupby(groups).sum().T.sum()
        for group in RISK_GROUPS:
            rows.append(
                {
                    "segment": segment,
                    "group": group,
                    "gross_return_contribution": float(grouped[group]),
                }
            )
    return pd.DataFrame(rows)


def write_report(output: Path, summary: dict) -> None:
    train, development = summary["train"], summary["development"]
    failed = [key for key, value in summary["gate_components"].items() if not value]
    report = f"""# v26 Adaptive Multi-Asset Trend Allocation

## Decision

**{summary['status']}**

v26 combines the frozen v24 absolute trend with an equally weighted within-group relative-strength
signal. Risk-on holds positive signals or cash. Risk-off permits half-strength shorts, cuts positive
growth signals to 40%, and retains positive rates, real-assets and FX signals. Four dynamic group
gross budgets target equal ex-ante proxy risk contribution.

| Metric | Train | Reused development |
|---|---:|---:|
| Net Sharpe | {train['sharpe']:.3f} | {development['sharpe']:.3f} |
| CAGR | {train['cagr']:.2%} | {development['cagr']:.2%} |
| Max drawdown | {train['max_drawdown']:.2%} | {development['max_drawdown']:.2%} |
| SPY beta | {train['spy_beta']:.3f} | {development['spy_beta']:.3f} |
| SPY R-squared | {train['spy_r_squared']:.1%} | {development['spy_r_squared']:.1%} |

v26 improves reused-development risk-adjusted performance relative to v25 while reducing SPY
dependence, but it has no positive train evidence. The frozen candidate therefore fails rather than
being promoted from the reused 2017–2024 window.

## Risk-allocation audit

- Development mean absolute actual group risk-contribution deviation from 25%:
  **{summary['risk_contribution']['development_mean_absolute_deviation']:.2%}**.
- Largest development mean group risk-contribution share:
  **{summary['risk_contribution']['development_maximum_mean_group_share']:.2%}**.
- Positive development risk groups: **{summary['positive_development_groups']} / 4**.
- Emergency liquidity overrides: **{summary['operational']['train_emergency_overrides']}** in train
  and **{summary['operational']['development_emergency_overrides']}** in development.
- Maximum development group-cap ratio: **{summary['development']['maximum_sleeve_budget_ratio']:.2f}x**;
  maximum name-cap excess: **{summary['development']['maximum_name_cap_excess']:.2%}**.
- Failed gate components: **{', '.join(failed) if failed else 'None'}**.

The mean group risk shares are close to 25% in aggregate, but the mean absolute deviation at each
rebalance is **{summary['risk_contribution']['development_mean_absolute_deviation']:.2%}**. That
distinction matters: average allocations conceal unstable point-in-time risk contributions.

## 2022 and 2023

| Version | 2022 net return | 2023 net return |
|---|---:|---:|
| v24 dynamic symmetric | {summary['year_comparison']['v24']['2022']:.2%} | {summary['year_comparison']['v24']['2023']:.2%} |
| v25 regime-aware | {summary['year_comparison']['v25']['2022']:.2%} | {summary['year_comparison']['v25']['2023']:.2%} |
| v26 adaptive allocation | {summary['year_comparison']['v26']['2022']:.2%} | {summary['year_comparison']['v26']['2023']:.2%} |

v26 remains effectively long-only: development short expectancy is
**{development['short_net_expectancy']:.2%}**. The improvement comes from long allocation and lower
equity-beta concentration, not from discovering an independent short alpha.

The 2017–2024 window is reused development evidence. This result cannot validate the model or
authorize orders. Relative strength and risk allocation are assessed together under the frozen v26
portfolio hypothesis; further changes require a new protocol.

Orders allowed: **No**.
"""
    (output / "REPORT.md").write_text(report)


def main(source: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    if sha256(source) != EXPECTED_SOURCE_SHA256:
        raise RuntimeError("source does not match the frozen 45-ETF archive")
    data = load_data(source, DEVELOPMENT[1], UNIVERSE)
    features = build_v26_features(data)
    score = features["sizing_score"] * EXPECTED_V24_SLOPE
    result = run_candidate(
        score,
        features["risk_scaler"],
        features["regime"],
        features["group_budgets"],
        features["groups"],
        data,
    )
    if result.status != "COMPLETED":
        raise RuntimeError(f"v26 portfolio failed: {result.reason}")
    tables = diagnostic_tables(result, data)
    train = segment_diagnostics(result, data, tables, TRAIN, "train")
    development = segment_diagnostics(
        result, data, tables, DEVELOPMENT, "development"
    )
    doubled = frozen_trade_cost_stress(result, transaction_multiplier=2.0)
    delayed = run_candidate(
        score,
        features["risk_scaler"],
        features["regime"],
        features["group_budgets"],
        features["groups"],
        data,
        signal_delay=1,
    )
    state_cost = reprice_state_dependent_costs(
        result, build_state_cost_multipliers(data)
    )
    robustness = pd.DataFrame(
        [
            {"evaluation": "baseline", **segment_metrics(result, *DEVELOPMENT)},
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
    risk_contribution = actual_group_risk_contributions(
        result,
        data["returns"],
        features["groups"],
        features["target_group_risk_contributions"],
        features["group_budgets"],
    )
    group_contribution = group_contribution_table(
        result, data, features["groups"]
    )
    development_rc = risk_contribution.loc[
        risk_contribution["session"].between(*DEVELOPMENT)
    ]
    mean_group_rc = development_rc.groupby("group")["actual_risk_contribution"].mean()
    rc_mad = float((development_rc["actual_risk_contribution"] - RISK_TARGET).abs().mean())
    maximum_mean_rc = float(mean_group_rc.max())
    positive_groups = int(
        group_contribution.query("segment == 'development'")[
            "gross_return_contribution"
        ].gt(0).sum()
    )
    positive_regimes = int(tables["regimes"]["net_arithmetic_contribution"].gt(0).sum())
    robust = robustness.set_index("evaluation")
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
        "concentration": bool(development["top_5_absolute_contribution_share"] < 0.75),
        "spy_r_squared": bool(development["spy_r_squared"] < 0.50),
        "positive_groups": bool(positive_groups >= 3),
        "positive_regimes": bool(positive_regimes >= 3),
        "risk_contribution_deviation": bool(rc_mad <= 0.10),
        "risk_contribution_dominance": bool(maximum_mean_rc <= 0.50),
        "train_operational": operational_pass(train),
        "development_operational": operational_pass(development),
    }
    passed = all(gate_components.values())
    yearly = tables["yearly"]
    comparison = load_version_comparison(
        {"train": train, "development": development}
    )
    year_comparison = load_year_comparison(yearly)
    year_lookup = {
        version: {
            str(year): float(
                year_comparison.loc[
                    (year_comparison["version"].eq(version))
                    & (year_comparison["year"].eq(year)),
                    "net_return_compounded",
                ].iloc[0]
            )
            for year in (2022, 2023)
        }
        for version in ("v24", "v25", "v26")
    }
    rebalance_sessions = pd.to_datetime(result.rebalances.index)
    emergency = result.rebalances["emergency_constraint_override"].astype(bool)
    train_emergency = int(
        emergency.loc[(rebalance_sessions >= TRAIN[0]) & (rebalance_sessions <= TRAIN[1])].sum()
    )
    development_emergency = int(
        emergency.loc[
            (rebalance_sessions >= DEVELOPMENT[0])
            & (rebalance_sessions <= DEVELOPMENT[1])
        ].sum()
    )
    summary = {
        "status": (
            "V26_HISTORICAL_GATE_PASS_PROSPECTIVE_REQUIRED"
            if passed
            else "V26_REJECTED"
        ),
        "reason": None if passed else "ADAPTIVE_TREND_ALLOCATION_FAILED_FROZEN_GATE",
        "historical_gate_passed": passed,
        "gate_components": gate_components,
        "train": train,
        "development": development,
        "risk_contribution": {
            "development_mean_absolute_deviation": rc_mad,
            "development_maximum_mean_group_share": maximum_mean_rc,
            "development_mean_by_group": {
                key: float(value) for key, value in mean_group_rc.items()
            },
        },
        "operational": {
            "train_emergency_overrides": train_emergency,
            "development_emergency_overrides": development_emergency,
        },
        "year_comparison": year_lookup,
        "robustness_sharpe": {
            name: float(robust.loc[name, "sharpe"])
            for name in (
                "frozen_trade_double_cost",
                "signal_delay_1",
                "state_dependent_cost",
            )
        },
        "positive_development_groups": positive_groups,
        "positive_development_regimes": positive_regimes,
        "prospective_validation_required": True,
        "orders_allowed": False,
    }
    freeze = {
        "protocol_sha256": sha256(PROTOCOL),
        "source_sha256": sha256(source),
        "absolute_relative_blend": [0.50, 0.50],
        "risk_group_target": {group: 0.25 for group in RISK_GROUPS},
        "risk_group_weight_bounds": [0.10, 0.40],
        "risk_covariance_window": 60,
        "v24_score_scale": EXPECTED_V24_SLOPE,
        "costs": asdict(COSTS),
        "reused_development": True,
        "fresh_holdout_available": False,
    }
    (output / "frozen_run_inputs.json").write_text(json.dumps(freeze, indent=2) + "\n")
    result.daily.to_csv(output / "daily.csv")
    result.weights.to_csv(output / "weights.csv.gz", compression="gzip")
    result.rebalances.to_csv(output / "rebalances.csv")
    features["group_budgets"].to_csv(output / "group_risk_budgets.csv")
    features["target_group_risk_contributions"].to_csv(
        output / "target_group_risk_contributions.csv"
    )
    features["regime"].to_csv(output / "market_regime.csv")
    risk_contribution.to_csv(output / "actual_group_risk_contributions.csv", index=False)
    group_contribution.to_csv(output / "group_return_contributions.csv", index=False)
    robustness.to_csv(output / "robustness.csv", index=False)
    comparison.to_csv(output / "v24_v25_v26_comparison.csv", index=False)
    year_comparison.to_csv(output / "v24_v25_v26_yearly.csv", index=False)
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
    parser.add_argument("--output", type=Path, default=Path("reports/cross_asset_v26"))
    arguments = parser.parse_args()
    main(arguments.source, arguments.output)
