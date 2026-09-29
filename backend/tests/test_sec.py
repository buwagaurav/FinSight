"""US listings from SEC EDGAR, tested on hand-built EDGAR responses (no network)."""
import pytest

from app import research
from app.analytics import fundamentals
from app.ai import verify
from app.providers import sec, yahoo

TICKERS = {"ACME": {"cik": 1234, "name": "ACME WIDGETS CORP", "exchange": "NASDAQ"},
           "BRK-B": {"cik": 1067983, "name": "Berkshire Hathaway Inc", "exchange": "NYSE"},
           "ACMX": {"cik": 99, "name": "Acme Explorations Inc.", "exchange": "NYSE"}}


def flow(end, val, filed, start=None, form="10-K"):
    y = int(end[:4])
    return {"start": start or f"{y - 1}{end[4:]}", "end": end, "val": val, "filed": filed, "form": form}


def point(end, val, filed, form="10-K"):
    return {"end": end, "val": val, "filed": filed, "form": form}


def usd(*rows):
    return {"units": {"USD": list(rows)}}


FACTS = {"facts": {
    "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
        {"end": "2025-10-15", "val": 90e6}, {"end": "2026-01-20", "val": 100e6}, {"end": "2026-01-20", "val": 5e6}]}}},
    "us-gaap": {
        # older years reported under SalesRevenueNet, newer under the post-2018 concept
        "SalesRevenueNet": usd(flow("2021-09-30", 800e6, "2021-11-01")),
        "RevenueFromContractWithCustomerExcludingAssessedTax": usd(
            flow("2022-09-30", 900e6, "2022-11-01"),
            flow("2023-09-30", 1000e6, "2023-11-01"),
            flow("2023-09-30", 1010e6, "2024-11-01"),                              # restated a year later: wins
            flow("2024-09-30", 1100e6, "2024-11-01"),
            flow("2024-09-30", 280e6, "2024-11-01", start="2024-07-01"),            # a quarter inside the 10-K
            flow("2025-09-30", 1200e6, "2025-11-01"),
            flow("2026-06-30", 950e6, "2026-08-01", start="2025-10-01", form="10-Q")),
        "NetIncomeLoss": usd(*[flow(f"{y}-09-30", v, f"{y}-11-01") for y, v in
                               [(2021, 80e6), (2022, 90e6), (2023, 100e6), (2024, 110e6), (2025, 120e6)]]),
        "OperatingIncomeLoss": usd(flow("2025-09-30", 200e6, "2025-11-01")),
        "DepreciationDepletionAndAmortization": usd(flow("2025-09-30", 50e6, "2025-11-01")),
        "WeightedAverageNumberOfSharesOutstandingBasic": {"units": {"shares": [flow("2025-09-30", 100e6, "2025-11-01")]}},
        "StockholdersEquity": usd(point("2024-09-30", 500e6, "2024-11-01"), point("2025-09-30", 600e6, "2025-11-01")),
        "LongTermDebt": usd(point("2025-09-30", 150e6, "2025-11-01")),
        "CommercialPaper": usd(point("2025-09-30", 30e6, "2025-11-01")),
        "AssetsCurrent": usd(point("2025-09-30", 400e6, "2025-11-01")),
        "LiabilitiesCurrent": usd(point("2025-09-30", 250e6, "2025-11-01")),
        "NetCashProvidedByUsedInOperatingActivities": usd(flow("2025-09-30", 140e6, "2025-11-01")),
        "PaymentsToAcquirePropertyPlantAndEquipment": usd(flow("2025-09-30", 40e6, "2025-11-01")),
        "PaymentsOfDividends": usd(flow("2025-09-30", 25e6, "2025-11-01")),
    }}}

SUBMISSIONS = {"sic": "3571", "sicDescription": "ELECTRONIC COMPUTERS", "website": "",
               "filings": {"recent": {
                   "form": ["4", "8-K", "10-Q", "144"],
                   "accessionNumber": ["0001-26-000004", "0001-26-000003", "0001-26-000002", "0001-26-000001"],
                   "primaryDocument": ["form4.xml", "acme-8k.htm", "acme-10q.htm", "doc.xml"],
                   "primaryDocDescription": ["FORM 4", "8-K", "10-Q", "144"],
                   "items": ["", "2.02,9.01", "", ""],
                   "acceptanceDateTime": ["2026-09-24T22:30:07.000Z", "2026-07-30T20:30:28.000Z",
                                          "2026-07-31T10:01:02.000Z", "2026-07-01T10:00:00.000Z"],
                   "filingDate": ["2026-09-24", "2026-07-30", "2026-07-31", "2026-07-01"],
               }}}


