"""Run the prespecified v20 locked short-book and execution-cost audit once."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from backtest.cross_asset import CrossAssetResult
from backtest.engine import performance_metrics
from scripts.cross_asset_v17_universe import UNIVERSE
from scripts.evaluate_cross_asset_v12 import TEST, TRAIN, VALIDATION, load_data
from scripts.evaluate_cross_asset_v13 import segment_metrics
from scripts.evaluate_cross_asset_v15 import calibrate_absolute
from scripts.evaluate_cross_asset_v19 import (
    build_defensive_tsmom,
    frozen_trade_cost_stress,
    run_one,
)
from scripts.evaluate_equity_v7 import sha256

PROTOCOL = Path("docs/MULTI_ASSET_PROTOCOL_V20.md")
V19_FREEZE = Path("reports/cross_asset_v19/frozen_run_inputs.json")
EXPECTED_SOURCE_SHA256 = "82347fef112a5f04dc2b5accf947f362eefe1a0a89f1c59bf143a369ab63e32e"
EXPECTED_CALIBRATION_SLOPE = 6.537825607487585e-06
EXPECTED_CALIBRATION_DIGEST = (
    "d59984125ff01d469e8b75ded4e674f6a8708b1f066b92d9ce8ef5a744ab9122"
)
TOLERANCE = 1e-10


def build_state_cost_multipliers(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Build causal volatility, liquidity and drawdown cost multipliers."""
    returns = data["returns"]
    close = data["close"]
    volume = data["volume"]

    market_volatility = returns["SPY"].rolling(20, min_periods=20).std() * np.sqrt(252)
    volatility_reference = market_volatility.rolling(252, min_periods=60).median()
    volatility_ratio = market_volatility.div(volatility_reference.where(volatility_reference.gt(0)))

    dollar_volume = close * volume
    volume_reference = dollar_volume.rolling(60, min_periods=60).median()
    relative_liquidity = dollar_volume.div(volume_reference.where(volume_reference.gt(0)))
    liquidity_ratio = relative_liquidity.median(axis=1, skipna=True)

    # A cost realized on session t belongs to a trade selected after session t-1.
    volatility_ratio = volatility_ratio.shift(1).replace([np.inf, -np.inf], np.nan).fillna(1.0)
    liquidity_ratio = liquidity_ratio.shift(1).replace([np.inf, -np.inf], np.nan).fillna(1.0)
    prior_close = close["SPY"].shift(1)
    prior_peak = close["SPY"].cummax().shift(1)
    drawdown = prior_close.div(prior_peak.where(prior_peak.gt(0))).sub(1).fillna(0.0)

    volatility_stress = volatility_ratio.clip(lower=1.0)
    liquidity_stress = liquidity_ratio.pow(-1).clip(lower=1.0)
    drawdown_stress = pd.Series(
        np.where(drawdown.le(-0.10), 1.5, 1.0), index=returns.index
    )
    transaction = (volatility_stress * liquidity_stress * drawdown_stress).clip(1.0, 4.0)
    borrow = (volatility_stress * drawdown_stress).clip(1.0, 3.0)
    return pd.DataFrame(
        {
            "volatility_ratio": volatility_ratio,
            "liquidity_ratio": liquidity_ratio,
            "prior_drawdown": drawdown,
            "transaction_multiplier": transaction,
            "borrow_multiplier": borrow,
        },
        index=returns.index,
    )


