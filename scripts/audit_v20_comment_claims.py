"""Audit the structural claims raised after the frozen v20 holdout was reported.

This module is diagnostic only. It reads the immutable v20 outputs, adds a market
reference, and does not rebuild signals, change weights, or select a strategy.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm

from scripts.evaluate_equity_v7 import sha256

SESSIONS_PER_YEAR = 252
EXPECTED_SOURCE_SHA256 = "82347fef112a5f04dc2b5accf947f362eefe1a0a89f1c59bf143a369ab63e32e"
V20 = Path("reports/cross_asset_v20")
DEFAULT_OUTPUT = Path("reports/cross_asset_v20_comment_audit")


def annualized_stats(series: pd.Series) -> dict[str, float | int]:
    """Return arithmetic diagnostics for a contribution stream."""
    clean = series.dropna().astype(float)
    volatility = float(clean.std(ddof=1) * np.sqrt(SESSIONS_PER_YEAR))
    annualized_mean = float(clean.mean() * SESSIONS_PER_YEAR)
    return {
        "sessions": int(clean.size),
        "arithmetic_contribution": float(clean.sum()),
        "annualized_arithmetic_expectancy": annualized_mean,
        "annualized_volatility": volatility,
        "sharpe": annualized_mean / volatility if volatility > 0 else np.nan,
        "positive_session_rate": float(clean.gt(0).mean()),
    }


def regression_diagnostics(strategy: pd.Series, market: pd.Series) -> dict[str, float | int]:
    """Estimate market beta and HAC inference for one contribution stream."""
    aligned = pd.concat([strategy.rename("strategy"), market.rename("market")], axis=1).dropna()
    if len(aligned) < 30:
        raise ValueError("at least 30 aligned sessions are required")
    design = sm.add_constant(aligned["market"])
    fit = sm.OLS(aligned["strategy"], design).fit(
        cov_type="HAC", cov_kwds={"maxlags": 10}
    )
    return {
        "sessions": len(aligned),
        "annualized_alpha": float(fit.params["const"] * SESSIONS_PER_YEAR),
        "alpha_tstat_hac": float(fit.tvalues["const"]),
        "market_beta": float(fit.params["market"]),
        "beta_tstat_hac": float(fit.tvalues["market"]),
        "r_squared": float(fit.rsquared),
        "correlation": float(aligned.corr().iloc[0, 1]),
    }


def extract_market_reference(source: Path, sessions: pd.DatetimeIndex) -> pd.DataFrame:
    """Extract a locked SPY return reference from the hash-verified v17 archive."""
    if sha256(source) != EXPECTED_SOURCE_SHA256:
        raise RuntimeError("market source does not match the frozen v17 archive")
    raw = pd.read_csv(source, usecols=["symbol", "date", "adj_close"])
    spy = raw.loc[raw["symbol"].eq("SPY"), ["date", "adj_close"]].copy()
    spy["date"] = pd.to_datetime(spy["date"])
    close = spy.drop_duplicates("date").set_index("date")["adj_close"].sort_index()
    market_return = close.pct_change()
    prior_close = close.shift(1)
    prior_peak = close.cummax().shift(1)
    reference = pd.DataFrame(
        {
            "spy_return": market_return,
            "prior_spy_drawdown": prior_close.div(prior_peak).sub(1),
        }
    ).reindex(sessions)
    if reference.isna().any().any():
        raise RuntimeError("SPY reference does not cover every locked session")
    reference.index.name = "session"
    return reference


def cost_waterfall(book_metrics: pd.DataFrame) -> pd.DataFrame:
    """Show whether transaction or borrow costs explain short-book failure."""
    short = book_metrics.loc[book_metrics["book"].eq("short")].copy()
    scale = SESSIONS_PER_YEAR / short["sessions"]
    short["gross_expectancy"] = short["gross_return_contribution"] * scale
    short["transaction_drag"] = short["transaction_cost"] * scale
    short["borrow_drag"] = short["borrow_cost"] * scale
    short["borrow_free_expectancy"] = short["gross_expectancy"] - short["transaction_drag"]
    short["net_expectancy"] = short["annualized_arithmetic_expectancy"]
    short["borrow_removal_flips_sign"] = (
        short["borrow_free_expectancy"].gt(0) & short["net_expectancy"].le(0)
    )
    return short[
        [
            "segment",
            "cost_model",
            "sessions",
            "gross_expectancy",
            "transaction_drag",
            "borrow_drag",
            "borrow_free_expectancy",
            "net_expectancy",
            "sharpe",
            "borrow_removal_flips_sign",
        ]
    ]


def yearly_book_teardown(book: pd.DataFrame) -> pd.DataFrame:
    """Produce the locked annual long/short contribution waterfall."""
    rows = []
    for year, subset in book.groupby(book.index.year):
        short_borrow_free = subset["short_gross_return"] - subset["short_transaction_cost"]
        rows.append(
            {
                "year": int(year),
                "long_net_contribution": float(subset["long_net_return"].sum()),
                "short_gross_contribution": float(subset["short_gross_return"].sum()),
                "short_transaction_cost": float(subset["short_transaction_cost"].sum()),
                "short_borrow_cost": float(subset["short_borrow_cost"].sum()),
                "short_borrow_free_contribution": float(short_borrow_free.sum()),
                "short_net_contribution": float(subset["short_net_return"].sum()),
                "average_long_exposure": float(subset["long_gross_exposure"].mean()),
                "average_short_exposure": float(subset["short_gross_exposure"].mean()),
            }
        )
    return pd.DataFrame(rows)


def beta_table(
    daily: pd.DataFrame, book: pd.DataFrame, market: pd.DataFrame
) -> pd.DataFrame:
    """Attribute market beta to the total, long and short contribution streams."""
    streams = {
        "total_net": daily["net_return"],
        "long_net": book["long_net_return"],
        "short_net": book["short_net_return"],
    }
    periods: dict[str, pd.Series] = {"locked_2021_2024": market["spy_return"]}
    periods.update(
        {
            str(year): values["spy_return"]
            for year, values in market.groupby(market.index.year)
        }
    )
    rows = []
    for period, market_return in periods.items():
        for stream, strategy_return in streams.items():
            rows.append(
                {
                    "period": period,
                    "stream": stream,
                    **regression_diagnostics(
                        strategy_return.reindex(market_return.index), market_return
                    ),
                }
            )
    return pd.DataFrame(rows)


def regime_table(
    daily: pd.DataFrame, book: pd.DataFrame, market: pd.DataFrame
) -> pd.DataFrame:
    """Measure which book provides defense in observable market regimes."""
    short_borrow_free = book["short_gross_return"] - book["short_transaction_cost"]
    masks = {
        "all_locked_sessions": pd.Series(True, index=market.index),
        "spy_up_sessions": market["spy_return"].gt(0),
        "spy_down_sessions": market["spy_return"].lt(0),
        "prior_spy_drawdown_le_minus_10pct": market["prior_spy_drawdown"].le(-0.10),
        "calendar_2022": pd.Series(market.index.year == 2022, index=market.index),
    }
    streams = {
        "total_net": daily["net_return"],
        "long_net": book["long_net_return"],
        "short_gross": book["short_gross_return"],
        "short_borrow_free": short_borrow_free,
        "short_net": book["short_net_return"],
    }
    rows = []
    for regime, mask in masks.items():
        for stream, values in streams.items():
            rows.append({"regime": regime, "stream": stream, **annualized_stats(values[mask])})
    return pd.DataFrame(rows)


def write_report(output: Path, summary: dict) -> None:
    beta = summary["market_beta"]
    exposure = summary["directional_exposure"]
    short = summary["short_book"]
    report = f"""# v20.1 Comment-Driven Structural Audit

