"""Evaluate the frozen v22 ETF trend plus distribution-carry specification."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.cross_asset_v17_universe import UNIVERSE, asset_sleeves
from scripts.evaluate_cross_asset_v12 import TEST, TRAIN, VALIDATION, load_data
from scripts.evaluate_cross_asset_v13 import segment_metrics
from scripts.evaluate_cross_asset_v15 import calibrate_absolute
from scripts.evaluate_cross_asset_v19 import COSTS, frozen_trade_cost_stress
from scripts.evaluate_cross_asset_v20 import (
    book_metrics,
    build_state_cost_multipliers,
    long_short_daily_attribution,
    reprice_state_dependent_costs,
)
from scripts.evaluate_cross_asset_v21 import (
    CANDIDATES,
    candidate_diagnostics,
    fixed_regime_table,
    operational_pass,
    build_candidate_features,
    run_candidate,
    sleeve_table,
    yearly_table,
)
from scripts.evaluate_equity_v7 import sha256

PROTOCOL = Path("docs/MULTI_ASSET_PROTOCOL_V22.md")
EXPECTED_SOURCE_SHA256 = "82347fef112a5f04dc2b5accf947f362eefe1a0a89f1c59bf143a369ab63e32e"
DEVELOPMENT = (VALIDATION[0], TEST[1])
TREND_WEIGHT = 0.70
CARRY_WEIGHT = 0.30
MAX_EVENT_YIELD = 0.25
V21_D = CANDIDATES[3]


def build_distribution_carry(
    source: Path, data: dict[str, pd.DataFrame]
) -> dict[str, pd.DataFrame]:
    """Build a causal ETF cash-distribution carry proxy and its audit fields."""
    raw = pd.read_csv(
        source,
        usecols=["symbol", "date", "close", "dividends", "capital_gains"],
        parse_dates=["date"],
    )
    raw = raw.loc[
        raw["symbol"].isin(UNIVERSE) & raw["date"].le(DEVELOPMENT[1])
    ].copy()
    index, columns = data["close"].index, data["close"].columns

    def pivot(field: str) -> pd.DataFrame:
        return raw.pivot(index="date", columns="symbol", values=field).reindex(
            index=index, columns=columns
        )

    close = pivot("close")
    cash_distribution = pivot("dividends").fillna(0.0) + pivot("capital_gains").fillna(0.0)
    event_yield_raw = cash_distribution.div(close.shift(1).where(close.shift(1).gt(0)))
    rejected = event_yield_raw.lt(0) | event_yield_raw.gt(MAX_EVENT_YIELD)
    event_yield = event_yield_raw.mask(rejected).clip(lower=0.0)
    trailing_yield = event_yield.rolling(252, min_periods=252).sum()

    score = pd.DataFrame(np.nan, index=index, columns=columns)
    sleeves = asset_sleeves()
    for sleeve in sorted(sleeves.unique()):
        names = sleeves.index[sleeves.eq(sleeve)]
        usable = trailing_yield[names].where(data["eligibility"][names])
        ranks = usable.rank(axis=1, method="average", pct=True)
        centered = ranks.sub(ranks.mean(axis=1), axis=0) * 2.0
        score.loc[:, names] = centered.where(usable.notna().sum(axis=1).ge(3), axis=0)

    annualized_volatility = (
        data["returns"].rolling(60, min_periods=60).std().shift(1) * np.sqrt(252)
    )
    sizing_score = score.div(annualized_volatility.where(annualized_volatility.gt(0)))
    sizing_score = sizing_score.where(data["eligibility"])
    return {
        "cash_distribution": cash_distribution,
        "event_yield_raw": event_yield_raw,
        "rejected_event": rejected,
        "event_yield": event_yield,
        "trailing_yield": trailing_yield,
        "carry_score": score.where(data["eligibility"]),
        "sizing_score": sizing_score,
    }


def distribution_quality(
    fields: dict[str, pd.DataFrame], data: dict[str, pd.DataFrame]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    sleeves = asset_sleeves()
    asset_rows = []
    for symbol in data["close"].columns:
        events = fields["cash_distribution"][symbol].gt(0)
        rejected = fields["rejected_event"][symbol]
        asset_rows.append(
            {
                "symbol": symbol,
                "sleeve": sleeves[symbol],
                "positive_distribution_events": int(events.sum()),
                "rejected_events": int(rejected.sum()),
                "latest_trailing_distribution_yield": float(
                    fields["trailing_yield"][symbol].dropna().iloc[-1]
                ) if fields["trailing_yield"][symbol].notna().any() else np.nan,
                "carry_score_sessions": int(fields["sizing_score"][symbol].notna().sum()),
            }
        )
    assets = pd.DataFrame(asset_rows)
    sleeve_rows = []
    for sleeve, subset in assets.groupby("sleeve"):
        names = subset["symbol"].tolist()
        available = fields["sizing_score"][names].notna().sum(axis=1).ge(3)
        sleeve_rows.append(
            {
                "sleeve": sleeve,
                "assets": len(names),
                "assets_with_distributions": int(
                    subset["positive_distribution_events"].gt(0).sum()
                ),
                "positive_distribution_events": int(
                    subset["positive_distribution_events"].sum()
                ),
                "rejected_events": int(subset["rejected_events"].sum()),
                "sessions_with_carry_cross_section": int(available.sum()),
            }
        )
    return assets, pd.DataFrame(sleeve_rows)


def blend_expected_returns(
    trend_score: pd.DataFrame,
    carry_score: pd.DataFrame,
    trend_slope: float,
    carry_slope: float,
) -> pd.DataFrame:
    return TREND_WEIGHT * trend_score * trend_slope + CARRY_WEIGHT * carry_score * carry_slope


def asset_table(result, data: dict) -> pd.DataFrame:
    weights = result.weights.reindex_like(data["returns"]).fillna(0.0)
    contribution = weights * data["returns"].fillna(0.0)
    sleeves = asset_sleeves()
    rows = []
    for segment, (start, end) in {"train": TRAIN, "development": DEVELOPMENT}.items():
        total = contribution.loc[start:end].sum()
        for symbol in total.index:
            rows.append(
                {
                    "segment": segment,
                    "symbol": symbol,
                    "sleeve": sleeves[symbol],
                    "gross_return_contribution": float(total[symbol]),
                    "average_absolute_weight": float(weights.loc[start:end, symbol].abs().mean()),
                }
            )
    return pd.DataFrame(rows)


def write_report(output: Path, summary: dict, evaluation: pd.DataFrame) -> None:
    metrics = evaluation.set_index("segment")

    def value(segment: str, field: str, percent: bool = False) -> str:
        number = float(metrics.loc[segment, field])
        return f"{number:.2%}" if percent else f"{number:.3f}"

    failed = [name for name, passed in summary.get("gate_components", {}).items() if not passed]
    report = f"""# v22 ETF Trend + Distribution-Carry

