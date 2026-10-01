import numpy as np
import pandas as pd

from scripts.evaluate_cross_asset_v27 import (
    build_leave_one_out_group_returns,
    build_residual_mean_reversion,
    pooled_score_correlation,
)


def _data(periods: int = 700) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(2701)
    index = pd.bdate_range("2008-01-02", periods=periods)
    columns = [
        "SPY",
        "QQQ",
        "HYG",
        "LQD",
        "TLT",
        "IEF",
        "GLD",
        "SLV",
        "DBC",
        "DBA",
        "UUP",
        "FXE",
    ]
    returns = pd.DataFrame(
        rng.normal(0, 0.01, (periods, len(columns))), index=index, columns=columns
    )
    close = 100 * (1 + returns).cumprod()
    return {
        "returns": returns,
        "close": close,
        "eligibility": pd.DataFrame(True, index=index, columns=columns),
    }


def test_leave_one_out_group_proxy_excludes_the_asset_itself():
    index = pd.date_range("2020-01-01", periods=2)
    returns = pd.DataFrame(
        {"A": [10.0, 20.0], "B": [1.0, 2.0], "C": [3.0, 4.0]}, index=index
    )
    eligibility = returns.notna()
    groups = pd.Series("growth", index=returns.columns)
    proxy = build_leave_one_out_group_returns(returns, eligibility, groups)
    assert np.allclose(proxy["A"], [2.0, 3.0])
    assert np.allclose(proxy["B"], [6.5, 12.0])


def test_residual_mean_reversion_does_not_change_when_future_prices_change():
    data = _data()
    cutoff = data["returns"].index[600]
    baseline = build_residual_mean_reversion(data)
    revised = {key: value.copy() for key, value in data.items()}
    revised["returns"].loc[revised["returns"].index > cutoff] *= 10
    revised["close"] = 100 * (1 + revised["returns"]).cumprod()
    changed = build_residual_mean_reversion(revised)
    for key in (
        "peer_group_return",
        "beta",
        "residual_return",
        "residual_20",
        "residual_z",
        "threshold",
        "signal",
        "sizing_score",
    ):
        pd.testing.assert_frame_equal(baseline[key].loc[:cutoff], changed[key].loc[:cutoff])


def test_pooled_score_correlation_uses_only_requested_period():
    index = pd.bdate_range("2010-01-01", periods=20)
    left = pd.DataFrame({"A": np.arange(20), "B": np.arange(20)[::-1]}, index=index)
    right = left.copy()
    right.loc[index[10] :, :] *= -1
    result = pooled_score_correlation(left, right, (index[0], index[9]))
    assert np.isclose(result["pooled_correlation"], 1.0)
    assert result["observations"] == 20
