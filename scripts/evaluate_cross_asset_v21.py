"""Run the prespecified v21 defensive long-biased TSMOM research matrix."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd

from backtest.cross_asset import CrossAssetResult
from backtest.cross_asset_budget import RiskBudgetConfig, run_risk_budget_backtest
from portfolio.optimizer import PortfolioCosts
from scripts.audit_v20_comment_claims import regression_diagnostics
from scripts.cross_asset_v17_universe import UNIVERSE, asset_sleeves, factor_loadings
from scripts.evaluate_cross_asset_v12 import TEST, TRAIN, VALIDATION, load_data
from scripts.evaluate_cross_asset_v13 import segment_metrics
from scripts.evaluate_cross_asset_v15 import calibrate_absolute
from scripts.evaluate_cross_asset_v19 import (
    COSTS,
    FACTOR_CAPS,
    SLEEVE_CAPS,
    build_defensive_tsmom,
    frozen_trade_cost_stress,
    normalized_loadings,
    run_one as run_v19,
)
from scripts.evaluate_cross_asset_v20 import (
    book_metrics,
    build_state_cost_multipliers,
    long_short_daily_attribution,
    reprice_state_dependent_costs,
)
from scripts.evaluate_equity_v7 import sha256

PROTOCOL = Path("docs/MULTI_ASSET_PROTOCOL_V21.md")
EXPECTED_SOURCE_SHA256 = "82347fef112a5f04dc2b5accf947f362eefe1a0a89f1c59bf143a369ab63e32e"
DEVELOPMENT = (VALIDATION[0], TEST[1])
MOMENTUM_WEIGHTS = {63: 0.25, 126: 0.35, 252: 0.40}
SKIP_SESSIONS = 21
VOLATILITY_WINDOW = 60
MOVING_AVERAGE_WINDOW = 200
LONG_THRESHOLD = 0.25


@dataclass(frozen=True)
class Candidate:
    name: str
    short_threshold: float
    fast_overlay: bool
    volatility_floor: float | None
    cash_fallback: bool
    short_gross_cap: float
    rates_sleeve_cap: float


CANDIDATES = (
    Candidate("A", -0.40, False, None, False, 0.35, 0.60),
    Candidate("B", -0.40, True, None, False, 0.35, 0.60),
    Candidate("C", -0.40, True, 0.08, False, 0.35, 0.60),
    Candidate("D", -0.40, True, 0.08, True, 0.35, 0.60),
    Candidate("E", -0.50, True, 0.08, True, 0.35, 0.60),
    Candidate("F", -0.40, True, 0.10, True, 0.35, 0.60),
    Candidate("G", -0.40, True, 0.08, True, 0.25, 0.60),
    Candidate("H", -0.40, True, 0.08, True, 0.35, 0.30),
)


def build_fast_overlay(data: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Build causal 1/.5/0 name multipliers from the frozen fast-risk rules."""
    close, returns = data["close"], data["returns"]
    realized_volatility = returns.rolling(20, min_periods=20).std() * np.sqrt(252)
    reference = realized_volatility.rolling(252, min_periods=60)
    p80 = reference.quantile(0.80).shift(1)
    p95 = reference.quantile(0.95).shift(1)
    drawdown = close.div(close.cummax()).sub(1)
    moving_average_50 = close.rolling(50, min_periods=50).mean()
    moving_average_200 = close.rolling(200, min_periods=200).mean()
    momentum_21 = close.pct_change(21, fill_method=None)

    moderate = (
        realized_volatility.gt(p80)
        | drawdown.lt(-0.10)
        | (moving_average_50.lt(moving_average_200) & momentum_21.lt(0))
    )
    extreme = drawdown.lt(-0.15) | realized_volatility.gt(p95)
    multiplier = pd.DataFrame(1.0, index=close.index, columns=close.columns)
    multiplier = multiplier.mask(moderate, 0.5).mask(extreme, 0.0)
    return {
        "multiplier": multiplier,
        "realized_volatility_20": realized_volatility,
        "volatility_p80": p80,
        "volatility_p95": p95,
        "drawdown": drawdown,
        "moderate": moderate,
        "extreme": extreme,
    }


