import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, OptimizeResult

from backtest.cross_asset_budget import (
    RiskBudgetConfig,
    _is_feasible_candidate,
    run_risk_budget_backtest,
)


def test_nonconverged_candidate_must_still_pass_independent_feasibility_check():
    bounds = Bounds(np.array([-1.0]), np.array([1.0]))
    linear = LinearConstraint(np.array([[1.0]]), -np.inf, np.array([0.5]))
    volatility = lambda x: 0.25 - float(x @ x)
    numerical_boundary = OptimizeResult(x=np.array([0.50000002]), success=False, status=8)
    breached = OptimizeResult(x=np.array([0.51]), success=False, status=8)
    assert _is_feasible_candidate(numerical_boundary, bounds, linear, volatility, 1e-7)
    assert not _is_feasible_candidate(breached, bounds, linear, volatility, 1e-7)


def test_risk_budget_targets_respect_all_caps():
    rng = np.random.default_rng(41)
    index = pd.bdate_range("2018-01-02", periods=200)
    columns = [f"A{i}" for i in range(12)]
    returns = pd.DataFrame(rng.normal(0, .004, (200, 12)), index=index, columns=columns)
    alpha = pd.DataFrame(rng.normal(0, .002, (200, 12)), index=index, columns=columns)
    adv = pd.DataFrame(100_000_000.0, index=index, columns=columns)
    eligibility = pd.DataFrame(True, index=index, columns=columns)
    factors = pd.DataFrame({
        "equity": [1] * 4 + [0] * 8,
        "duration": [0] * 4 + [1] * 4 + [0] * 4,
        "commodity": [0] * 8 + [1] * 4,
    }, index=columns)
    sleeves = pd.Series(["equity"] * 4 + ["rates"] * 4 + ["commodity"] * 4,
                        index=columns)
    result = run_risk_budget_backtest(
        alpha, returns, adv, eligibility, factors,
        pd.Series({"equity": .12, "duration": .12, "commodity": .12}),
        sleeves, pd.Series({"equity": .25, "rates": .25, "commodity": .25}),
        config=RiskBudgetConfig(covariance_window=60, net_cap=.20),
    )
    assert result.status == "COMPLETED"
    assert result.rebalances.net_budget_ratio.max() <= 1.0001
    assert result.rebalances.maximum_factor_budget_ratio.max() <= 1.0001
    assert result.rebalances.maximum_sleeve_budget_ratio.max() <= 1.0001
    assert result.daily.transaction_cost.sum() > 0


def test_risk_scaler_reduces_realized_gross_budget():
    rng = np.random.default_rng(42)
    index = pd.bdate_range("2018-01-02", periods=160)
    columns = [f"A{i}" for i in range(12)]
    returns = pd.DataFrame(rng.normal(0, .004, (160, 12)), index=index, columns=columns)
    alpha = pd.DataFrame(rng.normal(0, .002, (160, 12)), index=index, columns=columns)
    adv = pd.DataFrame(100_000_000.0, index=index, columns=columns)
    factors = pd.DataFrame({"factor": [1, -1] * 6}, index=columns)
    sleeves = pd.Series(["left"] * 6 + ["right"] * 6, index=columns)
    scaler = pd.Series(.5, index=index)
    result = run_risk_budget_backtest(
        alpha, returns, adv, pd.DataFrame(True, index=index, columns=columns), factors,
        pd.Series({"factor": .5}), sleeves, pd.Series({"left": .5, "right": .5}),
        risk_scaler=scaler, config=RiskBudgetConfig(covariance_window=60, net_cap=.5),
    )
    assert result.status == "COMPLETED"
    assert result.rebalances.gross.max() <= .5001
    assert result.rebalances.risk_scaler.eq(.5).all()


def test_temporarily_ineligible_holding_is_carried_without_zero_adv_liquidation():
    rng = np.random.default_rng(43)
    index = pd.bdate_range("2018-01-02", periods=120)
    columns = [f"A{i}" for i in range(12)]
    returns = pd.DataFrame(rng.normal(0, .003, (120, 12)), index=index, columns=columns)
    alpha = pd.DataFrame(0.002, index=index, columns=columns)
    alpha.iloc[:, 1::2] *= -1
    adv = pd.DataFrame(100_000_000.0, index=index, columns=columns)
    eligibility = pd.DataFrame(True, index=index, columns=columns)
    # After positions exist, A0 cannot be traded at one rebalance but still has a valid return.
    eligibility.loc[index[100], "A0"] = False
    adv.loc[index[100], "A0"] = 0
    factors = pd.DataFrame({"factor": [1, -1] * 6}, index=columns)
    sleeves = pd.Series(["all"] * 12, index=columns)
    result = run_risk_budget_backtest(
        alpha, returns, adv, eligibility, factors, pd.Series({"factor": .5}),
        sleeves, pd.Series({"all": 1.0}),
        config=RiskBudgetConfig(covariance_window=60, net_cap=.5),
    )
    assert result.status == "COMPLETED"
    assert result.daily.transaction_cost.notna().all()


