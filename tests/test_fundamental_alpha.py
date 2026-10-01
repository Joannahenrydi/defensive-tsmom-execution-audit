import numpy as np
import pandas as pd

from features.fundamental_alpha import build_fundamental_scores, expand_fundamentals_asof


def _events(names: int = 5) -> pd.DataFrame:
    rows = []
    for number in range(names):
        rows.append(
            {
                "symbol": f"S{number}",
                "sector": "Industrials",
                "available_at": "2022-03-02",
                "profitability": number + 1.0,
                "gross_profitability": number + 2.0,
                "cash_profitability": number + 3.0,
                "accrual_quality": number + 4.0,
                "asset_growth": 5.0 - number,
                "revenue_growth": 4.0 - number,
            }
        )
    return pd.DataFrame(rows)


def test_filing_is_not_visible_before_available_date_and_expires() -> None:
    sessions = pd.DatetimeIndex(["2022-03-01", "2022-03-02", "2023-04-10"])
    expanded = expand_fundamentals_asof(_events(1), sessions, max_age_days=400)
    assert pd.Timestamp("2022-03-01") not in set(expanded["date"])
    assert pd.Timestamp("2022-03-02") in set(expanded["date"])
    assert pd.Timestamp("2023-04-10") not in set(expanded["date"])


def test_scores_are_sector_neutral_and_require_five_names() -> None:
    sessions = pd.DatetimeIndex(["2022-03-02"])
    expanded = expand_fundamentals_asof(_events(5), sessions)
    scores = build_fundamental_scores(expanded, minimum_cross_section=5)
    assert np.isclose(scores["quality_score"].mean(), 0)
    assert np.isclose(scores["conservative_growth_score"].mean(), 0)


def test_small_sector_does_not_receive_ranked_score() -> None:
    sessions = pd.DatetimeIndex(["2022-03-02"])
    expanded = expand_fundamentals_asof(_events(4), sessions)
    scores = build_fundamental_scores(expanded, minimum_cross_section=4)
    assert scores["quality_score"].isna().all()