def reprice_state_dependent_costs(
    baseline: CrossAssetResult, multipliers: pd.DataFrame
) -> CrossAssetResult:
    """Reprice fixed holdings and trades with causal state-dependent costs."""
    required = {"transaction_multiplier", "borrow_multiplier"}
    if not required.issubset(multipliers.columns):
        raise ValueError("state multiplier columns are incomplete")
    aligned = multipliers.reindex(baseline.daily.index)
    if aligned[list(required)].isna().any().any():
        raise ValueError("state multipliers must cover every baseline session")
    if (
        not np.isfinite(aligned[list(required)].to_numpy()).all()
        or aligned[list(required)].lt(1).any().any()
    ):
        raise ValueError("state multipliers must be finite and at least one")

    daily = baseline.daily.copy()
    daily["transaction_cost"] *= aligned["transaction_multiplier"]
    daily["borrow_cost"] *= aligned["borrow_multiplier"]
    daily["net_return"] = (
        daily["gross_return"] - daily["transaction_cost"] - daily["borrow_cost"]
    )
    return CrossAssetResult(
        daily=daily,
        weights=baseline.weights.copy(),
        rebalances=baseline.rebalances.copy(),
        status=baseline.status,
        reason=baseline.reason,
    )


def long_short_daily_attribution(
    result: CrossAssetResult,
    returns: pd.DataFrame,
    *,
    baseline_net_return: pd.Series | None = None,
) -> pd.DataFrame:
    """Allocate gross return and realized costs to long and short books."""
    daily = result.daily.reindex(returns.index)
    weights = result.weights.reindex(index=returns.index, columns=returns.columns).fillna(0.0)
    aligned_returns = returns.reindex_like(weights).fillna(0.0)

    security_contribution = weights * aligned_returns
    long_gross = security_contribution.where(weights.gt(0), 0.0).sum(axis=1)
    short_gross = security_contribution.where(weights.lt(0), 0.0).sum(axis=1)

    prior_weight = weights.shift(1).fillna(0.0)
    prior_return = aligned_returns.shift(1).fillna(0.0)
    drift_net = daily["net_return"] if baseline_net_return is None else baseline_net_return
    prior_net = drift_net.reindex(returns.index).shift(1).fillna(0.0)
    pretrade = prior_weight.mul(1 + prior_return).div(1 + prior_net, axis=0)
    pretrade.iloc[0] = 0.0

    long_turnover = weights.clip(lower=0).sub(pretrade.clip(lower=0)).abs().sum(axis=1)
    short_turnover = weights.clip(upper=0).sub(pretrade.clip(upper=0)).abs().sum(axis=1)
    reconstructed_turnover = long_turnover + short_turnover
    turnover_error = reconstructed_turnover.sub(daily["turnover"]).abs().max()
    if not np.isfinite(turnover_error) or turnover_error > TOLERANCE:
        raise RuntimeError(f"book turnover does not reconcile: {turnover_error}")

    allocation_denominator = reconstructed_turnover.where(reconstructed_turnover.gt(0))
    long_share = long_turnover.div(allocation_denominator).fillna(0.0)
    short_share = short_turnover.div(allocation_denominator).fillna(0.0)
    long_transaction = daily["transaction_cost"] * long_share
    short_transaction = daily["transaction_cost"] * short_share

    attribution = pd.DataFrame(
        {
            "long_gross_return": long_gross,
            "short_gross_return": short_gross,
            "long_transaction_cost": long_transaction,
            "short_transaction_cost": short_transaction,
            "short_borrow_cost": daily["borrow_cost"],
            "long_net_return": long_gross - long_transaction,
            "short_net_return": short_gross - short_transaction - daily["borrow_cost"],
            "long_turnover": long_turnover,
            "short_turnover": short_turnover,
            "long_gross_exposure": weights.clip(lower=0).sum(axis=1),
            "short_gross_exposure": weights.clip(upper=0).abs().sum(axis=1),
        },
        index=returns.index,
    )
    reconciliation = attribution["long_net_return"].add(
        attribution["short_net_return"]
    ).sub(daily["net_return"])
    if reconciliation.abs().max() > TOLERANCE:
        raise RuntimeError("long/short net attribution does not reconcile")
    return attribution


