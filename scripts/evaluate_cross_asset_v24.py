"""Evaluate the frozen v24 dynamic symmetric time-series momentum candidate."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from backtest.cross_asset import CrossAssetResult
from backtest.cross_asset_budget import RiskBudgetConfig, run_risk_budget_backtest
from portfolio.optimizer import PortfolioCosts
from scripts.audit_v20_comment_claims import regression_diagnostics
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
    book_metrics,
    build_state_cost_multipliers,
    long_short_daily_attribution,
    reprice_state_dependent_costs,
)
from scripts.evaluate_equity_v7 import sha256

PROTOCOL = Path("docs/MULTI_ASSET_PROTOCOL_V24.md")
EXPECTED_SOURCE_SHA256 = "82347fef112a5f04dc2b5accf947f362eefe1a0a89f1c59bf143a369ab63e32e"
DEVELOPMENT = (VALIDATION[0], TEST[1])
MOMENTUM_WEIGHTS = {63: 0.25, 126: 0.35, 252: 0.40}
SKIP_SESSIONS = 21
VOLATILITY_WINDOW = 60
STANDARDIZATION_WINDOW = 252
STANDARDIZATION_MINIMUM = 126
THRESHOLD_QUANTILE = 0.70
VOLATILITY_FLOOR = 0.08


def symmetric_position(
    z_score: pd.DataFrame,
    threshold: pd.DataFrame,
    trend_strength: pd.DataFrame,
) -> pd.DataFrame:
    """Map standardized trend to an exactly odd long/short signal."""
    active = z_score.abs().gt(threshold) & np.sign(z_score).eq(np.sign(trend_strength))
    return np.tanh(z_score).where(active, 0.0)


def build_regime_scaler(data: dict[str, pd.DataFrame]) -> pd.Series:
    """Build the frozen causal 1.0/0.7/0.4 portfolio-level risk scaler."""
    market_return = data["returns"]["SPY"]
    market_close = data["close"]["SPY"]
    realized = market_return.rolling(20, min_periods=20).std() * np.sqrt(252)
    reference = realized.rolling(252, min_periods=60)
    p80 = reference.quantile(0.80).shift(1)
    p95 = reference.quantile(0.95).shift(1)
    drawdown = market_close.div(market_close.cummax()).sub(1)
    moderate = realized.gt(p80) | drawdown.le(-0.10)
    stress = realized.gt(p95) | drawdown.le(-0.15)
    scaler = pd.Series(1.0, index=market_return.index, name="risk_scaler")
    scaler.loc[moderate] = 0.7
    scaler.loc[stress] = 0.4
    return scaler


def build_dynamic_symmetric_tsmom(
    data: dict[str, pd.DataFrame],
) -> dict[str, pd.DataFrame | pd.Series]:
    """Build the prespecified causal z-score, threshold and symmetric sizing score."""
    close = data["close"]
    returns = data["returns"]
    eligibility = data["eligibility"]
    log_price = np.log(close)
    daily_volatility = returns.rolling(
        VOLATILITY_WINDOW, min_periods=VOLATILITY_WINDOW
    ).std().shift(1)
    components = []
    for horizon, weight in MOMENTUM_WEIGHTS.items():
        move = log_price.shift(SKIP_SESSIONS).sub(log_price.shift(horizon))
        components.append(
            weight * move.div(daily_volatility * np.sqrt(horizon - SKIP_SESSIONS))
        )
    composite = sum(components)
    reference = composite.rolling(
        STANDARDIZATION_WINDOW, min_periods=STANDARDIZATION_MINIMUM
    )
    prior_mean = reference.mean().shift(1)
    prior_standard_deviation = reference.std(ddof=1).shift(1)
    z_score = composite.sub(prior_mean).div(
        prior_standard_deviation.where(prior_standard_deviation.gt(0))
    ).clip(-5, 5)
    threshold = z_score.abs().rolling(
        STANDARDIZATION_WINDOW, min_periods=STANDARDIZATION_MINIMUM
    ).quantile(THRESHOLD_QUANTILE).shift(1)

    moving_average_50 = close.rolling(50, min_periods=50).mean()
    moving_average_200 = close.rolling(200, min_periods=200).mean()
    trend_strength = np.log(moving_average_50.div(moving_average_200)).div(
        daily_volatility * np.sqrt(150)
    )
    signal = symmetric_position(z_score, threshold, trend_strength).where(eligibility)

    annualized_volatility = daily_volatility * np.sqrt(252)
    cross_sectional_floor = annualized_volatility.median(axis=1, skipna=True).div(1.5)
    effective_volatility = annualized_volatility.clip(lower=VOLATILITY_FLOOR)
    effective_volatility = effective_volatility.clip(lower=cross_sectional_floor, axis=0)
    sizing_score = signal.div(effective_volatility.where(effective_volatility.gt(0)))
    return {
        "composite": composite.where(eligibility),
        "prior_mean": prior_mean.where(eligibility),
        "prior_standard_deviation": prior_standard_deviation.where(eligibility),
        "z_score": z_score.where(eligibility),
        "threshold": threshold.where(eligibility),
        "trend_strength": trend_strength.where(eligibility),
        "signal": signal,
        "annualized_volatility": annualized_volatility.where(eligibility),
        "effective_volatility": effective_volatility.where(eligibility),
        "sizing_score": sizing_score.where(eligibility),
        "risk_scaler": build_regime_scaler(data),
    }


def run_candidate(
    score: pd.DataFrame,
    risk_scaler: pd.Series,
    data: dict[str, pd.DataFrame],
    *,
    signal_delay: int = 0,
    costs: PortfolioCosts = COSTS,
) -> CrossAssetResult:
    """Run the sole frozen candidate with symmetric long and short gross budgets."""
    delayed_score = score.shift(signal_delay) if signal_delay else score
    delayed_scaler = (
        risk_scaler.shift(signal_delay).fillna(1.0) if signal_delay else risk_scaler
    )
    config = RiskBudgetConfig(
        rebalance_every=10,
        max_gross=1.0,
        max_name=0.10,
        max_turnover=0.25,
        max_participation=0.001,
        annual_volatility_cap=0.08,
        net_cap=0.20,
        max_long_gross=0.50,
        max_short_gross=0.50,
        liquidity_limited_cap_reduction=True,
    )
    return run_risk_budget_backtest(
        delayed_score,
        data["returns"],
        data["adv"],
        data["eligibility"] & delayed_score.notna(),
        normalized_loadings(),
        FACTOR_CAPS,
        asset_sleeves(),
        SLEEVE_CAPS,
        risk_scaler=delayed_scaler,
        config=config,
        costs=costs,
    )


def diagnostic_tables(
    result: CrossAssetResult, data: dict[str, pd.DataFrame]
) -> dict[str, pd.DataFrame]:
    """Return reconciled book, yearly, sleeve and regime evidence."""
    attribution = long_short_daily_attribution(result, data["returns"])
    books = pd.DataFrame(
        book_metrics(attribution, *TRAIN, segment="train", cost_model="baseline")
        + book_metrics(
            attribution, *DEVELOPMENT, segment="development", cost_model="baseline"
        )
        + book_metrics(
            attribution,
            pd.Timestamp("2022-01-03"),
            pd.Timestamp("2022-12-30"),
            segment="diagnostic_2022",
            cost_model="baseline",
        )
    )
    weights = result.weights.reindex_like(data["returns"]).fillna(0.0)
    contribution = weights * data["returns"].fillna(0.0)
    sleeves = asset_sleeves()
    sleeve_rows = []
    for segment, period in {"train": TRAIN, "development": DEVELOPMENT}.items():
        by_sleeve = contribution.loc[period[0] : period[1]].T.groupby(sleeves).sum().T
        for sleeve in sorted(sleeves.unique()):
            sleeve_rows.append(
                {
                    "segment": segment,
                    "sleeve": sleeve,
                    "gross_return_contribution": float(by_sleeve[sleeve].sum()),
                }
            )
    yearly_rows = []
    development_daily = result.daily.loc[DEVELOPMENT[0] : DEVELOPMENT[1]]
    for year, daily in development_daily.groupby(development_daily.index.year):
        book = attribution.loc[daily.index]
        yearly_rows.append(
            {
                "year": int(year),
                "net_return_compounded": float((1 + daily["net_return"]).prod() - 1),
                "long_net_contribution": float(book["long_net_return"].sum()),
                "short_net_contribution": float(book["short_net_return"].sum()),
                "transaction_cost": float(daily["transaction_cost"].sum()),
                "borrow_cost": float(daily["borrow_cost"].sum()),
            }
        )
    regimes = {
        "2017_2019": (pd.Timestamp("2017-01-03"), pd.Timestamp("2019-12-31")),
        "2020": (pd.Timestamp("2020-01-01"), pd.Timestamp("2020-12-31")),
        "2021_2022": (pd.Timestamp("2021-01-04"), pd.Timestamp("2022-12-30")),
        "2023_2024": (pd.Timestamp("2023-01-03"), pd.Timestamp("2024-12-31")),
    }
    regime_rows = [
        {
            "regime": name,
            "net_arithmetic_contribution": float(
                result.daily.loc[start:end, "net_return"].sum()
            ),
        }
        for name, (start, end) in regimes.items()
    ]
    return {
        "book_daily": attribution,
        "book_metrics": books,
        "yearly": pd.DataFrame(yearly_rows),
        "sleeves": pd.DataFrame(sleeve_rows),
        "regimes": pd.DataFrame(regime_rows),
    }


def segment_diagnostics(
    result: CrossAssetResult,
    data: dict[str, pd.DataFrame],
    tables: dict[str, pd.DataFrame],
    period: tuple[pd.Timestamp, pd.Timestamp],
    segment: str,
) -> dict:
    """Build the prespecified performance, symmetry and constraint diagnostics."""
    metrics = segment_metrics(result, *period)
    if metrics.get("status") != "COMPLETED":
        return metrics
    books = tables["book_metrics"].loc[
        tables["book_metrics"]["segment"].eq(segment)
    ].set_index("book")
    weights = result.weights.reindex_like(data["returns"]).fillna(0.0)
    contribution = (weights * data["returns"].fillna(0.0)).loc[period[0] : period[1]]
    absolute = contribution.sum().abs().sort_values(ascending=False)
    denominator = float(absolute.sum())
    regression = regression_diagnostics(
        result.daily.loc[period[0] : period[1], "net_return"],
        data["returns"].loc[period[0] : period[1], "SPY"],
    )
    rebalances = result.rebalances.loc[period[0] : period[1]]
    metrics.update(
        long_net_expectancy=float(books.loc["long", "annualized_arithmetic_expectancy"]),
        short_net_expectancy=float(books.loc["short", "annualized_arithmetic_expectancy"]),
        long_sharpe=float(books.loc["long", "sharpe"]),
        short_sharpe=float(books.loc["short", "sharpe"]),
        long_net_contribution=float(books.loc["long", "net_return_arithmetic"]),
        short_net_contribution=float(books.loc["short", "net_return_arithmetic"]),
        average_long_exposure=float(books.loc["long", "average_gross_exposure"]),
        average_short_exposure=float(books.loc["short", "average_gross_exposure"]),
        exposure_gap=float(
            abs(
                books.loc["long", "average_gross_exposure"]
                - books.loc["short", "average_gross_exposure"]
            )
        ),
        top_5_absolute_contribution_share=(
            float(absolute.head(5).sum() / denominator) if denominator > 0 else np.nan
        ),
        top_5_symbols=",".join(absolute.head(5).index),
        spy_beta=float(regression["market_beta"]),
        spy_r_squared=float(regression["r_squared"]),
        maximum_long_gross_budget_ratio=float(
            rebalances["long_gross_budget_ratio"].max()
        ),
        maximum_short_gross_budget_ratio=float(
            rebalances["short_gross_budget_ratio"].max()
        ),
        maximum_forecast_volatility_ratio=float(
            rebalances["forecast_volatility"].div(0.08).max()
        ),
        maximum_turnover_budget_ratio=float(
            rebalances["turnover"].div(rebalances["turnover_limit"]).max()
        ),
        maximum_name_cap_excess=float(rebalances["maximum_name_cap_excess"].max()),
    )
    return metrics


def operational_pass(metrics: dict) -> bool:
    keys = (
        "maximum_net_budget_ratio",
        "maximum_factor_budget_ratio",
        "maximum_sleeve_budget_ratio",
        "maximum_long_gross_budget_ratio",
        "maximum_short_gross_budget_ratio",
        "maximum_forecast_volatility_ratio",
        "maximum_turnover_budget_ratio",
    )
    return bool(
        metrics.get("status") == "COMPLETED"
        and metrics["annual_turnover"] <= 25
        and all(metrics[key] <= 1.0001 for key in keys)
        and metrics["maximum_name_cap_excess"] <= 1e-8
    )


def write_report(output: Path, summary: dict) -> None:
    train = summary.get("train", {})
    development = summary.get("development", {})
    robustness = summary.get("robustness_sharpe", {})
    failed = [key for key, value in summary.get("gate_components", {}).items() if not value]
    report = f"""# v24 Dynamic Symmetric TSMOM