## Decision

**{summary['status']}**

The carry input is trailing cash distributions reported in the ETF archive. It is a distinct
observable from price trend, but it is only an ETF distribution-carry proxy. This report makes no
claim about futures curve, basis or roll carry.

| Segment | Net Sharpe | Net CAGR | Max drawdown | Short expectancy | Annual turnover |
|---|---:|---:|---:|---:|---:|
| Train 2008–2016 | {value('train', 'sharpe')} | {value('train', 'cagr', True)} | {value('train', 'max_drawdown', True)} | {value('train', 'short_annualized_expectancy', True)} | {value('train', 'annual_turnover')} |
| Reused development 2017–2024 | {value('development', 'sharpe')} | {value('development', 'cagr', True)} | {value('development', 'max_drawdown', True)} | {value('development', 'short_annualized_expectancy', True)} | {value('development', 'annual_turnover')} |
| 2022 diagnostic | {value('diagnostic_2022', 'sharpe')} | {value('diagnostic_2022', 'cagr', True)} | {value('diagnostic_2022', 'max_drawdown', True)} | {value('diagnostic_2022', 'short_annualized_expectancy', True)} | {value('diagnostic_2022', 'annual_turnover')} |

## Calibration and robustness

- Train trend slope: **{summary['calibration']['trend']['slope']:.8f}**.
- Train distribution-carry slope: **{summary['calibration']['carry']['slope']:.8f}**.
- Frozen 2x transaction-cost development Sharpe:
  **{summary['robustness_sharpe']['frozen_trade_double_cost']:.3f}**.