def book_metrics(
    attribution: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    segment: str,
    cost_model: str,
) -> list[dict]:
    """Summarize standalone net expectancy for each book."""
    subset = attribution.loc[start:end]
    rows = []
    for book in ("long", "short"):
        net = subset[f"{book}_net_return"]
        metrics = performance_metrics(net)
        rows.append(
            {
                "segment": segment,
                "cost_model": cost_model,
                "book": book,
                "gross_return_contribution": float(subset[f"{book}_gross_return"].sum()),
                "transaction_cost": float(subset[f"{book}_transaction_cost"].sum()),
                "borrow_cost": (
                    float(subset["short_borrow_cost"].sum()) if book == "short" else 0.0
                ),
                "net_return_arithmetic": float(net.sum()),
                "annualized_arithmetic_expectancy": float(net.mean() * 252),
                "average_gross_exposure": float(subset[f"{book}_gross_exposure"].mean()),
                **metrics,
            }
        )
    return rows


def risk_budgets_pass(metrics: dict) -> bool:
    return bool(
        metrics.get("status") == "COMPLETED"
        and metrics["maximum_net_budget_ratio"] <= 1 + 1e-6
        and metrics["maximum_factor_budget_ratio"] <= 1 + 1e-6
        and metrics["maximum_sleeve_budget_ratio"] <= 1 + 1e-6
    )


def locked_portfolio_passes(
    baseline: dict, doubled: dict, state_cost: dict
) -> bool:
    return bool(
        baseline.get("status") == doubled.get("status") == state_cost.get("status") == "COMPLETED"
        and baseline["cagr"] > 0
        and baseline["sharpe"] > 0.50
        and baseline["max_drawdown"] >= -0.20
        and doubled["sharpe"] > 0
        and state_cost["sharpe"] > 0
        and risk_budgets_pass(baseline)
    )


def short_book_passes(table: pd.DataFrame) -> bool:
    baseline_short = table.loc[
        table["cost_model"].eq("baseline")
        & table["book"].eq("short")
        & table["segment"].isin(["train", "development", "locked_test"])
    ]
    return bool(
        len(baseline_short) == 3
        and baseline_short["annualized_arithmetic_expectancy"].gt(0).all()
        and baseline_short["sharpe"].gt(0).all()
    )


def multiplier_summary(multipliers: pd.DataFrame, start, end) -> list[dict]:
    subset = multipliers.loc[start:end]
    rows = []
    for name in ("transaction_multiplier", "borrow_multiplier"):
        rows.append(
            {
                "multiplier": name,
                "mean": float(subset[name].mean()),
                "p95": float(subset[name].quantile(0.95)),
                "maximum": float(subset[name].max()),
            }
        )
    return rows


def write_report(output: Path, summary: dict, evaluations: pd.DataFrame) -> None:
    metrics = evaluations.set_index("evaluation")

    def value(name: str, field: str, percent: bool = False) -> str:
        number = float(metrics.loc[name, field])
        return f"{number:.2%}" if percent else f"{number:.3f}"

    short = summary["short_book"]
    report = f"""# v20 Locked Execution and Short-Book Audit

## Decision

- Total portfolio: **{summary['portfolio_decision']}**
- Structural classification: **{summary['short_book_decision']}**
- Locked test evaluated exactly once: **Yes**
- Orders allowed: **No**

| Locked 2021–2024 evaluation | Net Sharpe | Net CAGR | Max drawdown |
|---|---:|---:|---:|
| Baseline frozen v19 | {value('locked_baseline', 'sharpe')} | {value('locked_baseline', 'cagr', True)} | {value('locked_baseline', 'max_drawdown', True)} |
| Frozen trades, 2x transaction cost | {value('locked_double_transaction', 'sharpe')} | {value('locked_double_transaction', 'cagr', True)} | {value('locked_double_transaction', 'max_drawdown', True)} |
| Frozen trades, state-dependent costs | {value('locked_state_cost', 'sharpe')} | {value('locked_state_cost', 'cagr', True)} | {value('locked_state_cost', 'max_drawdown', True)} |

## Short-book evidence

The baseline short book produced locked annualized arithmetic expectancy of
**{short['locked_annualized_expectancy']:.2%}** and Sharpe of
**{short['locked_sharpe']:.3f}** after allocated transaction costs and borrow. In 2022 alone its
net arithmetic contribution was **{short['year_2022_net_contribution']:.2%}** with Sharpe
**{short['year_2022_sharpe']:.3f}**.

The long and short books are evaluated as standalone contribution streams on the same portfolio
capital base. Their daily net returns reconcile exactly to total portfolio net return.

## State-dependent execution stress

The stress retains every baseline holding and trade. Transaction and borrow charges rise only when
lagged volatility, liquidity or drawdown conditions worsen. The locked average transaction-cost
multiplier was **{summary['state_cost']['transaction_mean']:.2f}x**, its 95th percentile was
**{summary['state_cost']['transaction_p95']:.2f}x**, and its maximum was
**{summary['state_cost']['transaction_max']:.2f}x**.

## Interpretation

The total-portfolio result and the short-book result are separate prespecified decisions. A
portfolio pass does not validate a symmetric long-short CTA claim. No parameter was changed after
the holdout was read, and this run cannot authorize paper or live orders.
"""
    (output / "REPORT.md").write_text(report)