def build_candidate_features(
    data: dict[str, pd.DataFrame], candidate: Candidate
) -> dict[str, pd.DataFrame]:
    """Build one frozen candidate without using forward prices or future thresholds."""
    close, returns, eligibility = data["close"], data["returns"], data["eligibility"]
    log_price = np.log(close)
    daily_volatility = returns.rolling(
        VOLATILITY_WINDOW, min_periods=VOLATILITY_WINDOW
    ).std().shift(1)
    standardized, raw_moves = {}, {}
    for horizon, weight in MOMENTUM_WEIGHTS.items():
        move = log_price.shift(SKIP_SESSIONS).sub(log_price.shift(horizon))
        raw_moves[horizon] = move
        standardized[horizon] = move.div(
            daily_volatility * np.sqrt(horizon - SKIP_SESSIONS)
        ) * weight
    composite = sum(standardized.values()).clip(-3, 3)
    moving_average = close.rolling(
        MOVING_AVERAGE_WINDOW, min_periods=MOVING_AVERAGE_WINDOW
    ).mean()
    negative_horizons = sum(move.lt(0).astype(int) for move in raw_moves.values())
    long_active = composite.gt(LONG_THRESHOLD) & close.gt(moving_average)
    short_active = (
        composite.lt(candidate.short_threshold)
        & close.lt(moving_average)
        & negative_horizons.ge(2)
    )
    active = (long_active | short_active) & eligibility
    signal = composite.where(long_active | short_active, 0.0).where(eligibility)

    annualized_volatility = daily_volatility * np.sqrt(252)
    cross_sectional_floor = annualized_volatility.median(axis=1, skipna=True).div(1.5)
    effective_volatility = annualized_volatility.copy()
    if candidate.volatility_floor is not None:
        effective_volatility = effective_volatility.clip(lower=candidate.volatility_floor)
        effective_volatility = effective_volatility.clip(
            lower=cross_sectional_floor, axis=0
        )

    overlay = build_fast_overlay(data)
    overlay_multiplier = (
        overlay["multiplier"]
        if candidate.fast_overlay
        else pd.DataFrame(1.0, index=close.index, columns=close.columns)
    )
    signal = signal * overlay_multiplier
    name_scaler = overlay_multiplier.copy()
    if candidate.cash_fallback:
        name_scaler = name_scaler.where(active, 0.0)
    name_scaler = name_scaler.where(eligibility, 0.0).fillna(0.0)
    sizing_score = signal.div(effective_volatility.where(effective_volatility.gt(0)))
    return {
        "composite": composite.where(eligibility),
        "signal": signal.where(eligibility),
        "long_active": long_active & eligibility,
        "short_active": short_active & eligibility,
        "negative_horizons": negative_horizons.where(eligibility),
        "annualized_volatility": annualized_volatility.where(eligibility),
        "effective_volatility": effective_volatility.where(eligibility),
        "overlay_multiplier": overlay_multiplier,
        "name_scaler": name_scaler,
        "sizing_score": sizing_score.where(eligibility),
    }


def run_candidate(
    score: pd.DataFrame,
    name_scaler: pd.DataFrame,
    data: dict,
    candidate: Candidate,
    *,
    signal_delay: int = 0,
    costs: PortfolioCosts = COSTS,
) -> CrossAssetResult:
    delayed_score = score.shift(signal_delay) if signal_delay else score
    delayed_scaler = name_scaler.shift(signal_delay).fillna(0.0) if signal_delay else name_scaler
    sleeve_caps = SLEEVE_CAPS.copy()
    sleeve_caps.loc["rates"] = candidate.rates_sleeve_cap
    config = RiskBudgetConfig(
        rebalance_every=10,
        max_gross=1.0,
        max_name=0.10,
        max_turnover=0.25,
        max_participation=0.001,
        annual_volatility_cap=0.08,
        net_cap=0.60,
        max_short_gross=candidate.short_gross_cap,
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
        sleeve_caps,
        name_scaler=delayed_scaler,
        config=config,
        costs=costs,
    )