def test_name_scaler_can_force_selected_assets_to_cash():
    rng = np.random.default_rng(44)
    index = pd.bdate_range("2018-01-02", periods=150)
    columns = [f"A{i}" for i in range(12)]
    returns = pd.DataFrame(rng.normal(0, .004, (150, 12)), index=index, columns=columns)
    alpha = pd.DataFrame(.002, index=index, columns=columns)
    adv = pd.DataFrame(100_000_000.0, index=index, columns=columns)
    eligibility = pd.DataFrame(True, index=index, columns=columns)
    factors = pd.DataFrame({"factor": [1, -1] * 6}, index=columns)
    sleeves = pd.Series(["all"] * 12, index=columns)
    name_scaler = pd.DataFrame(1.0, index=index, columns=columns)
    name_scaler.loc[:, "A0"] = 0.0
    result = run_risk_budget_backtest(
        alpha, returns, adv, eligibility, factors, pd.Series({"factor": 1.0}),
        sleeves, pd.Series({"all": 1.0}), name_scaler=name_scaler,
        config=RiskBudgetConfig(covariance_window=60, net_cap=1.0),
    )
    assert result.status == "COMPLETED"
    assert result.weights["A0"].abs().max() == 0


def test_optimizer_enforces_short_gross_cap():
    rng = np.random.default_rng(45)
    index = pd.bdate_range("2018-01-02", periods=150)
    columns = [f"A{i}" for i in range(12)]
    returns = pd.DataFrame(rng.normal(0, .004, (150, 12)), index=index, columns=columns)
    alpha = pd.DataFrame(-.004, index=index, columns=columns)
    adv = pd.DataFrame(100_000_000.0, index=index, columns=columns)
    eligibility = pd.DataFrame(True, index=index, columns=columns)
    factors = pd.DataFrame({"factor": [1, -1] * 6}, index=columns)
    sleeves = pd.Series(["all"] * 12, index=columns)
    result = run_risk_budget_backtest(
        alpha, returns, adv, eligibility, factors, pd.Series({"factor": 1.0}),
        sleeves, pd.Series({"all": 1.0}),
        config=RiskBudgetConfig(
            covariance_window=60, net_cap=1.0, max_short_gross=.20,
        ),
    )
    assert result.status == "COMPLETED"
    assert result.rebalances["short_gross"].max() <= .2001
    assert result.rebalances["short_gross_budget_ratio"].max() <= 1.0001


def test_optimizer_enforces_long_gross_cap():
    rng = np.random.default_rng(451)
    index = pd.bdate_range("2018-01-02", periods=150)
    columns = [f"A{i}" for i in range(12)]
    returns = pd.DataFrame(rng.normal(0, .004, (150, 12)), index=index, columns=columns)
    alpha = pd.DataFrame(.004, index=index, columns=columns)
    adv = pd.DataFrame(100_000_000.0, index=index, columns=columns)
    eligibility = pd.DataFrame(True, index=index, columns=columns)
    factors = pd.DataFrame({"factor": [1, -1] * 6}, index=columns)
    sleeves = pd.Series(["all"] * 12, index=columns)
    result = run_risk_budget_backtest(
        alpha, returns, adv, eligibility, factors, pd.Series({"factor": 1.0}),
        sleeves, pd.Series({"all": 1.0}),
        config=RiskBudgetConfig(
            covariance_window=60, net_cap=1.0, max_long_gross=.20,
        ),
    )
    assert result.status == "COMPLETED"
    assert result.rebalances["long_gross"].max() <= .2001
    assert result.rebalances["long_gross_budget_ratio"].max() <= 1.0001


def test_side_specific_scalers_modify_long_and_short_caps():
    rng = np.random.default_rng(452)
    index = pd.bdate_range("2018-01-02", periods=150)
    columns = [f"A{i}" for i in range(12)]
    returns = pd.DataFrame(rng.normal(0, .004, (150, 12)), index=index, columns=columns)
    alpha = pd.DataFrame(
        np.tile([.004, -.004], (150, 6)), index=index, columns=columns
    )
    adv = pd.DataFrame(100_000_000.0, index=index, columns=columns)
    factors = pd.DataFrame({"factor": [1, -1] * 6}, index=columns)
    sleeves = pd.Series(["all"] * 12, index=columns)
    result = run_risk_budget_backtest(
        alpha,
        returns,
        adv,
        pd.DataFrame(True, index=index, columns=columns),
        factors,
        pd.Series({"factor": 1.0}),
        sleeves,
        pd.Series({"all": 1.0}),
        long_gross_scaler=pd.Series(.5, index=index),
        short_gross_scaler=pd.Series(.25, index=index),
        config=RiskBudgetConfig(
            covariance_window=60,
            net_cap=1.0,
            max_long_gross=.6,
            max_short_gross=.4,
        ),
    )
    assert result.status == "COMPLETED"
    assert np.allclose(result.rebalances["long_gross_cap"], .3)
    assert np.allclose(result.rebalances["short_gross_cap"], .1)
    assert result.rebalances["long_gross_budget_ratio"].max() <= 1.0001
    assert result.rebalances["short_gross_budget_ratio"].max() <= 1.0001


