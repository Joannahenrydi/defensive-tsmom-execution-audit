import pandas as pd

from scripts.import_sharadar_sf1_v29 import normalize_sf1


def _candidate() -> pd.DataFrame:
    return pd.DataFrame({"symbol": ["BRK-B", "AAA"], "sector": ["Financials", "Industrials"]})


def test_sf1_import_uses_only_ary_and_delays_filing() -> None:
    source = pd.DataFrame(
        {
            "ticker": ["BRK.B", "BRK.B"],
            "dimension": ["ARY", "MRY"],
            "datekey": ["2022-02-28", "2022-02-28"],
            "reportperiod": ["2021-12-31", "2021-12-31"],
            "assets": [100.0, 999.0],
            "revenue": [80.0, 999.0],
            "gp": [40.0, 999.0],
            "netinc": [10.0, 999.0],
            "ncfo": [12.0, 999.0],
        }
    )
    events, summary = normalize_sf1(source, _candidate())
    assert summary["dimension"] == "ARY"
    assert len(events) == 1
    assert events.iloc[0]["symbol"] == "BRK-B"
    assert events.iloc[0]["assets"] == 100.0
    assert events.iloc[0]["available_at"] == pd.Timestamp("2022-03-01")


def test_sf1_import_rejects_duplicate_filing_vintage() -> None:
    row = {
        "ticker": "AAA",
        "dimension": "ARY",
        "datekey": "2022-03-01",
        "reportperiod": "2021-12-31",
        "assets": 100.0,
        "revenue": 80.0,
        "gp": 40.0,
        "netinc": 10.0,
        "ncfo": 12.0,
    }
    events, summary = normalize_sf1(pd.DataFrame([row, row]), _candidate())
    assert events.empty
    assert summary["reason"] == "DUPLICATE_SF1_VINTAGE"


def test_sf1_import_rejects_missing_datekey() -> None:
    source = pd.DataFrame(
        {
            "ticker": ["AAA"],
            "dimension": ["ARY"],
            "reportperiod": ["2021-12-31"],
            "assets": [100.0],
            "revenue": [80.0],
            "gp": [40.0],
            "netinc": [10.0],
            "ncfo": [12.0],
        }
    )
    events, summary = normalize_sf1(source, _candidate())
    assert events.empty
    assert summary["reason"] == "MISSING_SF1_COLUMNS"
    assert summary["missing_columns"] == ["datekey"]
