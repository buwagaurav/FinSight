import json

from app.ai import verify

SNAPSHOT = json.dumps({"source": "S1", "roe_pct": 48.7, "net_profit_cr": 49210.0,
                       "statements": {"source": "S2", "revenue_cr": 255324.0}})


def test_numbers_must_come_from_tools():
    assert verify.unverified_numbers("ROE was 48.7% and profit ₹49,210 Cr.", [SNAPSHOT]) == []
    assert verify.unverified_numbers("ROE was 52.3%.", [SNAPSHOT]) == ["52.3%"]


def test_years_small_counts_and_question_numbers_are_allowed():
    assert verify.unverified_numbers("Over 3 years to 2025 in FY25, P/E below 30", [SNAPSHOT], question="P/E below 30") == []


def test_citation_must_point_at_the_source_holding_the_number():
    assert verify.misattributed("ROE 48.7% [S1], revenue ₹2,55,324 Cr [S2]", [SNAPSHOT]) == []
    assert verify.misattributed("Revenue ₹2,55,324 Cr [S1]", [SNAPSHOT]) == ["₹2,55,324 Cr [S1]"]


def test_quotes_must_appear_in_the_cited_page():
    docs = json.dumps({"results": [{"source": "S3", "page": 12,
                                    "text": "We expect margins to stay within our 24-26% target band this year."}]})
    ok = 'Management said "margins to stay within our 24-26% target band" [S3].'
    bad = 'Management said "margins will expand sharply next year to 30%" [S3].'
    assert verify.unsupported_quotes(ok, [docs]) == []
    assert len(verify.unsupported_quotes(bad, [docs])) == 1


def test_arithmetic_recheck():
    assert verify.arithmetic_errors("Profit rose 16.8% from ₹42,147 Cr to ₹49,210 Cr.") == []
    assert len(verify.arithmetic_errors("Profit rose 25% from ₹42,147 Cr to ₹49,210 Cr.")) == 1
    assert verify.arithmetic_errors("Margin fell from 11% to 9%.") == []                   # percentage points
    assert verify.arithmetic_errors("Revenue grew 10% a year from ₹100 Cr in FY22 to ₹133.1 Cr in FY25.") == []