def test_dynamic_sleeve_caps_are_enforced_by_session():
    rng = np.random.default_rng(453)
    index = pd.bdate_range("2018-01-02", periods=150)
    columns = [f"A{i}" for i in range(12)]
    returns = pd.DataFrame(rng.normal(0, .004, (150, 12)), index=index, columns=columns)
    alpha = pd.DataFrame(.004, index=index, columns=columns)
    adv = pd.DataFrame(100_000_000.0, index=index, columns=columns)
    factors = pd.DataFrame({"factor": [1, -1] * 6}, index=columns)
    sleeves = pd.Series(["left"] * 6 + ["right"] * 6, index=columns)
    caps = pd.DataFrame({"left": .30, "right": .20}, index=index)
    result = run_risk_budget_backtest(
        alpha,
        returns,
        adv,
        pd.DataFrame(True, index=index, columns=columns),
        factors,
        pd.Series({"factor": 1.0}),
        sleeves,
        caps,
        config=RiskBudgetConfig(covariance_window=60, net_cap=1.0),
    )
    assert result.status == "COMPLETED"
    assert result.rebalances["maximum_sleeve_budget_ratio"].max() <= 1.0001


def test_name_scaler_validation_rejects_noncausal_ranges():
    index = pd.bdate_range("2018-01-02", periods=20)
    columns = [f"A{i}" for i in range(8)]
    frame = pd.DataFrame(0.0, index=index, columns=columns)
    invalid = pd.DataFrame(1.1, index=index, columns=columns)
    with np.testing.assert_raises_regex(ValueError, "name scaler must be in"):
        run_risk_budget_backtest(
            frame, frame, frame + 1, frame.eq(0),
            pd.DataFrame({"factor": 0.0}, index=columns), pd.Series({"factor": 1.0}),
            pd.Series("all", index=columns), pd.Series({"all": 1.0}),
            name_scaler=invalid,
        )


def test_abrupt_name_cap_reduction_uses_feasible_cash_retry():
    rng = np.random.default_rng(46)
    index = pd.bdate_range("2018-01-02", periods=150)
    columns = [f"A{i}" for i in range(12)]
    returns = pd.DataFrame(rng.normal(0, .004, (150, 12)), index=index, columns=columns)
    alpha = pd.DataFrame(.003, index=index, columns=columns)
    adv = pd.DataFrame(100_000_000.0, index=index, columns=columns)
    factors = pd.DataFrame({"factor": [1, -1] * 6}, index=columns)
    sleeves = pd.Series(["all"] * 12, index=columns)
    scaler = pd.DataFrame(1.0, index=index, columns=columns)
    scaler.loc[index[100]:, :] = 0.0
    result = run_risk_budget_backtest(
        alpha, returns, adv, pd.DataFrame(True, index=index, columns=columns),
        factors, pd.Series({"factor": 1.0}), sleeves, pd.Series({"all": 1.0}),
        name_scaler=scaler,
        config=RiskBudgetConfig(covariance_window=60, rebalance_every=5, net_cap=1.0),
    )
    assert result.status == "COMPLETED"
    assert result.rebalances.loc[index[100]:, "gross"].max() <= 1e-8


def test_liquidity_limited_cap_reduction_is_executed_and_disclosed():
    rng = np.random.default_rng(47)
    index = pd.bdate_range("2018-01-02", periods=170)
    columns = [f"A{i}" for i in range(12)]
    returns = pd.DataFrame(rng.normal(0, .003, (170, 12)), index=index, columns=columns)
    alpha = pd.DataFrame(.003, index=index, columns=columns)
    adv = pd.DataFrame(3_000_000.0, index=index, columns=columns)
    factors = pd.DataFrame({"factor": [1, -1] * 6}, index=columns)
    sleeves = pd.Series(["all"] * 12, index=columns)
    scaler = pd.DataFrame(1.0, index=index, columns=columns)
    scaler.loc[index[110]:, :] = 0.0
    result = run_risk_budget_backtest(
        alpha, returns, adv, pd.DataFrame(True, index=index, columns=columns),
        factors, pd.Series({"factor": 1.0}), sleeves, pd.Series({"all": 1.0}),
        name_scaler=scaler,
        config=RiskBudgetConfig(
            covariance_window=60, rebalance_every=5, net_cap=1.0,
            liquidity_limited_cap_reduction=True,
        ),
    )
    assert result.status == "COMPLETED"
    after_cut = result.rebalances.loc[index[110]:]
    assert after_cut["maximum_name_cap_excess"].max() > 0
    assert after_cut.iloc[-1]["maximum_name_cap_excess"] <= 1e-8
    assert after_cut.iloc[-1]["gross"] <= 1e-8
