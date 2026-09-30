"""Evaluate the frozen v25 regime-aware dynamic TSMOM candidate."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from backtest.cross_asset import CrossAssetResult
from backtest.cross_asset_budget import RiskBudgetConfig, run_risk_budget_backtest
from backtest.engine import performance_metrics
from portfolio.optimizer import PortfolioCosts
from scripts.cross_asset_v17_universe import UNIVERSE, asset_sleeves
from scripts.evaluate_cross_asset_v12 import TEST, TRAIN, VALIDATION, load_data
from scripts.evaluate_cross_asset_v13 import segment_metrics
from scripts.evaluate_cross_asset_v15 import calibrate_absolute
from scripts.evaluate_cross_asset_v19 import (
    COSTS,
    FACTOR_CAPS,
    SLEEVE_CAPS,
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
from scripts.evaluate_equity_v7 import sha256

PROTOCOL = Path("docs/MULTI_ASSET_PROTOCOL_V25.md")
V24_SUMMARY = Path("reports/cross_asset_v24/SUMMARY.json")
V24_YEARLY = Path("reports/cross_asset_v24/yearly.csv")
EXPECTED_SOURCE_SHA256 = "82347fef112a5f04dc2b5accf947f362eefe1a0a89f1c59bf143a369ab63e32e"
EXPECTED_V24_SLOPE = 5.1513871248276005e-05
EXPECTED_V24_DIGEST = "fd015ea2c63e5ca7952585fb7c50d88d6ebd9f18fe5bdf7a9fe01410dab348e3"
DEVELOPMENT = (VALIDATION[0], TEST[1])


def build_market_regime(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Classify the next-session portfolio with the frozen causal SPY rule."""
    close = data["close"]["SPY"]
    returns = data["returns"]["SPY"]
    moving_average_200 = close.rolling(200, min_periods=200).mean()
    return_252 = close.pct_change(252, fill_method=None)
    volatility_20 = returns.rolling(20, min_periods=20).std() * np.sqrt(252)
    volatility_p70 = volatility_20.rolling(252, min_periods=60).quantile(0.70).shift(1)
    risk_off = (
        close.lt(moving_average_200)
        & return_252.lt(0)
        & volatility_20.gt(volatility_p70)
    )
    return pd.DataFrame(
        {
            "spy_close": close,
            "spy_ma200": moving_average_200,
            "spy_return_252": return_252,
            "spy_volatility_20": volatility_20,
            "spy_volatility_p70": volatility_p70,
            "risk_off": risk_off.fillna(False),
            "regime": np.where(risk_off.fillna(False), "risk_off", "risk_on"),
        },
        index=close.index,
    )


def apply_conditional_short_multiplier(
    score: pd.DataFrame, risk_off: pd.Series
) -> pd.DataFrame:
    """Apply the frozen 0.5/1.0 multiplier only to negative scores."""
    short_multiplier = pd.Series(np.where(risk_off, 1.0, 0.5), index=score.index)
    multiplier = pd.DataFrame(
        np.where(score.lt(0), short_multiplier.to_numpy()[:, None], 1.0),
        index=score.index,
        columns=score.columns,
    )
    return score * multiplier


