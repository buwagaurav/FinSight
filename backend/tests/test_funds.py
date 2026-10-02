"""Mutual funds from AMFI's daily NAV file: parsing, search and fund detail. No network: a small sample file."""
import pytest
from fastapi.testclient import TestClient

from app import funds, main
from app.providers import amfi

SAMPLE = """Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Plan;Option;Net Asset Value;Date

Open Ended Schemes(Equity Scheme - Flexi Cap Fund)

PPFAS Mutual Fund

122639;INF879O01027;-;Parag Parikh Flexi Cap Fund;Direct Plan;Growth;88.2569;01-Oct-2026
122640;INF879O01019;-;Parag Parikh Flexi Cap Fund;Regular Plan;Growth;80.3771;01-Oct-2026
153964;INF879O01AB1;INF879O01AB2;Parag Parikh Flexi Cap Fund;Direct Plan;IDCW;88.2569;01-Oct-2026

Open Ended Schemes(Equity Schemes - ELSS- Tax Saver Fund)

SBI Mutual Fund

119723;INF200K01T28;-;SBI ELSS Tax Saver Fund - Direct Plan - Growth;;;450.10;01-Oct-2026
105628;INF200K01495;INF200K01503;SBI ELSS Tax Saver Fund - Regular Plan - Income Distribution Cum Capital Withdrawal;;;80.20;01-Oct-2026
100001;-;-;UTI - Regular Saving Fund;;;30.00;01-Oct-2026

Close Ended Schemes(Income)

Old Mutual Fund

100002;INF000000001;-;Old FMP Series 1 - Growth;;;12.00;02-Jul-2018
100003;INF000000002;-;Broken Scheme - Growth;;;N.A.;01-Oct-2026
"""


@pytest.fixture
def sample(monkeypatch):
    rows = amfi.parse(SAMPLE)
    monkeypatch.setattr(amfi, "schemes", lambda: rows)
    return rows


def test_parse_reads_headers_plans_and_options(sample):
    by = {r["code"]: r for r in sample}
    assert 100003 not in by                                     # "N.A." NAV skipped
    assert by[122639]["house"] == "PPFAS Mutual Fund"
    assert (by[122639]["group"], by[122639]["category"]) == ("Equity Scheme", "Flexi Cap Fund")
    assert (by[119723]["group"], by[119723]["category"]) == ("Equity Scheme", "ELSS")   # spellings unified
    assert (by[119723]["plan"], by[119723]["option"], by[119723]["fund"]) == ("Direct", "Growth", "SBI ELSS Tax Saver Fund")
    assert (by[105628]["plan"], by[105628]["option"]) == ("Regular", "IDCW")
    assert by[100001]["fund"] == "UTI - Regular Saving Fund"    # "Regular" here is the fund's name, not the plan
    assert by[153964]["isins"] == ["INF879O01AB1", "INF879O01AB2"]


def test_search_filters_and_hides_inactive_schemes(sample):
    assert funds.search("parag")["total"] == 3
    assert funds.search("", category="ELSS", plan="Direct")["rows"][0]["code"] == 119723
    assert funds.search("old fmp")["total"] == 0                       # last NAV in 2018: inactive
    old = funds.search("old fmp", include_inactive=True)["rows"][0]
    assert old["active"] is False
    assert funds.search("122640")["rows"][0]["code"] == 122640           # a scheme code finds that scheme
    res = funds.search("")
    assert res["nav_date"] == "2026-10-01" and "Old Mutual Fund" not in res["facets"]["houses"]


def test_detail_groups_variants_and_compares_direct_with_regular(sample):
    d = funds.detail(122640)
    assert [v["code"] for v in d["variants"]] == [122639, 153964, 122640]   # Direct Growth first
    assert d["direct_vs_regular"]["direct_ahead_pct"] == pytest.approx((88.2569 / 80.3771 - 1) * 100)
    with pytest.raises(LookupError):
        funds.detail(999)


def test_fund_api(sample):
    c = TestClient(main.app)
    assert c.get("/api/funds", params={"q": "elss"}).json()["total"] == 2
    assert c.get("/api/funds/999").status_code == 404
    assert c.get("/api/funds", params={"plan": "Both"}).status_code == 422
