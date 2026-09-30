import numpy as np
import pandas as pd

from scripts.cross_asset_v17_universe import UNIVERSE, asset_sleeves
from scripts.evaluate_cross_asset_v22 import (
    build_distribution_carry,
    blend_expected_returns,
)


def distribution_fixture(tmp_path):
    index = pd.bdate_range("2010-01-04", periods=320)
    columns = UNIVERSE
    rng = np.random.default_rng(2201)
    returns = pd.DataFrame(rng.normal(0.0001, 0.006, (len(index), len(columns))),
                           index=index, columns=columns)
    close = 100 * (1 + returns).cumprod()
    dividends = pd.DataFrame(0.0, index=index, columns=columns)
    for offset, symbol in enumerate(columns):
        dividends.loc[index[::63], symbol] = 0.1 + offset / 1000
    capital_gains = pd.DataFrame(0.0, index=index, columns=columns)
    rows = []
    for symbol in columns:
        rows.append(pd.DataFrame({
            "symbol": symbol,
            "date": index,
            "close": close[symbol].to_numpy(),
            "dividends": dividends[symbol].to_numpy(),
            "capital_gains": capital_gains[symbol].to_numpy(),
        }))
    source = tmp_path / "etfs.csv"
    pd.concat(rows, ignore_index=True).to_csv(source, index=False)
    data = {
        "close": close,
        "returns": close.pct_change(fill_method=None),
        "eligibility": pd.DataFrame(True, index=index, columns=columns),
    }
    return source, data


def test_distribution_carry_is_causal(tmp_path):
    source, data = distribution_fixture(tmp_path)
    cutoff = data["close"].index[285]
    baseline = build_distribution_carry(source, data)["sizing_score"]
    raw = pd.read_csv(source, parse_dates=["date"])
    raw.loc[raw["date"].gt(cutoff), "dividends"] += 2.0
    changed = tmp_path / "changed.csv"
    raw.to_csv(changed, index=False)
    revised = build_distribution_carry(changed, data)["sizing_score"]
    pd.testing.assert_frame_equal(baseline.loc[:cutoff], revised.loc[:cutoff])


def test_distribution_carry_is_centered_within_sleeve(tmp_path):
    source, data = distribution_fixture(tmp_path)
    carry = build_distribution_carry(source, data)["carry_score"]
    sleeves = asset_sleeves()
    session = carry.dropna(how="all").index[-1]
    for sleeve in sleeves.unique():
        names = sleeves.index[sleeves.eq(sleeve)]
        values = carry.loc[session, names].dropna()
        if len(values) >= 3:
            assert abs(values.mean()) < 1e-12


def test_distribution_event_above_25_percent_is_rejected(tmp_path):
    source, data = distribution_fixture(tmp_path)
    raw = pd.read_csv(source, parse_dates=["date"])
    date = data["close"].index[280]
    prior_close = float(data["close"].loc[data["close"].index[279], "SPY"])
    raw.loc[(raw.symbol == "SPY") & (raw.date == date), "dividends"] = prior_close * .30
    raw.to_csv(source, index=False)
    fields = build_distribution_carry(source, data)
    assert fields["rejected_event"].loc[date, "SPY"]
    assert np.isnan(fields["event_yield"].loc[date, "SPY"])


def test_expected_return_blend_uses_frozen_70_30_weights():
    index = pd.bdate_range("2020-01-02", periods=2)
    trend = pd.DataFrame({"A": [1.0, 2.0]}, index=index)
    carry = pd.DataFrame({"A": [3.0, 4.0]}, index=index)
    result = blend_expected_returns(trend, carry, 0.5, 0.25)
    expected = 0.70 * trend * 0.5 + 0.30 * carry * 0.25
    pd.testing.assert_frame_equal(result, expected)