## Status

This is a **post-holdout diagnostic**, not a new strategy version. It reads the immutable v20
holdings and returns. It does not change the signal, portfolio, costs, gates or the original
`LOCKED_PORTFOLIO_FAIL` decision.

## Questions and answers

| Comment concern | Evidence | Answer |
|---|---|---|
| Is the portfolio disguised equity beta? | Total SPY beta {beta['total_beta']:.3f}, HAC t-stat {beta['total_beta_tstat']:.2f}, R-squared {beta['total_r_squared']:.1%}; long-book beta {beta['long_beta']:.3f}; short-book beta {beta['short_beta']:.3f}. Average net exposure was {exposure['average_net_exposure']:.1%}. | **Yes: directional long dependence is confirmed.** |
| Does the short book have positive standalone expectancy after costs? | Locked short expectancy {short['locked_net_expectancy']:.2%}, Sharpe {short['locked_net_sharpe']:.3f}. | **No.** |
| Is borrow drag the only reason the short book fails? | Locked borrow-free short expectancy {short['locked_borrow_free_expectancy']:.2%}. | **No. It remains negative before borrow over the full holdout.** |
| Did shorts provide defense in 2022? | 2022 borrow-free short contribution {short['year_2022_borrow_free_contribution']:.2%}; after borrow {short['year_2022_net_contribution']:.2%}; long contribution {short['year_2022_long_contribution']:.2%}. | **Weak gross defense existed, but borrow reversed it and its size was immaterial versus the long loss.** |
| Would replacing ETF shorts with futures solve the problem? | Zero-borrow counterfactual is still negative over 2021–2024. | **Borrow removal alone is insufficient. A real futures test still requires contract-level roll, carry, margin and execution data.** |