def main(source: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    source_digest = sha256(source)
    if source_digest != EXPECTED_SOURCE_SHA256:
        raise RuntimeError("source hash does not match the frozen v19 archive")

    data = load_data(source, TEST[1], UNIVERSE)
    features = build_defensive_tsmom(data)
    calibration = calibrate_absolute(features["sizing_score"], data["returns"])
    if (
        calibration["digest"] != EXPECTED_CALIBRATION_DIGEST
        or not np.isclose(calibration["slope"], EXPECTED_CALIBRATION_SLOPE)
    ):
        raise RuntimeError("train calibration does not reproduce the v19 freeze")

    score = features["sizing_score"] * calibration["slope"]
    baseline = run_one(score, data)
    if baseline.status != "COMPLETED":
        raise RuntimeError(f"baseline failed: {baseline.reason}")
    doubled = frozen_trade_cost_stress(baseline, transaction_multiplier=2.0)
    state_multipliers = build_state_cost_multipliers(data)
    state_cost = reprice_state_dependent_costs(baseline, state_multipliers)

    evaluations = []
    for name, result in (
        ("train_baseline", baseline),
        ("development_baseline", baseline),
        ("locked_baseline", baseline),
        ("locked_double_transaction", doubled),
        ("locked_state_cost", state_cost),
    ):
        segment = TRAIN if name.startswith("train") else VALIDATION if name.startswith(
            "development"
        ) else TEST
        evaluations.append({"evaluation": name, **segment_metrics(result, *segment)})
    evaluation_table = pd.DataFrame(evaluations)
    evaluation_table.to_csv(output / "evaluation.csv", index=False)

    baseline_books = long_short_daily_attribution(baseline, data["returns"])
    state_books = long_short_daily_attribution(
        state_cost,
        data["returns"],
        baseline_net_return=baseline.daily["net_return"],
    )
    segment_map = {
        "train": TRAIN,
        "development": VALIDATION,
        "locked_test": TEST,
        "locked_2022": (pd.Timestamp("2022-01-03"), pd.Timestamp("2022-12-30")),
    }
    book_rows = []
    for cost_model, attribution in (
        ("baseline", baseline_books),
        ("state_dependent", state_books),
    ):
        for segment, (start, end) in segment_map.items():
            book_rows.extend(
                book_metrics(
                    attribution,
                    start,
                    end,
                    segment=segment,
                    cost_model=cost_model,
                )
            )
    book_table = pd.DataFrame(book_rows)
    book_table.to_csv(output / "book_metrics.csv", index=False)

    locked_daily = baseline.daily.loc[TEST[0] : TEST[1]]
    locked_daily.to_csv(output / "locked_baseline_daily.csv")
    state_cost.daily.loc[TEST[0] : TEST[1]].to_csv(output / "locked_state_cost_daily.csv")
    doubled.daily.loc[TEST[0] : TEST[1]].to_csv(
        output / "locked_double_transaction_daily.csv"
    )
    baseline.rebalances.loc[TEST[0] : TEST[1]].to_csv(output / "locked_rebalances.csv")
    baseline.weights.loc[TEST[0] : TEST[1]].to_csv(
        output / "locked_weights.csv.gz", compression="gzip"
    )
    baseline_books.loc[TEST[0] : TEST[1]].to_csv(output / "locked_book_daily.csv")
    state_multipliers.loc[TEST[0] : TEST[1]].to_csv(output / "locked_state_multipliers.csv")

    multiplier_table = pd.DataFrame(multiplier_summary(state_multipliers, *TEST))
    multiplier_table.to_csv(output / "state_multiplier_summary.csv", index=False)
    yearly = []
    for year, index in locked_daily.groupby(locked_daily.index.year).groups.items():
        row = {"year": int(year)}
        for label, series in (
            ("baseline", baseline.daily.loc[index, "net_return"]),
            ("state_cost", state_cost.daily.loc[index, "net_return"]),
        ):
            row.update({f"{label}_{key}": value for key, value in performance_metrics(series).items()})
        yearly.append(row)
    pd.DataFrame(yearly).to_csv(output / "locked_yearly.csv", index=False)

    metrics = evaluation_table.set_index("evaluation").to_dict("index")
    portfolio_pass = locked_portfolio_passes(
        metrics["locked_baseline"],
        metrics["locked_double_transaction"],
        metrics["locked_state_cost"],
    )
    short_pass = short_book_passes(book_table)
    short_locked = book_table.query(
        "segment == 'locked_test' and cost_model == 'baseline' and book == 'short'"
    ).iloc[0]
    short_2022 = book_table.query(
        "segment == 'locked_2022' and cost_model == 'baseline' and book == 'short'"
    ).iloc[0]
    multiplier_index = multiplier_table.set_index("multiplier")
    summary = {
        "status": "LOCKED_AUDIT_COMPLETE",
        "portfolio_decision": (
            "LOCKED_PORTFOLIO_PASS" if portfolio_pass else "LOCKED_PORTFOLIO_FAIL"
        ),
        "short_book_decision": (
            "SHORT_BOOK_VALIDATED" if short_pass else "LONG_DRIVEN_NOT_SYMMETRIC"
        ),
        "locked_test_evaluated": True,
        "locked_test_run_count": 1,
        "orders_allowed": False,
        "short_book": {
            "locked_annualized_expectancy": float(
                short_locked["annualized_arithmetic_expectancy"]
            ),
            "locked_sharpe": float(short_locked["sharpe"]),
            "year_2022_net_contribution": float(short_2022["net_return_arithmetic"]),
            "year_2022_sharpe": float(short_2022["sharpe"]),
        },
        "state_cost": {
            "transaction_mean": float(
                multiplier_index.loc["transaction_multiplier", "mean"]
            ),
            "transaction_p95": float(
                multiplier_index.loc["transaction_multiplier", "p95"]
            ),
            "transaction_max": float(
                multiplier_index.loc["transaction_multiplier", "maximum"]
            ),
        },
        "hashes": {
            "protocol_sha256": sha256(PROTOCOL),
            "source_sha256": source_digest,
            "evaluator_sha256": sha256(Path(__file__)),
            "v19_freeze_sha256": sha256(V19_FREEZE),
        },
    }
    (output / "SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n")
    write_report(output, summary, evaluation_table)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("output/cross_asset_etfs_v17/etf_daily.csv"),
    )
    parser.add_argument("--output", type=Path, default=Path("reports/cross_asset_v20"))
    arguments = parser.parse_args()
    main(arguments.source, arguments.output)
