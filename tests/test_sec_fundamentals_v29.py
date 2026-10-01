import pandas as pd

from scripts.collect_sec_fundamentals_v29 import (
    build_filing_events,
    canonical_ticker,
    extract_company_facts,
    ticker_mapping,
)


def _fact(tag, value, filed, end, accession, start=None, fy=2022):
    item = {
        "val": value,
        "filed": filed,
        "end": end,
        "accn": accession,
        "form": "10-K",
        "fp": "FY",
        "fy": fy,
    }
    if start:
        item["start"] = start
    return {"label": tag, "units": {"USD": [item]}}


def test_ticker_mapping_normalizes_class_share_separator():
    payload = {
        "fields": ["cik", "name", "ticker", "exchange"],
        "data": [[1067983, "Berkshire Hathaway", "BRK-B", "NYSE"]],
    }
    candidates = pd.DataFrame(
        {"symbol": ["BRK.B"], "sector": ["Financials"], "name": ["Berkshire"]}
    )
    mapped = ticker_mapping(payload, candidates)
    assert canonical_ticker("brk.b") == "BRK-B"
    assert bool(mapped.loc[0, "mapped"])
    assert int(mapped.loc[0, "cik"]) == 1067983


def test_extract_and_build_events_use_filing_date_and_prior_annual_values():
    facts = {}
    for year, assets, revenue, income, cash in (
        (2021, 100, 80, 8, 10),
        (2022, 110, 100, 11, 15),
    ):
        accession = f"{year}-annual"
        filed = f"{year + 1}-02-15"
        end = f"{year}-12-31"
        start = f"{year}-01-01"
        facts.setdefault("Assets", {"label": "Assets", "units": {"USD": []}})["units"][
            "USD"
        ].append(
            {
                "val": assets,
                "filed": filed,
                "end": end,
                "accn": accession,
                "form": "10-K",
                "fp": "FY",
                "fy": year,
            }
        )
        for tag, value in (
            ("RevenueFromContractWithCustomerExcludingAssessedTax", revenue),
            ("NetIncomeLoss", income),
            ("NetCashProvidedByUsedInOperatingActivities", cash),
        ):
            facts.setdefault(tag, {"label": tag, "units": {"USD": []}})["units"][
                "USD"
            ].append(
                {
                    "val": value,
                    "filed": filed,
                    "start": start,
                    "end": end,
                    "accn": accession,
                    "form": "10-K",
                    "fp": "FY",
                    "fy": year,
                }
            )
    payload = {"cik": 1, "entityName": "Example", "facts": {"us-gaap": facts}}
    extracted = extract_company_facts(payload, "EXM", "Industrials")
    events = build_filing_events(extracted)
    latest = events.sort_values("filed").iloc[-1]
    assert latest["available_at"] == pd.Timestamp("2023-02-16")
    assert abs(latest["profitability"] - 0.10) < 1e-12
    assert abs(latest["accrual_quality"] - 4 / 110) < 1e-12
    assert abs(latest["asset_growth"] + 0.10) < 1e-12
    assert abs(latest["revenue_growth"] - 0.25) < 1e-12


def test_flow_facts_outside_annual_duration_are_rejected():
    payload = {
        "cik": 1,
        "entityName": "Example",
        "facts": {
            "us-gaap": {
                "NetIncomeLoss": _fact(
                    "NetIncomeLoss",
                    5,
                    "2023-02-15",
                    "2022-12-31",
                    "quarter",
                    start="2022-10-01",
                )
            }
        },
    }
    assert extract_company_facts(payload, "EXM", "Industrials").empty
