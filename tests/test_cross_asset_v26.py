import numpy as np
import pandas as pd

from scripts.evaluate_cross_asset_v26 import (
    RISK_GROUPS,
    apply_adaptive_exposure,
    build_group_risk_budgets,
    build_relative_strength,
    solve_equal_risk_budget,
)


def _groups(columns: list[str]) -> pd.Series:
    return pd.Series(
        np.repeat(RISK_GROUPS, len(columns) // len(RISK_GROUPS)), index=columns
    )


def test_equal_risk_solver_returns_equal_contributions_for_identity_covariance():
    weight, contribution, valid = solve_equal_risk_budget(np.eye(4))
    assert valid
    assert np.allclose(weight, .25, atol=1e-7)
    assert np.allclose(contribution, .25, atol=1e-7)


def test_relative_strength_is_causal_to_future_composite_changes():
    rng = np.random.default_rng(2601)
    index = pd.bdate_range("2005-01-03", periods=600)
    columns = [f"A{i}" for i in range(8)]
    composite = pd.DataFrame(rng.normal(size=(600, 8)), index=index, columns=columns)
    eligibility = pd.DataFrame(True, index=index, columns=columns)
    groups = _groups(columns)
    cutoff = index[500]
    baseline = build_relative_strength(composite, groups, eligibility)
    revised = composite.copy()
    revised.loc[revised.index > cutoff] += 20
    changed = build_relative_strength(revised, groups, eligibility)
    for key in ("residual", "z_score", "threshold", "signal"):
        pd.testing.assert_frame_equal(baseline[key].loc[:cutoff], changed[key].loc[:cutoff])


def test_adaptive_exposure_uses_cash_in_risk_on_and_conditional_shorts_in_risk_off():
    index = pd.date_range("2020-01-01", periods=2)
    columns = [f"A{i}" for i in range(8)]
    signal = pd.DataFrame(
        [[1, -1, 1, -1, 1, -1, 1, -1], [1, -1, 1, -1, 1, -1, 1, -1]],
        index=index,
        columns=columns,
        dtype=float,
    )
    groups = _groups(columns)
    adapted = apply_adaptive_exposure(
        signal, pd.Series([False, True], index=index), groups
    )
    assert adapted.loc[index[0]].min() == 0
    assert adapted.loc[index[1], "A0"] == .4
    assert adapted.loc[index[1], "A1"] == -.5
    assert adapted.loc[index[1], "A2"] == 1
    assert adapted.loc[index[1], "A3"] == -.5


def test_group_risk_budgets_use_only_prior_returns():
    rng = np.random.default_rng(2602)
    index = pd.bdate_range("2010-01-04", periods=240)
    columns = [f"A{i}" for i in range(8)]
    returns = pd.DataFrame(rng.normal(0, .01, (240, 8)), index=index, columns=columns)
    groups = _groups(columns)
    cutoff = index[180]
    baseline, _ = build_group_risk_budgets(returns, groups)
    revised = returns.copy()
    revised.loc[revised.index > cutoff] *= 10
    changed, _ = build_group_risk_budgets(revised, groups)
    pd.testing.assert_frame_equal(baseline.loc[:cutoff], changed.loc[:cutoff])