@pytest.fixture
def edgar(monkeypatch):
    monkeypatch.setattr(sec, "tickers", lambda: TICKERS)
    monkeypatch.setattr(sec, "company_facts", lambda cik: FACTS)
    monkeypatch.setattr(sec, "submissions", lambda cik: SUBMISSIONS)


def test_symbols():
    assert sec.is_us("aapl.us") and not sec.is_us("TCS.NS")
    assert sec.ticker("BRK-B.US") == "BRK-B"
    assert yahoo.normalize_symbol("aapl.us") == "AAPL.US" and yahoo.normalize_symbol("tcs") == "TCS.NS"
    assert yahoo.yahoo_ticker("BRK-B.US") == "BRK-B" and yahoo.yahoo_ticker("TCS.NS") == "TCS.NS"


def test_search_ranks_exact_ticker_then_prefix_then_name(edgar):
    assert [r["symbol"] for r in sec.search("acme")] == ["ACME.US", "ACMX.US"]
    first = sec.search("ACME")[0]
    assert first == {"symbol": "ACME.US", "name": "Acme Widgets Corp", "exchange": "NASDAQ", "sector": None}
    assert [r["symbol"] for r in sec.search("berkshire")] == ["BRK-B.US"]
    assert sec.search("  ") == []


def test_lookup_unknown_ticker(edgar):
    with pytest.raises(LookupError):
        sec.lookup("NOPE.US")


def test_annual_statements_pick_full_years_latest_filing_and_last_five(edgar):
    st = sec.annual_statements("ACME.US")
    assert st["scale"] == sec.MILLION and st["converted_from"] is None
    assert sorted(st["income"]) == ["FY21", "FY22", "FY23", "FY24", "FY25"]      # named after the year they end
    assert st["income"]["FY21"]["Total Revenue"] == 800e6                          # older concept fills the gap
    assert st["income"]["FY23"]["Total Revenue"] == 1010e6                         # restated figure wins
    assert st["income"]["FY24"]["Total Revenue"] == 1100e6                         # not the quarter
    fy25 = {**st["income"]["FY25"], **st["balance"]["FY25"], **st["cashflow"]["FY25"]}
    assert fy25["EBITDA"] == 250e6 and fy25["EBIT"] == 200e6
    assert fy25["Total Debt"] == 180e6 and fy25["Working Capital"] == 150e6
    assert fy25["Capital Expenditure"] == -40e6 and fy25["Free Cash Flow"] == 100e6
    assert fy25["Cash Dividends Paid"] == -25e6
    assert not any(k.startswith("_") for k in fy25)


def test_statements_become_a_table_in_dollar_millions(edgar):
    table = fundamentals.build_table(sec.annual_statements("ACME.US"))
    last = table[-1]
    assert last["revenue"] == pytest.approx(1200) and last["net_profit"] == pytest.approx(120)
    assert last["eps"] == pytest.approx(1.2)                     # $120M / 100M shares, in dollars
    assert last["roe_pct"] == pytest.approx(120 / 550 * 100)
    assert fundamentals.growth_summary(table)["revenue_cagr_pct"] == pytest.approx(((1200 / 800) ** 0.25 - 1) * 100)


def test_shares_outstanding_sums_share_classes_on_latest_date(edgar):
    assert sec.shares_outstanding("ACME.US") == 105e6


def test_filings_are_labelled_and_routine_ones_flagged(edgar):
    rows = sec.filings("ACME.US")
    assert [r["category"] for r in rows] == ["4", "8-K: Current report", "10-Q: Quarterly report", "144"]
    assert [r["routine"] for r in rows] == [True, False, False, True]
    eight_k = rows[1]
    assert eight_k["text"] == "Results"
    assert eight_k["published"] == "2026-07-30T20:30:28+00:00"
    assert eight_k["pdf_url"] == "https://www.sec.gov/Archives/edgar/data/1234/000126000003/acme-8k.htm"
    assert eight_k["symbol"] == "ACME.US"