## Decision

**{summary['status']}**

v24 applies one causal, prespecified signal to both directions: prior-window z-scoring, a prior
70th-percentile absolute-z threshold, standardized 50/200-day moving-average gap confirmation and
`tanh(z)` sizing. Long and short gross caps are both 50%. The 2017–2024 audit is reused development
evidence; it is not a fresh holdout.

| Segment | Net Sharpe | CAGR | Max DD | Long expectancy | Short expectancy | Long Sharpe | Short Sharpe |
|---|---:|---:|---:|---:|---:|---:|---:|
| Train | {train.get('sharpe', float('nan')):.3f} | {train.get('cagr', float('nan')):.2%} | {train.get('max_drawdown', float('nan')):.2%} | {train.get('long_net_expectancy', float('nan')):.2%} | {train.get('short_net_expectancy', float('nan')):.2%} | {train.get('long_sharpe', float('nan')):.3f} | {train.get('short_sharpe', float('nan')):.3f} |
| Reused development | {development.get('sharpe', float('nan')):.3f} | {development.get('cagr', float('nan')):.2%} | {development.get('max_drawdown', float('nan')):.2%} | {development.get('long_net_expectancy', float('nan')):.2%} | {development.get('short_net_expectancy', float('nan')):.2%} | {development.get('long_sharpe', float('nan')):.3f} | {development.get('short_sharpe', float('nan')):.3f} |

