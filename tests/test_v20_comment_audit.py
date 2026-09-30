import numpy as np
import pandas as pd

from scripts.audit_v20_comment_claims import (
    annualized_stats,
    cost_waterfall,
    regression_diagnostics,
    yearly_book_teardown,
)


def test_regression_diagnostics_recovers_market_beta():
    index = pd.bdate_range("2021-01-04", periods=300)
    market = pd.Series(np.linspace(-0.02, 0.02, len(index)), index=index)
    strategy = 0.0001 + 0.25 * market
    result = regression_diagnostics(strategy, market)
    assert np.isclose(result["market_beta"], 0.25)
    assert np.isclose(result["annualized_alpha"], 0.0252)
    assert np.isclose(result["r_squared"], 1.0)


def test_cost_waterfall_separates_borrow_from_gross_signal():
    table = pd.DataFrame(
        {
            "segment": ["locked_test"],
            "cost_model": ["baseline"],
            "book": ["short"],
            "sessions": [252],
            "gross_return_contribution": [0.02],
            "transaction_cost": [0.002],
            "borrow_cost": [0.03],
            "annualized_arithmetic_expectancy": [-0.012],
            "sharpe": [-0.5],
        }
    )
    result = cost_waterfall(table).iloc[0]
    assert np.isclose(result["gross_expectancy"], 0.02)
    assert np.isclose(result["borrow_free_expectancy"], 0.018)
    assert np.isclose(result["net_expectancy"], -0.012)
    assert bool(result["borrow_removal_flips_sign"])


def test_yearly_teardown_reconciles_short_cost_waterfall():
    index = pd.to_datetime(["2022-01-03", "2022-01-04"])
    book = pd.DataFrame(
        {
            "long_net_return": [-0.01, 0.002],
            "short_gross_return": [0.003, 0.001],
            "short_transaction_cost": [0.0002, 0.0001],
            "short_borrow_cost": [0.0005, 0.0005],
            "short_net_return": [0.0023, 0.0004],
            "long_gross_exposure": [0.6, 0.5],
            "short_gross_exposure": [0.2, 0.3],
        },
        index=index,
    )
    result = yearly_book_teardown(book).iloc[0]
    assert np.isclose(result["short_gross_contribution"], 0.004)
    assert np.isclose(result["short_borrow_free_contribution"], 0.0037)
    assert np.isclose(result["short_net_contribution"], 0.0027)


def test_annualized_stats_handles_contribution_stream():
    result = annualized_stats(pd.Series([0.01, -0.005, 0.002]))
    assert result["sessions"] == 3
    assert np.isclose(result["arithmetic_contribution"], 0.007)
    assert result["annualized_volatility"] > 0