def test_html_text_keeps_visible_text_only():
    html = (b"<html><head><title>x</title><style>p{}</style></head><body><ix:header>hidden</ix:header>"
            b"<p>Revenue&nbsp;rose&amp;grew</p><div>Second   line</div><script>var a</script></body></html>")
    assert sec.html_text(html) == "Revenue rose&grew\nSecond line"


def test_only_sec_archive_documents_are_fetched():
    with pytest.raises(ValueError):
        sec.download_document("https://evil.example.com/Archives/x.htm")


def test_us_company_report_without_yahoo(edgar, monkeypatch):
    def blocked(symbol):
        raise RuntimeError("Yahoo refused the request")
    monkeypatch.setattr(yahoo, "profile", blocked)
    monkeypatch.setattr(yahoo, "price_history", blocked)
    r = research.company_report("acme.us")
    p = r["profile"]
    assert (p["symbol"], p["name"], p["exchange"], p["currency"], p["price"]) == ("ACME.US", "Acme Widgets Corp", "NASDAQ", "USD", None)
    assert p["sector"] == "Technology" and p["industry"] == "Electronic Computers"
    assert r["financials"]["unit"] == "$ M (EPS in $)"
    assert r["financials"]["source"]["name"] == "SEC EDGAR (10-K filings)"
    assert "Yahoo Finance are unavailable" in r["financials"]["data_checks"][0]
    assert r["financials"]["years"][-1]["revenue"] == pytest.approx(1200)
    assert r["scores"]["overall"]["score"] is not None


def test_us_company_without_10k_still_gets_a_page(edgar, monkeypatch):
    monkeypatch.setattr(sec, "company_facts", lambda cik: {"facts": {}})
    monkeypatch.setattr(yahoo, "profile", lambda s: {**research._us_profile_from_sec(s), "price": 10.0})
    monkeypatch.setattr(yahoo, "price_history", lambda s: [])
    r = research.company_report("ACME.US")
    assert r["financials"]["years"] == [] and "20-F" in r["financials"]["data_checks"][0]


def test_bond_hurdle_follows_the_market():
    from app.analytics import scores
    table = [{"year": "FY25", "roe_pct": 20}]
    def reason(currency):
        out = scores.compute({"currency": currency, "pe": 20}, table, {"years": 1}, {}, [])
        return next(r["text"] for r in out["cards"]["valuation"]["reasons"] if "Earnings yield" in r["text"])
    assert reason("USD").endswith("~4% on 10-year government bonds")
    assert reason("INR").endswith("~7% on 10-year government bonds")


def test_verifier_understands_dollar_units():
    tool = ['{"source": "S1", "revenue": 416161.0, "market_cap_cr": 4940422.0, "net_profit": 112010.0}']
    assert verify.unverified_numbers("Revenue was $416.2 B and profit $112,010 M [S1].", tool) == []
    assert verify.unverified_numbers("Market value is about $4.94 trillion.", tool) == []
    assert verify.unverified_numbers("Revenue was $450 B.", tool) == ["$450 B"]
    assert verify.arithmetic_errors("Revenue grew 12.9% from $368.6 B to $416.2 B.") == []
    assert len(verify.arithmetic_errors("Revenue grew 30% from $368.6 B to $416.2 B.")) == 1


def test_share_counts_are_put_on_the_latest_split_basis(edgar, monkeypatch):
    def shares(end, val, filed, accn):
        return {**flow(end, val, filed), "accn": accn}
    facts = {"facts": {"us-gaap": {**FACTS["facts"]["us-gaap"],
        "WeightedAverageNumberOfSharesOutstandingBasic": {"units": {"shares": [
            # report filed 2023 (before a 10-for-1 split): FY21-FY23 on the old basis
            shares("2021-09-30", 2.4e9, "2023-11-01", "r2023"), shares("2022-09-30", 2.5e9, "2023-11-01", "r2023"),
            shares("2023-09-30", 2.5e9, "2023-11-01", "r2023"),
            # reports filed after the split restate their prior years x10
            shares("2023-09-30", 25e9, "2024-11-01", "r2024"), shares("2024-09-30", 24.6e9, "2024-11-01", "r2024"),
            shares("2024-09-30", 24.6e9, "2025-11-01", "r2025"), shares("2025-09-30", 24.4e9, "2025-11-01", "r2025"),
        ]}}}}}
    monkeypatch.setattr(sec, "company_facts", lambda cik: facts)
    st = sec.annual_statements("ACME.US")
    got = {fy: st["income"][fy]["Basic Average Shares"] for fy in st["income"]}
    assert got["FY25"] == 24.4e9 and got["FY24"] == 24.6e9 and got["FY23"] == pytest.approx(25e9)
    assert got["FY22"] == pytest.approx(25e9) and got["FY21"] == pytest.approx(24e9)    # scaled x10 via FY23 overlap