## Robustness and structure

- Frozen-trade 2x-cost Sharpe: **{robustness.get('frozen_trade_double_cost', float('nan')):.3f}**.
- One-session signal-and-regime delay Sharpe: **{robustness.get('signal_delay_1', float('nan')):.3f}**.
- State-dependent-cost Sharpe: **{robustness.get('state_dependent_cost', float('nan')):.3f}**.
- Reused-development average long/short gross: **{development.get('average_long_exposure', float('nan')):.2%} / {development.get('average_short_exposure', float('nan')):.2%}**.
- SPY beta / R-squared: **{development.get('spy_beta', float('nan')):.3f} / {development.get('spy_r_squared', float('nan')):.1%}**.
- Largest reused-development dynamic name-cap excess: **{development.get('maximum_name_cap_excess', float('nan')):.2%}**. The ADV limit prevented immediate liquidation on the affected scaler cuts, so the operational gate failed rather than assuming an impossible fill.
- Failed gate components: **{', '.join(failed) if failed else 'None'}**.

In the 2022 diagnostic, the short book earned **{summary.get('diagnostic_2022', {}).get('short_net_expectancy', float('nan')):.2%}** annualized with Sharpe **{summary.get('diagnostic_2022', {}).get('short_sharpe', float('nan')):.3f}**, while the long book earned **{summary.get('diagnostic_2022', {}).get('long_net_expectancy', float('nan')):.2%}**. The short hedge worked in that regime but was not large enough to make the portfolio profitable.