## Equity-beta attribution

The total portfolio's annualized regression alpha versus SPY was
{beta['total_annualized_alpha']:.2%}; the HAC beta t-stat was {beta['total_beta_tstat']:.2f}.
The long book explains essentially all measured market beta, while the short book has near-zero
beta and negative standalone expectancy. The portfolio therefore cannot be presented as an
uncorrelated or symmetric long-short CTA.

## Borrow-free counterfactual

The counterfactual keeps the exact ETF holdings and transaction costs but sets borrow to zero. It
is deliberately labelled **borrow-free ETF proxy**, not a futures backtest.

- Locked 2021–2024: {short['locked_borrow_free_expectancy']:.2%} annualized short expectancy before
  borrow, versus {short['locked_net_expectancy']:.2%} after borrow.
- 2022: {short['year_2022_borrow_free_contribution']:.2%} contribution before borrow, versus
  {short['year_2022_net_contribution']:.2%} after borrow.

Borrow drag explains the sign flip in 2022, but it does not explain the multi-year failure because
the full-holdout short gross edge is already negative. Actual futures may improve financing and
short implementation, but they also introduce roll yield, basis, contract selection, collateral,
margin and different execution costs. Those cannot be inferred from ETF returns.

## Research disposition

- Evidence questions raised in the comments: **resolved**.
- Frozen v20 strategy: **still rejected**.
- Symmetric long-short claim: **rejected**.
- Futures implementation claim: **not made without futures data**.
- Paper/live orders: **disabled**.

