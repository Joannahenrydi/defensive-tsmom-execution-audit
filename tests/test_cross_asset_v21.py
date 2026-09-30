import numpy as np
import pandas as pd

from scripts.evaluate_cross_asset_v21 import (
    CANDIDATES,
    build_candidate_features,
    select_candidate,
)


def synthetic_data(periods=520, assets=8):
    index = pd.bdate_range("2010-01-04", periods=periods)
    columns = [f"A{i}" for i in range(assets)]
    rng = np.random.default_rng(2101)
    returns = pd.DataFrame(rng.normal(0.0001, 0.01, (periods, assets)), index=index, columns=columns)
    close = 100 * (1 + returns).cumprod()
    return {
        "close": close,
        "returns": close.pct_change(fill_method=None),
        "eligibility": pd.DataFrame(True, index=index, columns=columns),
    }


def test_v21_matrix_is_the_eight_prespecified_candidates():
    assert [candidate.name for candidate in CANDIDATES] == list("ABCDEFGH")
    assert CANDIDATES[3].cash_fallback
    assert CANDIDATES[4].short_threshold == -0.50
    assert CANDIDATES[5].volatility_floor == 0.10
    assert CANDIDATES[6].short_gross_cap == 0.25
    assert CANDIDATES[7].rates_sleeve_cap == 0.30


def test_v21_features_do_not_change_when_future_prices_change():
    data = synthetic_data()
    cutoff = data["close"].index[430]
    baseline = build_candidate_features(data, CANDIDATES[3])
    changed = {key: value.copy() for key, value in data.items()}
    changed["close"].loc[changed["close"].index > cutoff] *= 3.0
    changed["returns"] = changed["close"].pct_change(fill_method=None)
    revised = build_candidate_features(changed, CANDIDATES[3])
    for key in ("sizing_score", "name_scaler", "overlay_multiplier"):
        pd.testing.assert_frame_equal(
            baseline[key].loc[:cutoff], revised[key].loc[:cutoff]
        )


def test_volatility_floor_and_relative_scaler_are_enforced():
    data = synthetic_data()
    features = build_candidate_features(data, CANDIDATES[3])
    effective = features["effective_volatility"]
    annualized = features["annualized_volatility"]
    relative_floor = annualized.median(axis=1).div(1.5)
    usable = effective.notna()
    assert (effective.where(usable).min(axis=1).dropna() >= 0.08 - 1e-12).all()
    difference = effective.sub(relative_floor, axis=0).where(usable)
    assert difference.min().min() >= -1e-12


def test_train_selection_ignores_development_performance_and_uses_tie_rule():
    rows = [
        {"candidate": "A", "segment": "train", "qualified": True, "sharpe": 0.80},
        {"candidate": "B", "segment": "train", "qualified": True, "sharpe": 0.81},
        {"candidate": "A", "segment": "development", "qualified": False, "sharpe": -5.0},
        {"candidate": "B", "segment": "development", "qualified": False, "sharpe": 5.0},
    ]
    assert select_candidate(rows) == "A"


def test_cash_fallback_closes_names_without_an_entry_signal():
    data = synthetic_data()
    features = build_candidate_features(data, CANDIDATES[3])
    inactive = ~(features["long_active"] | features["short_active"])
    assert features["name_scaler"].where(inactive).fillna(0.0).eq(0.0).all().all()
