import pandas as pd

from scripts.audit_sec_source_v29 import candidate_mapping_summary, schema_audit


def test_schema_audit_rejects_fact_rows_without_vintage() -> None:
    fundamentals = {
        "cik",
        "ticker",
        "metric",
        "fiscal_year",
        "fiscal_period",
        "end_date",
        "value",
        "unit",
        "quality",
    }
    filings = {"accession", "cik", "form", "report_date", "filed"}
    audit = schema_audit(fundamentals, filings)
    assert audit["fundamental_schema_present"]
    assert audit["filing_schema_present"]
    assert not audit["fact_rows_have_accession_and_filed"]
    assert not audit["point_in_time_reconstruction_possible"]
    assert audit["missing_fact_vintage_columns"] == ["accession", "filed"]


def test_schema_audit_accepts_accession_level_fact_vintage() -> None:
    fundamentals = {
        "cik",
        "ticker",
        "metric",
        "fiscal_year",
        "fiscal_period",
        "end_date",
        "value",
        "unit",
        "quality",
        "accession",
        "filed",
    }
    filings = {"accession", "cik", "form", "report_date", "filed"}
    assert schema_audit(fundamentals, filings)[
        "point_in_time_reconstruction_possible"
    ]


def test_candidate_mapping_excludes_ambiguous_current_tickers() -> None:
    candidates = pd.DataFrame({"symbol": ["BRK.B", "AAA", "DUP", "MISS"]})
    companies = pd.DataFrame(
        {"ticker": ["BRK-B", "AAA", "DUP", "DUP"], "cik": [1, 2, 3, 4]}
    )
    summary = candidate_mapping_summary(candidates, companies)
    assert summary["candidate_symbols"] == 4
    assert summary["uniquely_mapped_symbols"] == 2
    assert summary["ambiguous_symbols"] == 1
    assert not summary["mapping_gate_pass"]
