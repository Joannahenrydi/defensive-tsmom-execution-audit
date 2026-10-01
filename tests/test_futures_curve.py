import numpy as np
import pandas as pd

from features.futures_curve import contract_curve, held_contract_returns


def _metadata(cash_settled: bool = True) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "root": ["ES", "ES", "ES"],
            "contract": ["ESH4", "ESM4", "ESU4"],
            "expiry_date": ["2024-03-15", "2024-06-21", "2024-09-20"],
            "first_notice_date": [None, None, None],
            "last_trade_date": ["2024-03-15", "2024-06-21", "2024-09-20"],
            "cash_settled": [cash_settled] * 3,
        }
    )


def _daily() -> pd.DataFrame:
    rows = []
    for date, values in {
        "2024-03-07": {"ESH4": 102.0, "ESM4": 100.0, "ESU4": 99.0},
        "2024-03-08": {"ESH4": 103.0, "ESM4": 101.0, "ESU4": 100.0},
        "2024-03-11": {"ESH4": 150.0, "ESM4": 102.0, "ESU4": 101.0},
    }.items():
        for contract, settlement in values.items():
            rows.append(
                {
                    "date": date,
                    "root": "ES",
                    "contract": contract,
                    "settlement": settlement,
                    "volume": 100,
                    "open_interest": 200,
                }
            )
    return pd.DataFrame(rows)


def test_curve_carry_is_positive_in_backwardation_and_rolls_before_deadline() -> None:
    curve = contract_curve(_daily(), _metadata(), roll_buffer_days=5)
    march_7 = curve.loc[curve["date"].eq(pd.Timestamp("2024-03-07"))].iloc[0]
    march_8 = curve.loc[curve["date"].eq(pd.Timestamp("2024-03-08"))].iloc[0]
    assert march_7["front_contract"] == "ESH4"
    assert march_7["carry_annualized"] > 0
    assert march_8["front_contract"] == "ESM4"
    assert march_8["next_contract"] == "ESU4"


def test_held_return_uses_same_contract_across_roll() -> None:
    curve = contract_curve(_daily(), _metadata(), roll_buffer_days=5)
    returns = held_contract_returns(curve, _daily()).set_index("date")
    # The March 11 return holds ESM4 from the March 8 close; it does not compare
    # ESM4 with the expired ESH4 price level.
    assert np.isclose(returns.loc[pd.Timestamp("2024-03-11"), "excess_return"], 102 / 101 - 1)


def test_physical_contracts_without_first_notice_are_excluded() -> None:
    curve = contract_curve(_daily(), _metadata(cash_settled=False), roll_buffer_days=5)
    assert curve.empty