def candidate_diagnostics(
    result: CrossAssetResult,
    data: dict,
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    segment: str,
) -> dict:
    """Return all prespecified selection and structural diagnostics for one segment."""
    metrics = segment_metrics(result, start, end)
    if metrics.get("status") != "COMPLETED":
        return metrics
    returns = data["returns"]
    book = long_short_daily_attribution(result, returns)
    books = pd.DataFrame(
        book_metrics(book, start, end, segment=segment, cost_model="baseline")
    ).set_index("book")
    weights = result.weights.reindex(index=returns.index, columns=returns.columns).fillna(0.0)
    contributions = weights * returns.fillna(0.0)
    subset = contributions.loc[start:end]
    asset_total = subset.sum()
    absolute = asset_total.abs().sort_values(ascending=False)
    absolute_total = float(absolute.sum())
    sleeves = asset_sleeves()
    sleeve_total = subset.T.groupby(sleeves).sum().T.sum()
    market = returns["SPY"].loc[start:end]
    beta = regression_diagnostics(result.daily["net_return"].loc[start:end], market)
    rebalances = result.rebalances.loc[start:end]
    metrics.update(
        long_contribution=float(books.loc["long", "net_return_arithmetic"]),
        short_contribution=float(books.loc["short", "net_return_arithmetic"]),
        short_annualized_expectancy=float(
            books.loc["short", "annualized_arithmetic_expectancy"]
        ),
        average_long_exposure=float(books.loc["long", "average_gross_exposure"]),
        average_short_exposure=float(books.loc["short", "average_gross_exposure"]),
        top_5_absolute_contribution_share=(
            float(absolute.head(5).sum() / absolute_total) if absolute_total > 0 else np.nan
        ),
        top_5_symbols=",".join(absolute.head(5).index),
        positive_sleeves=int(sleeve_total.gt(0).sum()),
        spy_beta=float(beta["market_beta"]),
        spy_r_squared=float(beta["r_squared"]),
        maximum_short_gross_budget_ratio=float(
            rebalances["short_gross_budget_ratio"].max()
        ),
        maximum_name_cap_excess=float(rebalances["maximum_name_cap_excess"].max()),
        maximum_gross_budget_ratio=float(rebalances["gross"].max()),
    )
    return metrics


def train_qualified(metrics: dict) -> bool:
    return bool(
        metrics.get("status") == "COMPLETED"
        and metrics["sharpe"] > 0.50
        and metrics["cagr"] > 0
        and metrics["max_drawdown"] >= -0.15
        and metrics["short_annualized_expectancy"] >= 0
        and metrics["positive_sleeves"] >= 3
        and metrics["top_5_absolute_contribution_share"] < 0.75
        and abs(metrics["spy_beta"]) < 0.20
        and metrics["spy_r_squared"] < 0.50
    )


def select_candidate(rows: list[dict]) -> str | None:
    qualified = [row for row in rows if row["segment"] == "train" and row["qualified"]]
    if not qualified:
        return None
    best = max(float(row["sharpe"]) for row in qualified)
    near_ties = [row["candidate"] for row in qualified if float(row["sharpe"]) >= best - 0.02]
    return min(near_ties)


def fixed_regime_table(result: CrossAssetResult) -> pd.DataFrame:
    periods = {
        "2017_2019": (pd.Timestamp("2017-01-03"), pd.Timestamp("2019-12-31")),
        "2020": (pd.Timestamp("2020-01-01"), pd.Timestamp("2020-12-31")),
        "2021_2022": (pd.Timestamp("2021-01-04"), pd.Timestamp("2022-12-30")),
        "2023_2024": (pd.Timestamp("2023-01-03"), pd.Timestamp("2024-12-31")),
    }
    return pd.DataFrame(
        [
            {
                "regime": name,
                "start": start.date().isoformat(),
                "end": end.date().isoformat(),
                "net_arithmetic_contribution": float(
                    result.daily.loc[start:end, "net_return"].sum()
                ),
            }
            for name, (start, end) in periods.items()
        ]
    )