- One-session-delay development Sharpe: **{summary['robustness_sharpe']['signal_delay_1']:.3f}**.
- State-dependent-cost development Sharpe:
  **{summary['robustness_sharpe']['state_dependent_cost']:.3f}**.
- Failed gate components: **{', '.join(failed) if failed else 'none'}**.

## Interpretation

Historical research gate passed: **{summary['historical_gate_passed']}**. Orders allowed: **No**.
The entire 2017–2024 window is reused evidence. A positive historical gate would still require a
new prospective period. A rejection advances the project to the futures-native data gate without
changing the 70/30 blend after seeing these results.
"""
    (output / "REPORT.md").write_text(report)


def main(source: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    if sha256(source) != EXPECTED_SOURCE_SHA256:
        raise RuntimeError("source does not match the frozen 45-ETF archive")
    data = load_data(source, DEVELOPMENT[1], UNIVERSE)
    trend = build_candidate_features(data, V21_D)
    carry = build_distribution_carry(source, data)
    asset_quality, sleeve_quality = distribution_quality(carry, data)
    asset_quality.to_csv(output / "distribution_quality_by_asset.csv", index=False)
    sleeve_quality.to_csv(output / "distribution_quality_by_sleeve.csv", index=False)

    calibrations = {
        "trend": calibrate_absolute(trend["sizing_score"], data["returns"]),
        "carry": calibrate_absolute(carry["sizing_score"], data["returns"]),
    }
    pd.DataFrame(
        [{"family": name, **artifact} for name, artifact in calibrations.items()]
    ).to_csv(output / "train_calibration.csv", index=False)
    if any(artifact["status"] != "ADMITTED" for artifact in calibrations.values()):
        summary = {
            "status": "V22_REJECTED",
            "reason": "NONPOSITIVE_TRAIN_FAMILY_CALIBRATION",
            "calibration": calibrations,
            "historical_gate_passed": False,
            "prospective_validation_required": True,
            "orders_allowed": False,
        }
        (output / "SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n")
        (output / "REPORT.md").write_text(
            "# v22 ETF Trend + Distribution-Carry\n\n**V22_REJECTED**\n\n"
            "At least one prespecified family had a nonpositive train-only calibration slope. "
            "The signal was not reversed and no portfolio was evaluated.\n"
        )
        print(json.dumps(summary, indent=2))
        return

    expected_return = blend_expected_returns(
        trend["sizing_score"], carry["sizing_score"],
        calibrations["trend"]["slope"], calibrations["carry"]["slope"],
    )
    name_scaler = trend["overlay_multiplier"].where(data["eligibility"], 0.0).fillna(0.0)
    baseline = run_candidate(expected_return, name_scaler, data, V21_D)
    doubled = frozen_trade_cost_stress(baseline, transaction_multiplier=2.0)
    delayed = run_candidate(expected_return, name_scaler, data, V21_D, signal_delay=1)
    state = reprice_state_dependent_costs(baseline, build_state_cost_multipliers(data))

    periods = {
        "train": TRAIN,
        "development": DEVELOPMENT,
        "diagnostic_2022": (pd.Timestamp("2022-01-03"), pd.Timestamp("2022-12-30")),
    }
    rows = []
    for segment, (start, end) in periods.items():
        rows.append(
            {"segment": segment, **candidate_diagnostics(
                baseline, data, start, end, segment=segment
            )}
        )
    evaluation = pd.DataFrame(rows)
    evaluation.to_csv(output / "evaluation.csv", index=False)
    robustness = pd.DataFrame(
        [
            {"evaluation": "baseline", **segment_metrics(baseline, *DEVELOPMENT)},
            {"evaluation": "frozen_trade_double_cost", **segment_metrics(doubled, *DEVELOPMENT)},
            {"evaluation": "signal_delay_1", **segment_metrics(delayed, *DEVELOPMENT)},
            {"evaluation": "state_dependent_cost", **segment_metrics(state, *DEVELOPMENT)},
        ]
    )
    robustness.to_csv(output / "robustness.csv", index=False)
    baseline.daily.to_csv(output / "baseline_daily.csv")
    baseline.rebalances.to_csv(output / "baseline_rebalances.csv")
    baseline.weights.to_csv(output / "baseline_weights.csv.gz", compression="gzip")
    book = long_short_daily_attribution(baseline, data["returns"])
    book.to_csv(output / "book_daily.csv")
    pd.DataFrame(
        book_metrics(book, *TRAIN, segment="train", cost_model="baseline")
        + book_metrics(book, *DEVELOPMENT, segment="development", cost_model="baseline")
    ).to_csv(output / "book_metrics.csv", index=False)
    yearly_table(baseline, book).to_csv(output / "yearly_attribution.csv", index=False)
    sleeve = sleeve_table(baseline, data)
    sleeve.to_csv(output / "sleeve_attribution.csv", index=False)
    asset_table(baseline, data).to_csv(output / "asset_attribution.csv", index=False)
    regimes = fixed_regime_table(baseline)
    regimes.to_csv(output / "regime_attribution.csv", index=False)

    development = evaluation.set_index("segment").loc["development"]
    robust = robustness.set_index("evaluation")
    positive_sleeves = int(
        sleeve.query("segment == 'development'")["gross_return_contribution"].gt(0).sum()
    )
    positive_regimes = int(regimes["net_arithmetic_contribution"].gt(0).sum())
    gate_components = {
        "development_sharpe": bool(development["sharpe"] > 0.50),
        "development_cagr": bool(development["cagr"] > 0),
        "development_drawdown": bool(development["max_drawdown"] >= -0.15),
        "double_cost": bool(robust.loc["frozen_trade_double_cost", "sharpe"] > 0),
        "signal_delay": bool(robust.loc["signal_delay_1", "sharpe"] > 0),
        "state_cost": bool(robust.loc["state_dependent_cost", "sharpe"] > 0),
        "short_expectancy": bool(development["short_annualized_expectancy"] >= 0),
        "concentration": bool(development["top_5_absolute_contribution_share"] < 0.75),
        "spy_r_squared": bool(development["spy_r_squared"] < 0.50),
        "positive_sleeves": bool(positive_sleeves >= 3),
        "positive_regimes": bool(positive_regimes >= 3),
        "operational": operational_pass(development.to_dict()),
    }
    passed = all(gate_components.values())
    freeze = {
        "protocol_sha256": sha256(PROTOCOL),
        "source_sha256": sha256(source),
        "trend_weight": TREND_WEIGHT,
        "carry_weight": CARRY_WEIGHT,
        "carry_definition": "trailing_252_session_cash_distribution_yield_within_sleeve",
        "calibrations": calibrations,
        "base_candidate": asdict(V21_D),
        "costs": asdict(COSTS),
        "development_reused": True,
        "fresh_holdout_available": False,
    }
    (output / "frozen_run_inputs.json").write_text(json.dumps(freeze, indent=2) + "\n")
    summary = {
        "status": (
            "V22_HISTORICAL_GATE_PASS_PROSPECTIVE_REQUIRED" if passed else "V22_REJECTED"
        ),
        "reason": None if passed else "TREND_CARRY_FAILED_HISTORICAL_GATE",
        "historical_gate_passed": passed,
        "gate_components": gate_components,
        "calibration": calibrations,
        "robustness_sharpe": {
            name: float(robust.loc[name, "sharpe"])
            for name in (
                "frozen_trade_double_cost", "signal_delay_1", "state_dependent_cost"
            )
        },
        "positive_development_sleeves": positive_sleeves,
        "positive_development_regimes": positive_regimes,
        "prospective_validation_required": True,
        "orders_allowed": False,
    }
    (output / "SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n")
    write_report(output, summary, evaluation)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source", type=Path,
        default=Path("output/cross_asset_etfs_v17/etf_daily.csv"),
    )
    parser.add_argument("--output", type=Path, default=Path("reports/cross_asset_v22"))
    arguments = parser.parse_args()
    main(arguments.source, arguments.output)