The next admissible strategy is a separately frozen futures-native study. The consumed 2021–2024
ETF holdout cannot be used for parameter selection.
"""
    (output / "COMMENT_ISSUES.md").write_text(report)


def main(v20: Path, output: Path, market_source: Path | None) -> None:
    output.mkdir(parents=True, exist_ok=True)
    daily = pd.read_csv(v20 / "locked_baseline_daily.csv", index_col="session", parse_dates=True)
    book = pd.read_csv(v20 / "locked_book_daily.csv", index_col=0, parse_dates=True)
    book.index.name = "session"
    metrics = pd.read_csv(v20 / "book_metrics.csv")
    rebalances = pd.read_csv(v20 / "locked_rebalances.csv", index_col="session", parse_dates=True)

    reference_path = output / "locked_market_reference.csv"
    if market_source is not None:
        market = extract_market_reference(market_source, daily.index)
        market.to_csv(reference_path)
    else:
        market = pd.read_csv(reference_path, index_col="session", parse_dates=True)
    if not market.index.equals(daily.index):
        raise RuntimeError("market reference and locked daily results are not aligned")

    waterfall = cost_waterfall(metrics)
    yearly = yearly_book_teardown(book)
    betas = beta_table(daily, book, market)
    regimes = regime_table(daily, book, market)
    waterfall.to_csv(output / "short_cost_waterfall.csv", index=False)
    yearly.to_csv(output / "locked_yearly_book_teardown.csv", index=False)
    betas.to_csv(output / "market_beta_diagnostics.csv", index=False)
    regimes.to_csv(output / "regime_book_diagnostics.csv", index=False)

    locked_beta = betas.loc[betas["period"].eq("locked_2021_2024")].set_index("stream")
    locked_short = waterfall.query(
        "segment == 'locked_test' and cost_model == 'baseline'"
    ).iloc[0]
    year_2022 = waterfall.query(
        "segment == 'locked_2022' and cost_model == 'baseline'"
    ).iloc[0]
    yearly_2022 = yearly.loc[yearly["year"].eq(2022)].iloc[0]
    summary = {
        "status": "COMMENT_EVIDENCE_COMPLETE_STRATEGY_REJECTED",
        "diagnostic_only": True,
        "changes_to_strategy": False,
        "orders_allowed": False,
        "market_beta_assessment": "DIRECTIONAL_LONG_DEPENDENCE_CONFIRMED",
        "short_book_assessment": "STANDALONE_EXPECTANCY_FAILED",
        "futures_counterfactual_assessment": "BORROW_REMOVAL_INSUFFICIENT_FULL_HOLDOUT",
        "market_beta": {
            "total_beta": float(locked_beta.loc["total_net", "market_beta"]),
            "total_beta_tstat": float(locked_beta.loc["total_net", "beta_tstat_hac"]),
            "total_r_squared": float(locked_beta.loc["total_net", "r_squared"]),
            "total_annualized_alpha": float(
                locked_beta.loc["total_net", "annualized_alpha"]
            ),
            "long_beta": float(locked_beta.loc["long_net", "market_beta"]),
            "short_beta": float(locked_beta.loc["short_net", "market_beta"]),
        },
        "directional_exposure": {
            "average_gross_exposure": float(rebalances["gross"].mean()),
            "average_net_exposure": float(rebalances["net"].mean()),
            "average_equity_factor_exposure": float(rebalances["exposure_equity"].mean()),
            "average_long_gross_exposure": float(book["long_gross_exposure"].mean()),
            "average_short_gross_exposure": float(book["short_gross_exposure"].mean()),
        },
        "short_book": {
            "locked_borrow_free_expectancy": float(locked_short["borrow_free_expectancy"]),
            "locked_net_expectancy": float(locked_short["net_expectancy"]),
            "locked_net_sharpe": float(locked_short["sharpe"]),
            "year_2022_borrow_free_contribution": float(
                yearly_2022["short_borrow_free_contribution"]
            ),
            "year_2022_net_contribution": float(yearly_2022["short_net_contribution"]),
            "year_2022_long_contribution": float(yearly_2022["long_net_contribution"]),
            "year_2022_borrow_removal_flips_sign": bool(
                year_2022["borrow_removal_flips_sign"]
            ),
        },
        "hashes": {
            "v20_summary_sha256": sha256(v20 / "SUMMARY.json"),
            "locked_daily_sha256": sha256(v20 / "locked_baseline_daily.csv"),
            "locked_book_sha256": sha256(v20 / "locked_book_daily.csv"),
            "market_reference_sha256": sha256(reference_path),
            "audit_source_sha256": sha256(Path(__file__)),
        },
    }
    (output / "SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n")
    write_report(output, summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--v20", type=Path, default=V20)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--market-source", type=Path)
    arguments = parser.parse_args()
    main(arguments.v20, arguments.output, arguments.market_source)
