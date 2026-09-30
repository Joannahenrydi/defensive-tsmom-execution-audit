import numpy as np
import pandas as pd

from scripts.audit_v20_deleveraging_interaction import (
    classify_gross_change,
    interaction_summary,
    reconstruct_interactions,
)


def test_gross_change_classification_uses_fixed_ten_percent_threshold():
    change = pd.Series([-0.11, -0.10, 0.0, 0.10, 0.11])
    result = classify_gross_change(change)
    assert result.tolist() == [
        "deleveraging",
        "normal",
        "normal",
        "normal",
        "expansion",
    ]


def test_reconstruction_aligns_trade_cost_to_following_session():
    index = pd.bdate_range("2022-01-03", periods=3)
    returns = pd.DataFrame({"A": [0.10, 0.0, 0.0], "B": [0.0, 0.0, 0.0]}, index=index)
    weights = pd.DataFrame({"A": [0.5, 0.4, 0.4], "B": [-0.5, -0.4, -0.4]}, index=index)
    daily = pd.DataFrame(
        {
            "net_return": [0.05, 0.0, 0.0],
            "transaction_cost": [0.0, 0.001, 0.0],
        },
        index=index,
    )
    state_daily = daily.copy()
    state_daily.loc[index[1], "transaction_cost"] = 0.002
    rebalances = pd.DataFrame(
        {"gross": [0.8], "turnover": [0.2]}, index=pd.DatetimeIndex([index[0]])
    )
    multipliers = pd.DataFrame(
        {
            "volatility_ratio": [1.0, 1.5, 1.0],
            "liquidity_ratio": [1.0, 0.5, 1.0],
            "prior_drawdown": [0.0, -0.11, 0.0],
            "transaction_multiplier": [1.0, 4.0, 1.0],
        },
        index=index,
    )
    result = reconstruct_interactions(
        returns, weights, daily, state_daily, rebalances, multipliers
    )
    row = result.iloc[0]
    expected_before = abs(0.5 * 1.1 / 1.05) + abs(-0.5 / 1.05)
    assert np.isclose(row["gross_before"], expected_before)
    assert row["execution_session"] == index[1]
    assert np.isclose(row["total_cost_multiplier"], 4.0)
    assert np.isclose(row["incremental_state_cost"], 0.001)


def test_interaction_summary_reports_threshold_and_direction_groups():
    index = pd.to_datetime(["2022-01-03", "2022-02-01", "2023-01-03"])
    events = pd.DataFrame(
        {
            "gross_change_fraction": [-0.2, 0.0, 0.2],
            "rebalance_state": ["deleveraging", "normal", "expansion"],
            "gross_direction": ["reduction", "non_reduction", "non_reduction"],
            "volatility_stress_multiplier": [2.0, 1.0, 1.5],
            "liquidity_stress_multiplier": [1.5, 1.0, 1.2],
            "drawdown_stress_multiplier": [1.5, 1.0, 1.0],
            "total_cost_multiplier": [3.0, 1.0, 1.8],
            "turnover": [0.2, 0.01, 0.2],
            "baseline_transaction_cost": [0.001, 0.0001, 0.001],
            "state_transaction_cost": [0.003, 0.0001, 0.0018],
            "incremental_state_cost": [0.002, 0.0, 0.0008],
            "execution_day_portfolio_return": [-0.01, 0.001, 0.002],
        },
        index=index,
    )
    summary = interaction_summary(events)
    locked_deleveraging = summary.query(
        "period == 'locked_2021_2024' and state == 'deleveraging'"
    ).iloc[0]
    year_2022 = summary.query(
        "period == 'calendar_2022' and grouping == 'gross_direction' "
        "and state == 'reduction'"
    ).iloc[0]
    assert locked_deleveraging["events"] == 1
    assert np.isclose(locked_deleveraging["mean_total_cost_multiplier"], 3.0)
    assert year_2022["events"] == 1
