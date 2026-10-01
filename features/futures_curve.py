"""Causal futures-curve construction for contract-level trend and carry research."""

from __future__ import annotations

import numpy as np
import pandas as pd

REQUIRED_DAILY = {
    "date",
    "root",
    "contract",
    "settlement",
    "volume",
    "open_interest",
}
REQUIRED_METADATA = {
    "root",
    "contract",
    "expiry_date",
    "first_notice_date",
    "last_trade_date",
    "cash_settled",
}


def _require_columns(frame: pd.DataFrame, required: set[str], label: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"{label} missing columns: {','.join(missing)}")


def contract_curve(
    daily: pd.DataFrame,
    metadata: pd.DataFrame,
    roll_buffer_days: int = 5,
) -> pd.DataFrame:
    """Select the first two eligible expiries and calculate direction-corrected carry.

    A positive value means backwardation and therefore positive curve carry for a long
    position. Physically delivered contracts without a first-notice date are excluded.
    Prices observed on a date are signals for positions entered no earlier than the next
    session.
    """
    _require_columns(daily, REQUIRED_DAILY, "daily")
    _require_columns(metadata, REQUIRED_METADATA, "metadata")
    if roll_buffer_days < 0:
        raise ValueError("roll_buffer_days must be nonnegative")

    prices = daily.copy()
    contracts = metadata.copy()
    prices["date"] = pd.to_datetime(prices["date"], errors="coerce").dt.normalize()
    for column in ("expiry_date", "first_notice_date", "last_trade_date"):
        contracts[column] = pd.to_datetime(contracts[column], errors="coerce").dt.normalize()
    contracts["cash_settled"] = contracts["cash_settled"].fillna(False).astype(bool)
    contracts["roll_deadline"] = contracts["last_trade_date"]
    physical = ~contracts["cash_settled"]
    contracts.loc[physical, "roll_deadline"] = contracts.loc[physical, [
        "first_notice_date",
        "last_trade_date",
    ]].min(axis=1)
    contracts.loc[physical & contracts["first_notice_date"].isna(), "roll_deadline"] = pd.NaT
    contracts["last_eligible_date"] = contracts["roll_deadline"] - pd.offsets.BDay(
        roll_buffer_days
    )

    merged = prices.merge(
        contracts[[
            "root",
            "contract",
            "expiry_date",
            "last_eligible_date",
            "cash_settled",
        ]],
        on=["root", "contract"],
        how="inner",
        validate="many_to_one",
    )
    merged["settlement"] = pd.to_numeric(merged["settlement"], errors="coerce")
    merged = merged.loc[
        merged["date"].notna()
        & merged["expiry_date"].notna()
        & merged["last_eligible_date"].notna()
        & merged["settlement"].gt(0)
        & merged["date"].lt(merged["last_eligible_date"])
    ].copy()
    merged = merged.sort_values(
        ["date", "root", "expiry_date", "contract"], kind="stable"
    )
    merged["curve_rank"] = merged.groupby(["date", "root"]).cumcount() + 1
    first_two = merged.loc[merged["curve_rank"].le(2)].copy()

    values = [
        "contract",
        "settlement",
        "expiry_date",
        "volume",
        "open_interest",
    ]
    front = first_two.loc[first_two["curve_rank"].eq(1), ["date", "root", *values]].rename(
        columns={value: f"front_{value}" for value in values}
    )
    nxt = first_two.loc[first_two["curve_rank"].eq(2), ["date", "root", *values]].rename(
        columns={value: f"next_{value}" for value in values}
    )
    curve = front.merge(nxt, on=["date", "root"], how="left", validate="one_to_one")
    tenor_days = (curve["next_expiry_date"] - curve["front_expiry_date"]).dt.days
    valid = (
        curve["front_settlement"].gt(0)
        & curve["next_settlement"].gt(0)
        & tenor_days.gt(0)
    )
    curve["tenor_days"] = tenor_days
    curve["carry_annualized"] = np.nan
    curve.loc[valid, "carry_annualized"] = (
        np.log(
            curve.loc[valid, "front_settlement"]
            / curve.loc[valid, "next_settlement"]
        )
        * 365.25
        / tenor_days.loc[valid]
    )
    return curve.sort_values(["date", "root"]).reset_index(drop=True)