def yearly_table(result: CrossAssetResult, book: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for year, daily in result.daily.loc[DEVELOPMENT[0] : DEVELOPMENT[1]].groupby(
        result.daily.loc[DEVELOPMENT[0] : DEVELOPMENT[1]].index.year
    ):
        subset = book.loc[daily.index]
        rows.append(
            {
                "year": int(year),
                "net_return_compounded": float((1 + daily["net_return"]).prod() - 1),
                "net_return_arithmetic": float(daily["net_return"].sum()),
                "long_net_contribution": float(subset["long_net_return"].sum()),
                "short_net_contribution": float(subset["short_net_return"].sum()),
                "transaction_cost": float(daily["transaction_cost"].sum()),
                "borrow_cost": float(daily["borrow_cost"].sum()),
            }
        )
    return pd.DataFrame(rows)


def sleeve_table(result: CrossAssetResult, data: dict) -> pd.DataFrame:
    weights = result.weights.reindex_like(data["returns"]).fillna(0.0)
    contribution = weights * data["returns"].fillna(0.0)
    sleeves = asset_sleeves()
    rows = []
    for segment, (start, end) in {"train": TRAIN, "development": DEVELOPMENT}.items():
        by_sleeve = contribution.loc[start:end].T.groupby(sleeves).sum().T
        for sleeve in sorted(sleeves.unique()):
            rows.append(
                {
                    "segment": segment,
                    "sleeve": sleeve,
                    "gross_return_contribution": float(by_sleeve[sleeve].sum()),
                }
            )
    return pd.DataFrame(rows)


def operational_pass(metrics: dict) -> bool:
    keys = (
        "maximum_net_budget_ratio",
        "maximum_factor_budget_ratio",
        "maximum_sleeve_budget_ratio",
        "maximum_short_gross_budget_ratio",
    )
    return bool(
        metrics.get("status") == "COMPLETED"
        and metrics["annual_turnover"] <= 25
        and all(metrics[key] <= 1.0001 for key in keys)
        and metrics["maximum_gross_budget_ratio"] <= 1.0001
        and metrics["maximum_name_cap_excess"] <= 1e-6
    )


def write_report(output: Path, summary: dict, matrix: pd.DataFrame) -> None:
    train = matrix.loc[matrix["segment"].eq("train")].set_index("candidate")
    development = matrix.loc[matrix["segment"].eq("development")].set_index("candidate")
    rows = []
    for name in train.index:
        rows.append(
            f"| {name} | {train.loc[name, 'sharpe']:.3f} | "
            f"{development.loc[name, 'sharpe']:.3f} | {development.loc[name, 'cagr']:.2%} | "
            f"{development.loc[name, 'max_drawdown']:.2%} | "
            f"{development.loc[name, 'short_annualized_expectancy']:.2%} | "
            f"{str(bool(train.loc[name, 'qualified']))} |"
        )
    selected = summary.get("selected_candidate") or "None"
    report = f"""# v21 Defensive Long-Biased TSMOM

## Decision

**{summary['status']}**

The protocol and eight-candidate matrix were frozen before execution. Candidate selection uses
2008–2016 only. The combined 2017–2024 period is explicitly reused development evidence, not a
fresh holdout. The 2022 result is diagnostic and cannot alter the selection.

| Candidate | Train Sharpe | Reused-dev Sharpe | Reused-dev CAGR | Reused-dev max DD | Short expectancy | Train qualified |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

Train-selected candidate: **{selected}**.

## Gate interpretation

- Historical research gate passed: **{summary['historical_gate_passed']}**.
- Prospective validation required: **{summary['prospective_validation_required']}**.
- Orders allowed: **No**.
- Selection used development data: **No**.

The structural gate requires the short book to have nonnegative standalone expectancy, at least
three positive sleeves, top-five contribution below 75%, controlled SPY dependence and positive
performance in at least three of four fixed regimes. Passing the historical gate would authorize
only a frozen prospective study. It would not establish an unbiased OOS result.
"""
    (output / "REPORT.md").write_text(report)


def main(source: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    if sha256(source) != EXPECTED_SOURCE_SHA256:
        raise RuntimeError("source does not match the frozen 45-ETF archive")
    data = load_data(source, DEVELOPMENT[1], UNIVERSE)
    candidate_rows, results, features_by_candidate, calibrations = [], {}, {}, {}

    for candidate in CANDIDATES:
        features = build_candidate_features(data, candidate)
        calibration = calibrate_absolute(features["sizing_score"], data["returns"])
        calibrations[candidate.name] = calibration
        features_by_candidate[candidate.name] = features
        if calibration["status"] != "ADMITTED":
            for segment in ("train", "development", "diagnostic_2022"):
                candidate_rows.append(
                    {
                        "candidate": candidate.name,
                        "segment": segment,
                        "status": "BLOCKED",
                        "reason": calibration["reason"],
                        "qualified": False,
                    }
                )
            continue
        score = features["sizing_score"] * calibration["slope"]
        result = run_candidate(score, features["name_scaler"], data, candidate)
        results[candidate.name] = result
        periods = {"train": TRAIN, "development": DEVELOPMENT,
                   "diagnostic_2022": (pd.Timestamp("2022-01-03"), pd.Timestamp("2022-12-30"))}
        for segment, (start, end) in periods.items():
            metrics = candidate_diagnostics(result, data, start, end, segment=segment)
            metrics["qualified"] = train_qualified(metrics) if segment == "train" else False
            candidate_rows.append({"candidate": candidate.name, "segment": segment, **metrics})

    selected = select_candidate(candidate_rows)
    matrix = pd.DataFrame(candidate_rows)
    matrix.to_csv(output / "candidate_metrics.csv", index=False)
    pd.DataFrame([asdict(candidate) for candidate in CANDIDATES]).to_csv(
        output / "candidate_matrix.csv", index=False
    )
    pd.DataFrame(
        [{"candidate": name, **calibration} for name, calibration in calibrations.items()]
    ).to_csv(output / "train_calibration.csv", index=False)

    control_features = build_defensive_tsmom(data)
    control_calibration = calibrate_absolute(control_features["sizing_score"], data["returns"])
    control = run_v19(control_features["sizing_score"] * control_calibration["slope"], data)
    pd.DataFrame(
        [
            {"segment": name, **segment_metrics(control, *period)}
            for name, period in {"train": TRAIN, "development": DEVELOPMENT}.items()
        ]
    ).to_csv(output / "v19_control_metrics.csv", index=False)

    freeze = {
        "protocol_sha256": sha256(PROTOCOL),
        "source_sha256": sha256(source),
        "candidates": [asdict(candidate) for candidate in CANDIDATES],
        "calibrations": calibrations,
        "portfolio_common": {
            "rebalance_every": 10,
            "max_gross": 1.0,
            "max_name": 0.10,
            "max_turnover": 0.25,
            "max_participation": 0.001,
            "annual_volatility_cap": 0.08,
            "net_cap": 0.60,
        },
        "costs": asdict(COSTS),
        "selection_window": [str(TRAIN[0].date()), str(TRAIN[1].date())],
        "reused_development_window": [
            str(DEVELOPMENT[0].date()), str(DEVELOPMENT[1].date())
        ],
        "fresh_holdout_available": False,
    }
    (output / "frozen_run_inputs.json").write_text(json.dumps(freeze, indent=2) + "\n")

    if selected is None:
        summary = {
            "status": "V21_REJECTED",
            "reason": "NO_CANDIDATE_PASSED_TRAIN_ONLY_SELECTION_GATE",
            "selected_candidate": None,
            "historical_gate_passed": False,
            "prospective_validation_required": True,
            "orders_allowed": False,
        }
        (output / "SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n")
        write_report(output, summary, matrix)
        print(json.dumps(summary, indent=2))
        return

    candidate = next(item for item in CANDIDATES if item.name == selected)
    result = results[selected]
    features = features_by_candidate[selected]
    score = features["sizing_score"] * calibrations[selected]["slope"]
    doubled = frozen_trade_cost_stress(result, transaction_multiplier=2.0)
    delayed = run_candidate(
        score, features["name_scaler"], data, candidate, signal_delay=1
    )
    state = reprice_state_dependent_costs(result, build_state_cost_multipliers(data))
    robustness = pd.DataFrame(
        [
            {"evaluation": "baseline", **segment_metrics(result, *DEVELOPMENT)},
            {"evaluation": "frozen_trade_double_cost", **segment_metrics(doubled, *DEVELOPMENT)},
            {"evaluation": "signal_delay_1", **segment_metrics(delayed, *DEVELOPMENT)},
            {"evaluation": "state_dependent_cost", **segment_metrics(state, *DEVELOPMENT)},
        ]
    )
    robustness.to_csv(output / "selected_robustness.csv", index=False)
    result.daily.to_csv(output / "selected_daily.csv")
    result.rebalances.to_csv(output / "selected_rebalances.csv")
    result.weights.to_csv(output / "selected_weights.csv.gz", compression="gzip")
    book = long_short_daily_attribution(result, data["returns"])
    book.to_csv(output / "selected_book_daily.csv")
    pd.DataFrame(
        book_metrics(book, *TRAIN, segment="train", cost_model="baseline")
        + book_metrics(book, *DEVELOPMENT, segment="development", cost_model="baseline")
    ).to_csv(output / "selected_book_metrics.csv", index=False)
    yearly_table(result, book).to_csv(output / "selected_yearly.csv", index=False)
    sleeves = sleeve_table(result, data)
    sleeves.to_csv(output / "selected_sleeve_attribution.csv", index=False)
    regimes = fixed_regime_table(result)
    regimes.to_csv(output / "selected_regime_attribution.csv", index=False)
    overlay = features["overlay_multiplier"].loc[DEVELOPMENT[0] : DEVELOPMENT[1]]
    pd.DataFrame(
        [
            {"state": "full", "asset_sessions": int(overlay.eq(1.0).sum().sum())},
            {"state": "half", "asset_sessions": int(overlay.eq(0.5).sum().sum())},
            {"state": "cash", "asset_sessions": int(overlay.eq(0.0).sum().sum())},
        ]
    ).to_csv(output / "selected_overlay_frequency.csv", index=False)

    selected_row = matrix.loc[
        matrix["candidate"].eq(selected) & matrix["segment"].eq("development")
    ].iloc[0]
    robust = robustness.set_index("evaluation")
    positive_regimes = int(regimes["net_arithmetic_contribution"].gt(0).sum())
    positive_sleeves = int(
        sleeves.query("segment == 'development'")["gross_return_contribution"].gt(0).sum()
    )
    gate_components = {
        "development_sharpe": bool(selected_row["sharpe"] > 0.50),
        "development_cagr": bool(selected_row["cagr"] > 0),
        "development_drawdown": bool(selected_row["max_drawdown"] >= -0.15),
        "double_cost": bool(robust.loc["frozen_trade_double_cost", "sharpe"] > 0),
        "signal_delay": bool(robust.loc["signal_delay_1", "sharpe"] > 0),
        "state_cost": bool(robust.loc["state_dependent_cost", "sharpe"] > 0),
        "concentration": bool(selected_row["top_5_absolute_contribution_share"] < 0.75),
        "short_expectancy": bool(selected_row["short_annualized_expectancy"] >= 0),
        "spy_r_squared": bool(selected_row["spy_r_squared"] < 0.50),
        "positive_sleeves": bool(positive_sleeves >= 3),
        "positive_regimes": bool(positive_regimes >= 3),
        "operational": operational_pass(selected_row.to_dict()),
    }
    passed = all(gate_components.values())
    summary = {
        "status": (
            "V21_HISTORICAL_GATE_PASS_PROSPECTIVE_REQUIRED" if passed else "V21_REJECTED"
        ),
        "reason": None if passed else "SELECTED_CANDIDATE_FAILED_HISTORICAL_GATE",
        "selected_candidate": selected,
        "historical_gate_passed": passed,
        "gate_components": gate_components,
        "positive_development_regimes": positive_regimes,
        "positive_development_sleeves": positive_sleeves,
        "prospective_validation_required": True,
        "orders_allowed": False,
    }
    (output / "SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n")
    write_report(output, summary, matrix)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source", type=Path,
        default=Path("output/cross_asset_etfs_v17/etf_daily.csv"),
    )
    parser.add_argument("--output", type=Path, default=Path("reports/cross_asset_v21"))
    arguments = parser.parse_args()
    main(arguments.source, arguments.output)
