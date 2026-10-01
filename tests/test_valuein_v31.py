import pandas as pd

from scripts.collect_valuein_v31 import (
    _security_mapping,
    _total_size,
    build_daily_membership,
    endpoint,
    normalize_fundamental_events,
    valuein_data_gate,
)


def _mapping() -> pd.DataFrame:
    references = pd.DataFrame(
        {"security_id": [10], "cik": ["0001"], "sector": ["Industrials"]}
    )
    security = pd.DataFrame(
        {
            "id": [10],
            "entity_id": [1],
            "symbol": ["AAA"],
            "valid_from": ["2010-01-01"],
            "valid_to": [None],
            "is_primary_ticker": [True],
        }
    )
    return _security_mapping(references, security)


def test_valuein_endpoints_separate_public_sample_and_authenticated_plan() -> None:
    assert endpoint("sample", "fact").endswith("/v1/sample/fact")
    assert endpoint("sp500", "fact").endswith("/v1/sp500/fact")
    assert _total_size("bytes 0-0/264381418") == 264381418


def test_valuein_events_use_as_filed_value_and_next_business_day() -> None:
    rows = []
    for concept, value in {
        "TotalAssets": 100.0,
        "TotalRevenue": 80.0,
        "GrossProfit": 40.0,
        "NetIncome": 10.0,
        "OperatingCashFlow": 12.0,
    }.items():
        rows.append(
            {
                "fact_id": concept,
                "entity_id": 1,
                "accession_id": "A1",
                "standard_concept": concept,
                "priority": 1,
                "value_as_filed": value,
                "unit": "USD",
                "period_start": "2021-01-01" if concept != "TotalAssets" else None,
                "period_end": "2021-12-31",
                "fiscal_year": 2021,
                "fiscal_period": "FY",
                "accepted_at": "2022-02-25T21:00:00Z",
                "period_span_days": 364 if concept != "TotalAssets" else None,
                "restated": False,
            }
        )
    filings = pd.DataFrame(
        {
            "entity_id": [1],
            "accession_id": ["A1"],
            "filing_date": ["2022-02-25"],
            "form_type": ["10-K"],
            "is_amendment": [False],
            "accepted_at": ["2022-02-25T21:00:00Z"],
            "report_date": ["2021-12-31"],
        }
    )
    events = normalize_fundamental_events(pd.DataFrame(rows), filings, _mapping())
    assert len(events) == 1
    assert events.iloc[0]["assets"] == 100.0
    assert events.iloc[0]["availability_date"] == pd.Timestamp("2022-02-28")
    assert events.iloc[0]["profitability"] == 0.10


def test_membership_respects_effective_and_removal_dates() -> None:
    membership = pd.DataFrame(
        {
            "cik": ["0001"],
            "index_name": ["SP500"],
            "effective_date": ["2022-01-03"],
            "removal_date": ["2022-01-05"],
        }
    )
    sessions = pd.DatetimeIndex(["2022-01-03", "2022-01-04", "2022-01-05"])
    daily = build_daily_membership(membership, _mapping(), sessions)
    assert set(daily["date"]) == {pd.Timestamp("2022-01-03"), pd.Timestamp("2022-01-04")}


def test_incomplete_sample_history_fails_formal_gate() -> None:
    events = pd.DataFrame(
        {
            "entity_id": [1],
            "accession_id": ["A1"],
            "availability_date": [pd.Timestamp("2022-02-28")],
        }
    )
    membership = pd.DataFrame(
        {
            "date": [pd.Timestamp("2022-02-28")],
            "cik": ["0001"],
            "entity_id": [1],
            "sector": ["Industrials"],
        }
    )
    result = valuein_data_gate(events, membership)
    assert result["status"] == "V31_BLOCKED_PIT_DATA"
    assert not all(result["components"].values())