def side_gross_scalers(risk_off: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Return the frozen conditional long and short gross-cap scalers."""
    long_scaler = pd.Series(np.where(risk_off, 0.50, 1.00), index=risk_off.index)
    short_scaler = pd.Series(np.where(risk_off, 1.00, 0.25), index=risk_off.index)
    return long_scaler, short_scaler


def run_candidate(
    score: pd.DataFrame,
    risk_scaler: pd.Series,
    long_gross_scaler: pd.Series,
    short_gross_scaler: pd.Series,
    data: dict[str, pd.DataFrame],
    *,
    signal_delay: int = 0,
    costs: PortfolioCosts = COSTS,
) -> CrossAssetResult:
    """Run the single v25 candidate with synchronized causal delay stress."""
    if signal_delay:
        score = score.shift(signal_delay)
        risk_scaler = risk_scaler.shift(signal_delay).fillna(1.0)
        long_gross_scaler = long_gross_scaler.shift(signal_delay).fillna(1.0)
        short_gross_scaler = short_gross_scaler.shift(signal_delay).fillna(0.25)
    return run_risk_budget_backtest(
        score,
        data["returns"],
        data["adv"],
        data["eligibility"] & score.notna(),
        normalized_loadings(),
        FACTOR_CAPS,
        asset_sleeves(),
        SLEEVE_CAPS,
        risk_scaler=risk_scaler,
        long_gross_scaler=long_gross_scaler,
        short_gross_scaler=short_gross_scaler,
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


def conditional_book_metrics(
    attribution: pd.DataFrame, regime: pd.DataFrame
) -> pd.DataFrame:
    """Measure each book separately in risk-on and risk-off observations."""
    rows = []
    for segment, (start, end) in {"train": TRAIN, "development": DEVELOPMENT}.items():
        period = attribution.loc[start:end]
        period_regime = regime.loc[period.index, "regime"]
        for state in ("risk_on", "risk_off"):
            subset = period.loc[period_regime.eq(state)]
            for book in ("long", "short"):
                net = subset[f"{book}_net_return"]
                metrics = performance_metrics(net)
                rows.append(
                    {
                        "segment": segment,
                        "regime": state,
                        "book": book,
                        "sessions": len(subset),
                        "net_return_arithmetic": float(net.sum()),
                        "annualized_arithmetic_expectancy": float(net.mean() * 252),
                        "average_gross_exposure": float(
                            subset[f"{book}_gross_exposure"].mean()
                        ),
                        **metrics,
                    }
                )
    return pd.DataFrame(rows)


def comparison_table(v24: dict, train: dict, development: dict) -> pd.DataFrame:
    """Build the prespecified v24 versus v25 comparison."""
    rows = []
    for version, summary in (("v24", v24), ("v25", {"train": train, "development": development})):
        for segment in ("train", "development"):
            metrics = summary[segment]
            rows.append(
                {
                    "version": version,
                    "segment": segment,
                    **{
                        key: metrics[key]
                        for key in (
                            "sharpe",
                            "cagr",
                            "max_drawdown",
                            "annual_turnover",
                            "long_net_expectancy",
                            "short_net_expectancy",
                            "long_sharpe",
                            "short_sharpe",
                            "spy_beta",
                            "spy_r_squared",
                            "top_5_absolute_contribution_share",
                        )
                    },
                }
            )
    return pd.DataFrame(rows)


def write_report(output: Path, summary: dict, conditional: pd.DataFrame) -> None:
    train = summary["train"]
    development = summary["development"]
    risk_off = conditional.loc[
        conditional["regime"].eq("risk_off") & conditional["book"].eq("short")
    ].set_index("segment")
    failed = [key for key, value in summary["gate_components"].items() if not value]
    report = f"""# v25 Regime-Aware Dynamic TSMOM

## Decision

**{summary['status']}**

v25 retains the complete v24 signal and changes only side treatment. Risk-on sessions halve
negative scores and cap short gross at 25%. Risk-off sessions use the full short score and a 100%
short cap while limiting long gross to 50%. The common v24 risk scaler still controls total risk.

| Metric | Train | Reused development |
|---|---:|---:|
| Net Sharpe | {train['sharpe']:.3f} | {development['sharpe']:.3f} |
| CAGR | {train['cagr']:.2%} | {development['cagr']:.2%} |
| Max drawdown | {train['max_drawdown']:.2%} | {development['max_drawdown']:.2%} |
| Long net expectancy | {train['long_net_expectancy']:.2%} | {development['long_net_expectancy']:.2%} |
| Short net expectancy | {train['short_net_expectancy']:.2%} | {development['short_net_expectancy']:.2%} |
| Short Sharpe | {train['short_sharpe']:.3f} | {development['short_sharpe']:.3f} |

## Conditional-short test

- Train risk-off sessions: **{int(risk_off.loc['train', 'sessions'])}**; short expectancy:
  **{risk_off.loc['train', 'annualized_arithmetic_expectancy']:.2%}**; short Sharpe:
  **{risk_off.loc['train', 'sharpe']:.3f}**.
- Reused-development risk-off sessions: **{int(risk_off.loc['development', 'sessions'])}**;
  short expectancy: **{risk_off.loc['development', 'annualized_arithmetic_expectancy']:.2%}**;
  short Sharpe: **{risk_off.loc['development', 'sharpe']:.3f}**; average short gross:
  **{risk_off.loc['development', 'average_gross_exposure'] * 100:.2e}%**.
- v24 versus v25 total return in 2022: **{summary['year_comparison']['2022']['v24']:.2%} / {summary['year_comparison']['2022']['v25']:.2%}**; in 2023:
  **{summary['year_comparison']['2023']['v24']:.2%} / {summary['year_comparison']['2023']['v25']:.2%}**.
- Failed gate components: **{', '.join(failed) if failed else 'None'}**.

The regime hypothesis is evaluated on reused data and 2022 helped form it. A positive result would
remain development evidence and require prospective validation. Relative-strength alpha and
universe changes were excluded so this comparison isolates regime conditioning.

Orders allowed: **No**.
"""
    (output / "REPORT.md").write_text(report)


def main(source: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    if sha256(source) != EXPECTED_SOURCE_SHA256:
        raise RuntimeError("source does not match the frozen 45-ETF archive")
    data = load_data(source, DEVELOPMENT[1], UNIVERSE)
    features = build_dynamic_symmetric_tsmom(data)
    base_score = features["sizing_score"]
    risk_scaler = features["risk_scaler"]
    if not isinstance(base_score, pd.DataFrame) or not isinstance(risk_scaler, pd.Series):
        raise TypeError("v24 feature types are invalid")
    calibration = calibrate_absolute(base_score, data["returns"])
    calibration_matches = bool(
        calibration["status"] == "ADMITTED"
        and calibration["digest"] == EXPECTED_V24_DIGEST
        and abs(calibration["slope"] - EXPECTED_V24_SLOPE) <= 1e-15
    )
    regime = build_market_regime(data)
    long_scaler, short_scaler = side_gross_scalers(regime["risk_off"])
    calibrated = base_score * EXPECTED_V24_SLOPE
    conditional_score = apply_conditional_short_multiplier(calibrated, regime["risk_off"])
    freeze = {
        "protocol_sha256": sha256(PROTOCOL),
        "source_sha256": sha256(source),
        "v24_calibration": calibration,
        "v24_calibration_matches": calibration_matches,
        "regime": {
            "spy_below_ma200": True,
            "spy_252_return_negative": True,
            "spy_volatility_above_prior_p70": True,
        },
        "conditional_side_treatment": {
            "risk_on": {
                "long_signal_multiplier": 1.0,
                "short_signal_multiplier": 0.5,
                "long_gross_cap": 1.0,
                "short_gross_cap": 0.25,
            },
            "risk_off": {
                "long_signal_multiplier": 1.0,
                "short_signal_multiplier": 1.0,
                "long_gross_cap": 0.5,
                "short_gross_cap": 1.0,
            },
        },
        "costs": asdict(COSTS),
        "reused_development": True,
        "fresh_holdout_available": False,
    }
    (output / "frozen_run_inputs.json").write_text(json.dumps(freeze, indent=2) + "\n")
    pd.DataFrame([calibration]).to_csv(output / "train_calibration.csv", index=False)
    regime.to_csv(output / "market_regime.csv")
    if not calibration_matches:
        summary = {
            "status": "V25_BLOCKED_V24_CALIBRATION_MISMATCH",
            "historical_gate_passed": False,
            "orders_allowed": False,
        }
        (output / "SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary, indent=2))
        return

    result = run_candidate(
        conditional_score, risk_scaler, long_scaler, short_scaler, data
    )
    tables = diagnostic_tables(result, data)
    train = segment_diagnostics(result, data, tables, TRAIN, "train")
    development = segment_diagnostics(
        result, data, tables, DEVELOPMENT, "development"
    )
    doubled = frozen_trade_cost_stress(result, transaction_multiplier=2.0)
    delayed = run_candidate(
        conditional_score,
        risk_scaler,
        long_scaler,
        short_scaler,
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
    conditional = conditional_book_metrics(tables["book_daily"], regime)
    conditional.to_csv(output / "conditional_book_metrics.csv", index=False)
    risk_off_short = conditional.loc[
        conditional["regime"].eq("risk_off") & conditional["book"].eq("short")
    ].set_index("segment")
    robust = robustness.set_index("evaluation")
    development_sleeves = tables["sleeves"].query("segment == 'development'")
    positive_sleeves = int(development_sleeves["gross_return_contribution"].gt(0).sum())
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
        "train_risk_off_short_expectancy": bool(
            risk_off_short.loc["train", "annualized_arithmetic_expectancy"] > 0
        ),
        "development_risk_off_short_expectancy": bool(
            risk_off_short.loc["development", "annualized_arithmetic_expectancy"] > 0
        ),
        "train_risk_off_short_sharpe": bool(risk_off_short.loc["train", "sharpe"] > 0),
        "development_risk_off_short_sharpe": bool(
            risk_off_short.loc["development", "sharpe"] > 0
        ),
        "train_full_short_expectancy": bool(train["short_net_expectancy"] >= 0),
        "development_full_short_expectancy": bool(
            development["short_net_expectancy"] >= 0
        ),
        "train_long_expectancy": bool(train["long_net_expectancy"] >= 0),
        "development_long_expectancy": bool(development["long_net_expectancy"] >= 0),
        "risk_off_sample": bool((risk_off_short["sessions"] >= 20).all()),
        "concentration": bool(development["top_5_absolute_contribution_share"] < 0.75),
        "spy_r_squared": bool(development["spy_r_squared"] < 0.50),
        "positive_sleeves": bool(positive_sleeves >= 3),
        "positive_regimes": bool(positive_regimes >= 3),
        "train_operational": operational_pass(train),
        "development_operational": operational_pass(development),
    }
    passed = all(gate_components.values())
    v24_yearly = pd.read_csv(V24_YEARLY).assign(version="v24")
    v25_yearly = tables["yearly"].copy().assign(version="v25")
    yearly_comparison = pd.concat([v24_yearly, v25_yearly], ignore_index=True)
    yearly_comparison.to_csv(output / "v24_v25_yearly.csv", index=False)
    yearly_lookup = yearly_comparison.set_index(["year", "version"])[
        "net_return_compounded"
    ]
    summary = {
        "status": (
            "V25_HISTORICAL_GATE_PASS_PROSPECTIVE_REQUIRED"
            if passed
            else "V25_REJECTED"
        ),
        "reason": None if passed else "REGIME_AWARE_CANDIDATE_FAILED_FROZEN_GATE",
        "historical_gate_passed": passed,
        "gate_components": gate_components,
        "train": train,
        "development": development,
        "risk_off_short": {
            segment: {
                key: (
                    int(risk_off_short.loc[segment, key])
                    if key == "sessions"
                    else float(risk_off_short.loc[segment, key])
                )
                for key in (
                    "sessions",
                    "annualized_arithmetic_expectancy",
                    "sharpe",
                    "average_gross_exposure",
                )
            }
            for segment in ("train", "development")
        },
        "year_comparison": {
            str(year): {
                version: float(yearly_lookup.loc[(year, version)])
                for version in ("v24", "v25")
            }
            for year in (2022, 2023)
        },
        "robustness_sharpe": {
            name: float(robust.loc[name, "sharpe"])
            for name in (
                "frozen_trade_double_cost",
                "signal_delay_1",
                "state_dependent_cost",
            )
        },
        "positive_development_sleeves": positive_sleeves,
        "positive_development_regimes": positive_regimes,
        "prospective_validation_required": True,
        "orders_allowed": False,
    }
    v24 = json.loads(V24_SUMMARY.read_text())
    comparison = comparison_table(v24, train, development)
    comparison.to_csv(output / "v24_v25_comparison.csv", index=False)
    result.daily.to_csv(output / "daily.csv")
    result.weights.to_csv(output / "weights.csv.gz", compression="gzip")
    result.rebalances.to_csv(output / "rebalances.csv")
    for name, table in tables.items():
        table.to_csv(output / f"{name}.csv", index=name == "book_daily")
    robustness.to_csv(output / "robustness.csv", index=False)
    (output / "SUMMARY.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n"
    )
    write_report(output, summary, conditional)
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("output/cross_asset_etfs_v17/etf_daily.csv"),
    )
    parser.add_argument("--output", type=Path, default=Path("reports/cross_asset_v25"))
    arguments = parser.parse_args()
    main(arguments.source, arguments.output)
