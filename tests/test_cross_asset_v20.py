import numpy as np
import pandas as pd

from backtest.cross_asset import CrossAssetResult
from scripts.evaluate_cross_asset_v20 import (
    build_state_cost_multipliers,
    locked_portfolio_passes,
    long_short_daily_attribution,
    reprice_state_dependent_costs,
    short_book_passes,
)


def sample_result():
    index = pd.bdate_range("2022-01-03", periods=2)
    weights = pd.DataFrame({"A": [0.0, 0.5], "B": [0.0, -0.5]}, index=index)
    returns = pd.DataFrame({"A": [0.0, 0.10], "B": [0.0, -0.10]}, index=index)
    daily = pd.DataFrame(
        {
            "gross_return": [0.0, 0.10],
            "transaction_cost": [0.0, 0.002],
            "borrow_cost": [0.0, 0.001],
            "net_return": [0.0, 0.097],
            "gross": [0.0, 1.0],
            "net": [0.0, 0.0],
            "turnover": [0.0, 1.0],
        },
        index=index,
    )
    result = CrossAssetResult(
        daily=daily,
        weights=weights,
        rebalances=pd.DataFrame(index=index[:1]),
        status="COMPLETED",
        reason="OK",
    )
    return result, returns


def test_state_cost_features_do_not_change_when_future_data_change():
    rng = np.random.default_rng(7)
    index = pd.bdate_range("2019-01-02", periods=420)
    symbols = ["SPY", "TLT", "GLD"]
    innovations = pd.DataFrame(
        rng.normal(0.0002, 0.01, (len(index), len(symbols))),
        index=index,
        columns=symbols,
    )
    close = 100 * (1 + innovations).cumprod()
    volume = pd.DataFrame(
        rng.integers(1_000_000, 3_000_000, (len(index), len(symbols))),
        index=index,
        columns=symbols,
    )
    data = {"returns": close.pct_change(), "close": close, "volume": volume}
    baseline = build_state_cost_multipliers(data)

    cutoff = index[350]
    changed_close = close.copy()
    changed_volume = volume.copy()
    changed_close.loc[index[351]:] *= 1.75
    changed_volume.loc[index[351]:] *= 4
    changed = build_state_cost_multipliers(
        {
            "returns": changed_close.pct_change(),
            "close": changed_close,
            "volume": changed_volume,
        }
    )
    pd.testing.assert_frame_equal(baseline.loc[:cutoff], changed.loc[:cutoff])


def test_state_cost_repricing_preserves_holdings_and_reconciles_net_return():
    result, _ = sample_result()
    multipliers = pd.DataFrame(
        {
            "transaction_multiplier": [1.0, 3.0],
            "borrow_multiplier": [1.0, 2.0],
        },
        index=result.daily.index,
    )
    stressed = reprice_state_dependent_costs(result, multipliers)
    pd.testing.assert_frame_equal(stressed.weights, result.weights)
    pd.testing.assert_frame_equal(stressed.rebalances, result.rebalances)
    pd.testing.assert_series_equal(stressed.daily.turnover, result.daily.turnover)
    pd.testing.assert_series_equal(stressed.daily.gross_return, result.daily.gross_return)
    assert np.isclose(stressed.daily.iloc[1].transaction_cost, 0.006)
    assert np.isclose(stressed.daily.iloc[1].borrow_cost, 0.002)
    assert np.isclose(stressed.daily.iloc[1].net_return, 0.092)


def test_long_short_cost_allocation_reconciles_total_portfolio():
    result, returns = sample_result()
    attribution = long_short_daily_attribution(result, returns)
    assert np.isclose(attribution.iloc[1].long_transaction_cost, 0.001)
    assert np.isclose(attribution.iloc[1].short_transaction_cost, 0.001)
    assert np.isclose(attribution.iloc[1].long_net_return, 0.049)
    assert np.isclose(attribution.iloc[1].short_net_return, 0.048)
    assert np.allclose(
        attribution.long_net_return + attribution.short_net_return,
        result.daily.net_return,
    )


def test_locked_portfolio_gate_requires_cost_stresses_and_risk_budgets():
    passing = {
        "status": "COMPLETED",
        "cagr": 0.01,
        "sharpe": 0.6,
        "max_drawdown": -0.10,
        "maximum_net_budget_ratio": 1.0,
        "maximum_factor_budget_ratio": 1.0,
        "maximum_sleeve_budget_ratio": 1.0,
    }
    assert locked_portfolio_passes(passing, passing, passing)
    assert not locked_portfolio_passes({**passing, "sharpe": 0.5}, passing, passing)
    assert not locked_portfolio_passes(passing, {**passing, "sharpe": 0.0}, passing)
    assert not locked_portfolio_passes(
        {**passing, "maximum_factor_budget_ratio": 1.01}, passing, passing
    )


def test_short_book_gate_requires_positive_expectancy_in_all_three_segments():
    rows = []
    for segment in ("train", "development", "locked_test"):
        rows.append(
            {
                "segment": segment,
                "cost_model": "baseline",
                "book": "short",
                "annualized_arithmetic_expectancy": 0.01,
                "sharpe": 0.2,
            }
        )
    table = pd.DataFrame(rows)
    assert short_book_passes(table)
    table.loc[table.segment.eq("development"), "sharpe"] = -0.1
    assert not short_book_passes(table)
