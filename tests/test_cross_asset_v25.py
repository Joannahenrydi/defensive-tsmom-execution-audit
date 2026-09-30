import numpy as np
import pandas as pd

from scripts.evaluate_cross_asset_v25 import (
    apply_conditional_short_multiplier,
    build_market_regime,
    side_gross_scalers,
)


def _market_data() -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(2501)
    index = pd.bdate_range("2005-01-03", periods=800)
    shocks = rng.normal(0.0001, 0.01, len(index))
    close = pd.Series(100 * np.exp(np.cumsum(shocks)), index=index, name="SPY")
    return {
        "close": close.to_frame(),
        "returns": close.pct_change(fill_method=None).fillna(0.0).to_frame(),
    }


def test_conditional_short_multiplier_never_changes_long_scores():
    index = pd.date_range("2020-01-01", periods=4)
    score = pd.DataFrame(
        {"A": [1.0, -1.0, 2.0, -2.0], "B": [-3.0, 3.0, -4.0, 4.0]}, index=index
    )
    risk_off = pd.Series([False, False, True, True], index=index)
    adjusted = apply_conditional_short_multiplier(score, risk_off)
    pd.testing.assert_frame_equal(adjusted.where(score.ge(0)), score.where(score.ge(0)))
    assert adjusted.loc[index[0], "B"] == -1.5
    assert adjusted.loc[index[1], "A"] == -0.5
    assert adjusted.loc[index[2], "B"] == -4.0
    assert adjusted.loc[index[3], "A"] == -2.0


def test_side_caps_follow_only_the_frozen_market_regime():
    index = pd.date_range("2020-01-01", periods=3)
    risk_off = pd.Series([False, True, False], index=index)
    long_scaler, short_scaler = side_gross_scalers(risk_off)
    assert long_scaler.tolist() == [1.0, 0.5, 1.0]
    assert short_scaler.tolist() == [0.25, 1.0, 0.25]


def test_market_regime_is_causal_to_future_price_changes():
    data = _market_data()
    cutoff = data["close"].index[650]
    baseline = build_market_regime(data)
    revised_close = data["close"].copy()
    revised_close.loc[revised_close.index > cutoff, "SPY"] *= 0.5
    revised = {
        "close": revised_close,
        "returns": revised_close.pct_change(fill_method=None).fillna(0.0),
    }
    changed = build_market_regime(revised)
    pd.testing.assert_frame_equal(baseline.loc[:cutoff], changed.loc[:cutoff])


def test_market_regime_requires_all_three_conditions():
    data = _market_data()
    regime = build_market_regime(data)
    expected = (
        regime["spy_close"].lt(regime["spy_ma200"])
        & regime["spy_return_252"].lt(0)
        & regime["spy_volatility_20"].gt(regime["spy_volatility_p70"])
    ).fillna(False)
    pd.testing.assert_series_equal(regime["risk_off"], expected, check_names=False)
