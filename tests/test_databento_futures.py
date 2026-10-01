import pandas as pd

from scripts.collect_databento_futures import normalize_root_frames, request_costs


def _definitions() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts_recv": pd.to_datetime(["2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z"]),
            "instrument_id": [1, 2],
            "raw_symbol": ["ESH4", "ESM4"],
            "instrument_class": ["F", "F"],
            "security_update_action": ["A", "A"],
            "expiration": pd.to_datetime(["2024-03-15T13:30:00Z", "2024-06-21T13:30:00Z"]),
            "min_price_increment": [0.25, 0.25],
            "unit_of_measure_qty": [50.0, 50.0],
            "contract_multiplier": [1.0, 1.0],
            "exchange": ["XCME", "XCME"],
            "currency": ["USD", "USD"],
        }
    )


def test_normalizer_keeps_expiry_specific_contracts_and_official_stats() -> None:
    bars = pd.DataFrame(
        {
            "ts_event": pd.to_datetime(["2024-01-02T00:00:00Z", "2024-01-02T00:00:00Z"]),
            "instrument_id": [1, 2],
            "open": [4800.0, 4820.0],
            "high": [4810.0, 4830.0],
            "low": [4790.0, 4810.0],
            "close": [4805.0, 4825.0],
            "volume": [1000, 500],
        }
    )
    rows = []
    for instrument_id, settlement, volume, oi in [(1, 4806.0, 1100, 2000), (2, 4826.0, 550, 900)]:
        for stat_type, price, quantity in [
            (3, settlement, 0),
            (6, 0.0, volume),
            (9, 0.0, oi),
        ]:
            rows.append(
                {
                    "ts_recv": pd.Timestamp("2024-01-02T22:00:00Z"),
                    "ts_ref": pd.Timestamp("2024-01-02T00:00:00Z"),
                    "instrument_id": instrument_id,
                    "stat_type": stat_type,
                    "price": price,
                    "quantity": quantity,
                }
            )
    daily, metadata, history = normalize_root_frames(
        "ES", _definitions(), bars, pd.DataFrame(rows)
    )
    assert set(daily["contract"]) == {"ESH4", "ESM4"}
    assert daily.set_index("contract").loc["ESH4", "settlement"] == 4806.0
    assert daily.set_index("contract").loc["ESH4", "volume"] == 1100
    assert metadata["cash_settled"].all()
    assert metadata["first_notice_date"].isna().all()
    assert len(history) == 2


def test_physical_contract_requires_notice_calendar() -> None:
    definitions = _definitions().assign(raw_symbol=["ZNH4", "ZNM4"])
    bars = pd.DataFrame(
        {
            "ts_event": pd.to_datetime(["2024-01-02T00:00:00Z"]),
            "instrument_id": [1],
            "open": [110.0],
            "high": [111.0],
            "low": [109.0],
            "close": [110.5],
            "volume": [100],
        }
    )
    stats = pd.DataFrame(
        {
            "ts_recv": pd.to_datetime(["2024-01-02T22:00:00Z"] * 3),
            "ts_ref": pd.to_datetime(["2024-01-02T00:00:00Z"] * 3),
            "instrument_id": [1, 1, 1],
            "stat_type": [3, 6, 9],
            "price": [110.5, 0.0, 0.0],
            "quantity": [0, 100, 200],
        }
    )
    _, metadata, _ = normalize_root_frames("ZN", definitions, bars, stats)
    assert not metadata["cash_settled"].any()
    assert metadata["first_notice_date"].isna().all()


def test_cost_estimate_sums_all_required_schemas() -> None:
    class Metadata:
        def get_cost(self, **kwargs):
            return {"definition": 1.0, "ohlcv-1d": 2.0, "statistics": 3.0}[kwargs["schema"]]

    class Client:
        metadata = Metadata()

    result = request_costs(Client(), ["ES", "ZN"], "2020-01-01", "2021-01-01")
    assert result == {"definition": 1.0, "ohlcv-1d": 2.0, "statistics": 3.0, "total": 6.0}