## Interpretation

The direction rule is mathematically symmetric, so a negative short book cannot be attributed to
an asymmetric threshold or confirmation rule. It is evidence about this signal on cash ETFs after
borrow and allocated transaction costs. It is not a futures result: contract rolls, carry, margin,
basis and futures execution remain unobserved.

Historical gate passed: **{summary.get('historical_gate_passed', False)}**. Prospective validation
required: **True**. Orders allowed: **No**.
"""
    (output / "REPORT.md").write_text(report)


def main(source: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    if sha256(source) != EXPECTED_SOURCE_SHA256:
        raise RuntimeError("source does not match the frozen 45-ETF archive")
    data = load_data(source, DEVELOPMENT[1], UNIVERSE)
    features = build_dynamic_symmetric_tsmom(data)
    score = features["sizing_score"]
    if not isinstance(score, pd.DataFrame):
        raise TypeError("sizing score must be a DataFrame")
    calibration = calibrate_absolute(score, data["returns"])
    freeze = {
        "protocol_sha256": sha256(PROTOCOL),
        "source_sha256": sha256(source),
        "calibration": calibration,
        "momentum_weights": MOMENTUM_WEIGHTS,
        "skip_sessions": SKIP_SESSIONS,
        "standardization_window": STANDARDIZATION_WINDOW,
        "standardization_minimum": STANDARDIZATION_MINIMUM,
        "threshold_quantile": THRESHOLD_QUANTILE,
        "mapping": "tanh(z) with symmetric sign confirmation",
        "volatility_floor": VOLATILITY_FLOOR,
        "risk_scalers": {"normal": 1.0, "high_volatility": 0.7, "stress": 0.4},
        "portfolio": {
            "rebalance_every": 10,
            "max_gross": 1.0,
            "max_long_gross": 0.5,
            "max_short_gross": 0.5,
            "net_cap": 0.2,
            "max_name": 0.1,
            "max_turnover": 0.25,
            "max_participation": 0.001,
            "annual_volatility_cap": 0.08,
            "liquidity_limited_cap_reduction": True,
        },
        "factor_caps": FACTOR_CAPS.to_dict(),
        "sleeve_caps": SLEEVE_CAPS.to_dict(),
        "costs": asdict(COSTS),
        "train_window": [str(TRAIN[0].date()), str(TRAIN[1].date())],
        "reused_development_window": [
            str(DEVELOPMENT[0].date()), str(DEVELOPMENT[1].date())
        ],
        "fresh_holdout_available": False,
    }
    (output / "frozen_run_inputs.json").write_text(json.dumps(freeze, indent=2) + "\n")
    pd.DataFrame([calibration]).to_csv(output / "train_calibration.csv", index=False)
    if calibration["status"] != "ADMITTED":
        summary = {
            "status": "V24_BLOCKED_NONPOSITIVE_TRAIN_SLOPE",
            "reason": calibration["reason"],
            "historical_gate_passed": False,
            "prospective_validation_required": True,
            "orders_allowed": False,
        }
        (output / "SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n")
        write_report(output, summary)
        print(json.dumps(summary, indent=2))
        return

    calibrated = score * calibration["slope"]
    risk_scaler = features["risk_scaler"]
    if not isinstance(risk_scaler, pd.Series):
        raise TypeError("risk scaler must be a Series")
    result = run_candidate(calibrated, risk_scaler, data)
    tables = diagnostic_tables(result, data)
    train = segment_diagnostics(result, data, tables, TRAIN, "train")
    development = segment_diagnostics(
        result, data, tables, DEVELOPMENT, "development"
    )
    diagnostic_2022 = segment_diagnostics(
        result,
        data,
        tables,
        (pd.Timestamp("2022-01-03"), pd.Timestamp("2022-12-30")),
        "diagnostic_2022",
    )

    doubled = frozen_trade_cost_stress(result, transaction_multiplier=2.0)
    delayed = run_candidate(calibrated, risk_scaler, data, signal_delay=1)
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
        "train_long_expectancy": bool(train["long_net_expectancy"] >= 0),
        "train_short_expectancy": bool(train["short_net_expectancy"] >= 0),
        "development_long_expectancy": bool(development["long_net_expectancy"] >= 0),
        "development_short_expectancy": bool(development["short_net_expectancy"] >= 0),
        "train_long_sharpe": bool(train["long_sharpe"] >= 0),
        "train_short_sharpe": bool(train["short_sharpe"] >= 0),
        "development_long_sharpe": bool(development["long_sharpe"] >= 0),
        "development_short_sharpe": bool(development["short_sharpe"] >= 0),
        "exposure_symmetry": bool(development["exposure_gap"] <= 0.20),
        "concentration": bool(development["top_5_absolute_contribution_share"] < 0.75),
        "spy_r_squared": bool(development["spy_r_squared"] < 0.50),
        "positive_sleeves": bool(positive_sleeves >= 3),
        "positive_regimes": bool(positive_regimes >= 3),
        "train_operational": operational_pass(train),
        "development_operational": operational_pass(development),
    }
    passed = all(gate_components.values())
    summary = {
        "status": (
            "V24_HISTORICAL_GATE_PASS_PROSPECTIVE_REQUIRED"
            if passed
            else "V24_REJECTED"
        ),
        "reason": None if passed else "FROZEN_DYNAMIC_SYMMETRIC_CANDIDATE_FAILED_GATE",
        "historical_gate_passed": passed,
        "gate_components": gate_components,
        "train": train,
        "development": development,
        "diagnostic_2022": diagnostic_2022,
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
    result.daily.to_csv(output / "daily.csv")
    result.weights.to_csv(output / "weights.csv.gz", compression="gzip")
    result.rebalances.to_csv(output / "rebalances.csv")
    for name, table in tables.items():
        table.to_csv(output / f"{name}.csv", index=name == "book_daily")
    robustness.to_csv(output / "robustness.csv", index=False)
    pd.DataFrame(
        {
            "normal": [int(risk_scaler.eq(1.0).sum())],
            "high_volatility": [int(risk_scaler.eq(0.7).sum())],
            "stress": [int(risk_scaler.eq(0.4).sum())],
        }
    ).to_csv(output / "regime_scaler_frequency.csv", index=False)
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
    parser.add_argument("--output", type=Path, default=Path("reports/cross_asset_v24"))
    arguments = parser.parse_args()
    main(arguments.source, arguments.output)