def test_us_quote_is_rebuilt_from_price_history_when_yahoo_quote_fails(edgar, monkeypatch):
    def refused(symbol):
        raise LookupError(symbol)   # what yfinance's quote does when Yahoo blocks the server
    monkeypatch.setattr(yahoo, "profile", refused)
    closes = [10.0] * 250 + [11.0, 12.0]
    monkeypatch.setattr(yahoo, "price_history", lambda s: [{"date": f"d{i:04d}", "close": c, "volume": 1} for i, c in enumerate(closes)])
    monkeypatch.setattr(sec, "ttm_net_income", lambda facts: (126e6, "2026-06-30"))
    p = research.company_report("ACME.US")["profile"]
    assert p["price"] == 12.0 and p["change_pct"] == pytest.approx((12 / 11 - 1) * 100)
    assert (p["week52_low"], p["week52_high"]) == (10.0, 12.0)
    mcap = 12 * 105e6 / 1e6                                       # price x SEC share count, $M
    assert p["market_cap_cr"] == pytest.approx(mcap)
    assert p["pe"] == pytest.approx(12 / (126e6 / 105e6))
    assert p["pb"] == pytest.approx(mcap / 600)
    assert p["roe_ttm_pct"] == pytest.approx(126 / 600 * 100)
    assert p["debt_to_equity_ttm"] == pytest.approx(180 / 600)
    assert p["dividend_yield_pct"] == pytest.approx(25 / mcap * 100)
    checks = research.company_report("ACME.US")["financials"]["data_checks"]
    assert checks[0].startswith("Yahoo's live quote is unavailable right now")


def test_share_count_uses_the_freshest_reliable_source():
    def facts(dei=None, **gaap_shares):
        gaap = {"NetIncomeLoss": {"units": {"USD": [flow("2026-06-30", 1e9, "2026-08-01", start="2025-07-01", form="10-Q")]}}}
        for concept, rows in gaap_shares.items():
            gaap[concept] = {"units": {"shares": rows}}
        out = {"facts": {"us-gaap": gaap}}
        if dei:
            out["facts"]["dei"] = {"EntityCommonStockSharesOutstanding": {"units": {"shares": dei}}}
        return out
    point = lambda end, val: {"end": end, "val": val, "filed": end, "form": "10-Q"}
    # several share classes reported per class only: no cover total, use the balance-sheet figure
    assert sec.shares_from_facts(facts(CommonStockSharesOutstanding=[point("2026-06-30", 12.2e9)])) == 12.2e9
    # then the latest average share count
    assert sec.shares_from_facts(facts(WeightedAverageNumberOfSharesOutstandingBasic=[
        {**flow("2026-06-30", 2.4e9, "2026-08-01", start="2026-04-01", form="10-Q")}])) == 2.4e9
    # stale figures (years before the latest report) are ignored rather than trusted
    assert sec.shares_from_facts(facts(dei=[point("2011-04-29", 941_481)])) is None


def test_foreign_filers_get_no_market_cap_from_mismatched_share_counts(edgar, monkeypatch):
    monkeypatch.setattr(sec, "company_facts", lambda cik: {"facts": {"dei": FACTS["facts"]["dei"]}})   # no 10-K data
    monkeypatch.setattr(yahoo, "profile", lambda s: (_ for _ in ()).throw(LookupError(s)))
    monkeypatch.setattr(yahoo, "price_history", lambda s: [{"date": "d1", "close": 450.0, "volume": 1}])
    p = research.company_report("ACME.US")["profile"]
    assert p["price"] == 450.0 and p["market_cap_cr"] is None and p["pe"] is None
