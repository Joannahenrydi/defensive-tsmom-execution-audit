"""Point-in-time expansion and ranking of as-reported fundamental events."""

from __future__ import annotations

import numpy as np
import pandas as pd

FUNDAMENTAL_COMPONENTS = (
    "profitability",
    "gross_profitability",
    "cash_profitability",
    "accrual_quality",
    "asset_growth",
    "revenue_growth",
)


def expand_fundamentals_asof(
    events: pd.DataFrame,
    sessions: pd.DatetimeIndex,
    max_age_days: int = 400,
) -> pd.DataFrame:
    """Carry each issuer's latest available filing onto sessions without backfilling."""
    required = {"symbol", "sector", "available_at", *FUNDAMENTAL_COMPONENTS}
    missing = sorted(required - set(events.columns))
    if missing:
        raise ValueError(f"events missing columns: {','.join(missing)}")
    if max_age_days <= 0:
        raise ValueError("max_age_days must be positive")
    calendar = pd.DataFrame({"date": pd.DatetimeIndex(sessions).normalize()}).sort_values("date")
    pieces = []
    source = events.copy()
    source["available_at"] = pd.to_datetime(source["available_at"], errors="coerce").dt.normalize()
    source = source.dropna(subset=["symbol", "sector", "available_at"])
    for symbol, filings in source.groupby("symbol", sort=True):
        filings = filings.sort_values(["available_at"])
        expanded = pd.merge_asof(
            calendar,
            filings,
            left_on="date",
            right_on="available_at",
            direction="backward",
            allow_exact_matches=True,
        )
        expanded["symbol"] = symbol
        expanded["filing_age_days"] = (expanded["date"] - expanded["available_at"]).dt.days
        expanded = expanded.loc[expanded["filing_age_days"].between(0, max_age_days)]
        pieces.append(expanded)
    if not pieces:
        return pd.DataFrame(columns=["date", *sorted(required), "filing_age_days"])
    return pd.concat(pieces, ignore_index=True)


def _sector_rank(values: pd.Series) -> pd.Series:
    count = values.notna().sum()
    if count < 5:
        return pd.Series(np.nan, index=values.index)
    clipped = values.clip(values.quantile(0.01), values.quantile(0.99))
    rank = clipped.rank(method="average")
    return rank.sub((count + 1) / 2).div((count - 1) / 2)


def build_fundamental_scores(
    expanded: pd.DataFrame,
    minimum_cross_section: int = 100,
) -> pd.DataFrame:
    """Create sector-neutral quality and conservative-growth scores by session."""
    if minimum_cross_section < 1:
        raise ValueError("minimum_cross_section must be positive")
    frame = expanded.copy()
    ranked_columns = []
    for component in FUNDAMENTAL_COMPONENTS:
        ranked = f"{component}_rank"
        frame[ranked] = frame.groupby(["date", "sector"])[component].transform(_sector_rank)
        ranked_columns.append(ranked)
    quality = [f"{name}_rank" for name in FUNDAMENTAL_COMPONENTS[:4]]
    growth = [f"{name}_rank" for name in FUNDAMENTAL_COMPONENTS[4:]]
    frame["quality_components"] = frame[quality].notna().sum(axis=1)
    frame["growth_components"] = frame[growth].notna().sum(axis=1)
    frame["quality_score"] = frame[quality].mean(axis=1).where(
        frame["quality_components"].ge(2)
    )
    frame["conservative_growth_score"] = frame[growth].mean(axis=1).where(
        frame["growth_components"].ge(2)
    )
    cross_section = frame.groupby("date")["symbol"].transform("nunique")
    too_small = cross_section.lt(minimum_cross_section)
    frame.loc[too_small, ["quality_score", "conservative_growth_score"]] = np.nan
    return frame[[
        "date",
        "symbol",
        "sector",
        "available_at",
        "filing_age_days",
        "quality_score",
        "conservative_growth_score",
        "quality_components",
        "growth_components",
    ]]
