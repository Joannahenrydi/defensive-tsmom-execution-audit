import numpy as np
import pandas as pd

from scripts.evaluate_cross_asset_v24 import (
    build_dynamic_symmetric_tsmom,
    symmetric_position,
)


def _synthetic_data() -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(2401)
    index = pd.bdate_range("2005-01-03", periods=900)
    columns = ["SPY", "TLT", "GLD", "HYG"]
    shocks = rng.normal(0.0002, 0.008, (len(index), len(columns)))
    close = pd.DataFrame(100 * np.exp(np.cumsum(shocks, axis=0)), index=index, columns=columns)
    returns = close.pct_change(fill_method=None).fillna(0.0)
    return {
        "close": close,
        "returns": returns,
        "eligibility": pd.DataFrame(True, index=index, columns=columns),
    }


def test_symmetric_mapping_is_odd_under_joint_sign_reversal():
    index = pd.date_range("2020-01-01", periods=4)
    z = pd.DataFrame({"A": [-2.0, -0.4, 0.4, 2.0]}, index=index)
    threshold = pd.DataFrame(1.0, index=index, columns=["A"])
    trend = pd.DataFrame({"A": [-1.0, -1.0, 1.0, 1.0]}, index=index)
    original = symmetric_position(z, threshold, trend)
    mirrored = symmetric_position(-z, threshold, -trend)
    pd.testing.assert_frame_equal(mirrored, -original)
    assert original.iloc[1:3, 0].eq(0).all()


def test_v24_features_do_not_change_when_future_prices_change():
    data = _synthetic_data()
    cutoff = data["close"].index[760]
    original = build_dynamic_symmetric_tsmom(data)
    revised_close = data["close"].copy()
    revised_close.loc[revised_close.index > cutoff] *= np.array([1.5, 0.7, 1.2, 0.8])
    revised = {
        **data,
        "close": revised_close,
        "returns": revised_close.pct_change(fill_method=None).fillna(0.0),
    }
    changed = build_dynamic_symmetric_tsmom(revised)
    for key in ("z_score", "threshold", "trend_strength", "signal", "sizing_score"):
        pd.testing.assert_frame_equal(original[key].loc[:cutoff], changed[key].loc[:cutoff])
    pd.testing.assert_series_equal(
        original["risk_scaler"].loc[:cutoff], changed["risk_scaler"].loc[:cutoff]
    )


def test_dynamic_threshold_excludes_current_z_score():
    data = _synthetic_data()
    features = build_dynamic_symmetric_tsmom(data)
    z_score = features["z_score"]
    threshold = features["threshold"]
    session = z_score.index[-1]
    revised = z_score.copy()
    revised.loc[session] = 100.0
    expected = revised.abs().rolling(252, min_periods=126).quantile(0.70).shift(1)
    pd.testing.assert_series_equal(threshold.loc[session], expected.loc[session])


def test_v24_signal_contains_both_directions_when_trends_support_them():
    data = _synthetic_data()
    signal = build_dynamic_symmetric_tsmom(data)["signal"]
    assert signal.gt(0).any().any()
    assert signal.lt(0).any().any()