def held_contract_returns(curve: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    """Calculate next-session returns on the contract selected at the prior close.

    On roll dates this uses the new contract's prior and current settlement. It therefore
    excludes the artificial jump between two different contract price levels.
    """
    required_curve = {"date", "root", "front_contract", "front_settlement"}
    _require_columns(curve, required_curve, "curve")
    _require_columns(daily, {"date", "root", "contract", "settlement"}, "daily")
    selection = curve[["date", "root", "front_contract"]].copy()
    selection["date"] = pd.to_datetime(selection["date"], errors="coerce").dt.normalize()
    selection = selection.sort_values(["root", "date"])
    selection["held_contract"] = selection.groupby("root")["front_contract"].shift(1)
    selection["previous_date"] = selection.groupby("root")["date"].shift(1)

    settlements = daily[["date", "root", "contract", "settlement"]].copy()
    settlements["date"] = pd.to_datetime(settlements["date"], errors="coerce").dt.normalize()
    settlements["settlement"] = pd.to_numeric(settlements["settlement"], errors="coerce")
    current = selection.merge(
        settlements.rename(columns={"contract": "held_contract", "settlement": "current_price"}),
        on=["date", "root", "held_contract"],
        how="left",
        validate="one_to_one",
    )
    previous_prices = settlements.rename(
        columns={
            "date": "previous_date",
            "contract": "held_contract",
            "settlement": "previous_price",
        }
    ).copy()
    current = current.merge(
        previous_prices,
        on=["previous_date", "root", "held_contract"],
        how="left",
        validate="one_to_one",
    )
    current["excess_return"] = current["current_price"].div(current["previous_price"]).sub(1)
    current["roll_trade"] = current["front_contract"].ne(current["held_contract"])
    current.loc[current["held_contract"].isna(), "roll_trade"] = False
    return current[[
        "date",
        "root",
        "held_contract",
        "excess_return",
        "roll_trade",
    ]]


def root_signal_panel(
    curve: pd.DataFrame,
    returns: pd.DataFrame,
    min_history: int = 126,
) -> pd.DataFrame:
    """Build frozen 3/6/12-month trend and causal standardized carry scores."""
    if min_history <= 1:
        raise ValueError("min_history must exceed one session")
    ret = returns.pivot(index="date", columns="root", values="excess_return").sort_index()
    log_return = np.log1p(ret)
    trend_parts = []
    for horizon, weight in ((63, 0.25), (126, 0.35), (252, 0.40)):
        lookback = horizon - 21
        momentum = log_return.shift(21).rolling(
            lookback, min_periods=lookback
        ).sum()
        trend_parts.append(weight * momentum)
    trend = sum(trend_parts)
    prior_vol = ret.rolling(60, min_periods=40).std().shift(1) * np.sqrt(252)
    trend = trend.div(prior_vol.clip(lower=0.08))

    carry = curve.pivot(index="date", columns="root", values="carry_annualized").sort_index()
    carry_mean = carry.rolling(252, min_periods=min_history).mean().shift(1)
    carry_std = carry.rolling(252, min_periods=min_history).std(ddof=0).shift(1)
    carry_z = carry.sub(carry_mean).div(carry_std.replace(0, np.nan)).clip(-5, 5)

    records = []
    for date in sorted(set(trend.index).intersection(carry_z.index)):
        for root in sorted(set(trend.columns).intersection(carry_z.columns)):
            records.append({
                "date": date,
                "root": root,
                "trend_score": trend.at[date, root],
                "carry_score": carry_z.at[date, root],
                "prior_volatility": prior_vol.at[date, root],
            })
    return pd.DataFrame(records)
