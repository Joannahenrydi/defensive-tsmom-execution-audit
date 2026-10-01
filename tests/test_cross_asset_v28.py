from pathlib import Path

import numpy as np
import pandas as pd

from scripts.evaluate_cross_asset_v28 import (
    build_ohlcv_families,
    causal_dislocation_signal,
    remove_group_median,
)


def test_group_median_residualization_is_cross_sectional():
    index = pd.date_range("2020-01-01", periods=1)
    frame = pd.DataFrame({"A": [1.0], "B": [3.0], "C": [8.0]}, index=index)
    eligibility = frame.notna()
    groups = pd.Series("growth", index=frame.columns)
    result = remove_group_median(frame, eligibility, groups)
    assert np.allclose(result.iloc[0], [-2.0, 0.0, 5.0])


def test_dislocation_standardization_uses_only_prior_history():
    rng = np.random.default_rng(2801)
    index = pd.bdate_range("2010-01-04", periods=600)
    columns = ["A", "B"]
    frame = pd.DataFrame(rng.normal(size=(600, 2)), index=index, columns=columns)
    eligibility = frame.notna()
    cutoff = index[500]
    baseline = causal_dislocation_signal(frame, eligibility)
    changed_frame = frame.copy()
    changed_frame.loc[changed_frame.index > cutoff] += 100
    changed = causal_dislocation_signal(changed_frame, eligibility)
    for key in ("raw", "z_score", "threshold", "signal"):
        pd.testing.assert_frame_equal(baseline[key].loc[:cutoff], changed[key].loc[:cutoff])


def test_ohlcv_features_do_not_change_when_future_bars_change(tmp_path: Path):
    rng = np.random.default_rng(2802)
    index = pd.bdate_range("2008-01-02", periods=700)
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
        rng.normal(0, 0.01, (700, len(columns))), index=index, columns=columns
    )
    close = 100 * (1 + returns).cumprod()
    open_price = close.shift(1).fillna(100) * (1 + rng.normal(0, 0.002, close.shape))
    records = []
    for symbol in columns:
        frame = pd.DataFrame(
            {
                "symbol": symbol,
                "date": index,
                "open": open_price[symbol],
                "high": np.maximum(open_price[symbol], close[symbol]) * 1.001,
                "low": np.minimum(open_price[symbol], close[symbol]) * 0.999,
                "close": close[symbol],
                "adj_close": close[symbol],
                "volume": 1_000_000 + rng.integers(0, 100_000, len(index)),
            }
        )
        records.append(frame)
    source = tmp_path / "bars.csv"
    pd.concat(records).to_csv(source, index=False)
    data = {
        "returns": returns,
        "close": close,
        "eligibility": pd.DataFrame(True, index=index, columns=columns),
    }
    cutoff = index[600]
    baseline = build_ohlcv_families(source, data)
    changed_data = {key: value.copy() for key, value in data.items()}
    changed_data["returns"].loc[index > cutoff] *= 5
    changed_data["close"] = 100 * (1 + changed_data["returns"]).cumprod()
    raw = pd.read_csv(source, parse_dates=["date"])
    mask = raw["date"].gt(cutoff)
    raw.loc[mask, ["open", "high", "low", "close", "adj_close"]] *= 5
    changed_source = tmp_path / "changed.csv"
    raw.to_csv(changed_source, index=False)
    changed = build_ohlcv_families(changed_source, changed_data)
    for family in baseline:
        for key in ("raw", "z_score", "threshold", "signal", "sizing_score"):
            pd.testing.assert_frame_equal(
                baseline[family][key].loc[:cutoff], changed[family][key].loc[:cutoff]
            )
