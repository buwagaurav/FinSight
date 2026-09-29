"""The US screener pipeline end to end on fake SEC and Yahoo responses: universe, sectors, bulk statements,
batched prices, metrics, and screening by market."""
import io
import json
import zipfile

import pandas as pd
import pytest

from app import screener, us_market, watchlist
from app.providers import sec
from tests.test_sec import FACTS, flow

TICKERS = {  # SEC lists a company once per share class; the first one (main class) is kept
    "ACME": {"cik": 1234, "name": "ACME WIDGETS CORP", "exchange": "NASDAQ"},
    "ACME-B": {"cik": 1234, "name": "ACME WIDGETS CORP", "exchange": "NASDAQ"},
    "BANK": {"cik": 55, "name": "First Bank Corp", "exchange": "NYSE"},
    "SPAC": {"cik": 66, "name": "Blank Check Acquisition Corp", "exchange": "NASDAQ"},
    "FUND": {"cik": 77, "name": "Some Income Fund", "exchange": "NYSE"},
}
SUBMISSIONS = {1234: {"sic": "3571", "sicDescription": "ELECTRONIC COMPUTERS", "entityType": "operating"},
               55: {"sic": "6021", "sicDescription": "NATIONAL COMMERCIAL BANKS", "entityType": "operating"},
               66: {"sic": "6770", "sicDescription": "BLANK CHECKS", "entityType": "operating"},
               77: {"sic": "", "entityType": "other"}}


def bank_facts():
    gaap = {"Revenues": {"units": {"USD": [flow(f"{y}-12-31", v, f"{y + 1}-02-20") for y, v in [(2024, 500e6), (2025, 600e6)]]}},
            "NetIncomeLoss": {"units": {"USD": [flow(f"{y}-12-31", v, f"{y + 1}-02-20") for y, v in [(2024, 100e6), (2025, 150e6)]]}},
            "StockholdersEquity": {"units": {"USD": [{"end": "2025-12-31", "val": 1000e6, "filed": "2026-02-20", "form": "10-K"}]}}}
    return {"facts": {"us-gaap": gaap, "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [{"end": "2026-02-01", "val": 50e6}]}}}}}


class Response:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_content(self, chunk_size):
        yield self.body


@pytest.fixture
def us(clean_db, monkeypatch):
    subs = io.BytesIO()
    with zipfile.ZipFile(subs, "w") as z:
        for cik, body in SUBMISSIONS.items():
            z.writestr(f"CIK{cik:010d}.json", json.dumps(body))
            z.writestr(f"CIK{cik:010d}-submissions-001.json", json.dumps({"filings": []}))   # overflow page: ignored
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("CIK0000001234.json", json.dumps(FACTS))
        z.writestr("CIK0000000055.json", json.dumps(bank_facts()))
        z.writestr("CIK0000000066.json", json.dumps(FACTS))      # the SPAC: must be skipped
        z.writestr("CIK0000009999.json", json.dumps(FACTS))      # not listed: must be skipped
    downloads = []

    def get(url, **kw):
        downloads.append(url)
        return Response(subs.getvalue() if url == us_market.BULK_SUBMISSIONS else buf.getvalue())

    def download(tickers, **kw):
        idx = pd.to_datetime(["2026-09-25", "2026-09-28"])
        prices = {"ACME": [11.0, 12.0], "BANK": [40.0, 39.0]}
        cols = pd.MultiIndex.from_product([tickers, ["Close"]])
        return pd.DataFrame([[prices.get(t, [float("nan")] * 2)[i] for t in tickers] for i in range(2)], index=idx, columns=cols)

    monkeypatch.setattr(sec, "tickers", lambda: TICKERS)
    monkeypatch.setattr(sec.submissions, "__wrapped__", lambda cik: SUBMISSIONS[cik])
    monkeypatch.setattr(sec, "_get", get)
    import yfinance
    monkeypatch.setattr(yfinance, "download", download)
    return downloads


def test_full_refresh_builds_a_us_screener(us, clean_db):
    us_market.run(log=lambda *_: None)
    assert us == [us_market.BULK_FACTS]                      # one bulk download, no per-company requests
    companies = {r["symbol"]: r for r in clean_db.fetch_all("SELECT * FROM us_companies")}
    assert set(companies) == {"ACME.US", "BANK.US", "SPAC.US", "FUND.US"}   # one row per company
    assert companies["ACME.US"]["sector"] == "Technology" and companies["BANK.US"]["sector"] == "Financial Services"
    stored = {r["symbol"] for r in clean_db.fetch_all("SELECT symbol FROM us_statements")}
    assert stored == {"ACME.US", "BANK.US"}                  # shells and funds aren't screened

    rows = {r["symbol"]: r for r in screener.run([], market="US")["rows"]}
    acme = rows["ACME.US"]
    assert acme["price"] == 12.0
    assert acme["market_cap_cr"] == pytest.approx(12 * 105e6 / 1e6)          # price x cover-page shares, $M
    assert acme["roe_pct"] == pytest.approx(120 / 550 * 100)
    assert acme["dividend_yield_pct"] == pytest.approx(25 / (12 * 105e6 / 1e6) * 100)
    bank = rows["BANK.US"]
    assert bank["pe"] == pytest.approx(39 / (150e6 / 50e6))                  # price / trailing EPS
    assert bank["roce_pct"] is None and bank["debt_to_equity"] is None       # not meaningful for banks

    out = screener.run([{"field": "pe", "op": "<", "value": 20}], market="US", sectors=["Financial Services"])
    assert [r["symbol"] for r in out["rows"]] == ["BANK.US"]
    assert out["universe"] == "2 of 2 US stocks loaded"   # the shell company isn't counted and out["market"] == "US"


def test_daily_run_skips_statements_until_they_are_a_week_old(us, clean_db):
    us_market.run(log=lambda *_: None)
    us.clear()
    us_market.run(log=lambda *_: None)
    assert us == []                                          # prices only
    clean_db.execute("UPDATE us_statements SET updated_at = now() - interval '8 days'")
    us_market.run(log=lambda *_: None)
    assert us == [us_market.BULK_FACTS]


def test_markets_are_screened_separately(us, clean_db):
    from tests.conftest import add_company
    add_company(clean_db, "TCS", "TCS", market_cap_cr=750000)
    us_market.run(log=lambda *_: None)
    assert [r["symbol"] for r in screener.run([])["rows"]] == ["TCS.NS"]
    assert "TCS.NS" not in [r["symbol"] for r in screener.run([], market="US")["rows"]]
    assert "promoter_holding_pct" not in screener.fields("US")
    assert screener.fields("US")["market_cap_cr"] == "Market cap ($ M)"
    with pytest.raises(ValueError):
        screener.run([{"field": "promoter_holding_pct", "op": ">", "value": 50}], market="US")


def test_trailing_twelve_month_earnings():
    facts = {"facts": {"us-gaap": {"NetIncomeLoss": {"units": {"USD": [
        flow("2025-09-30", 120e6, "2025-11-01"),
        {**flow("2026-06-30", 100e6, "2026-08-01", start="2025-10-01", form="10-Q"), "accn": "q3"},   # 9 months
        {**flow("2025-06-30", 90e6, "2026-08-01", start="2024-10-01", form="10-Q"), "accn": "q3"},    # same 9m, prior year
        {**flow("2026-06-30", 40e6, "2026-08-01", start="2026-04-01", form="10-Q"), "accn": "q3"},    # the quarter alone
    ]}}}}}
    assert sec.ttm_net_income(facts) == (120e6 + 100e6 - 90e6, "2026-06-30")
    only_annual = {"facts": {"us-gaap": {"NetIncomeLoss": {"units": {"USD": [flow("2025-09-30", 120e6, "2025-11-01")]}}}}}
    assert sec.ttm_net_income(only_annual) == (120e6, "2025-09-30")


def test_watchlists_have_a_limit_per_market(clean_db, monkeypatch):
    from tests.conftest import add_company
    monkeypatch.setattr(watchlist, "LIMIT", 1)
    monkeypatch.setattr(sec, "tickers", lambda: TICKERS)
    add_company(clean_db, "TCS", "TCS")
    add_company(clean_db, "INFY", "Infosys")
    user = {"sub": "u1"}
    watchlist.add(user, "TCS")
    watchlist.add(user, "ACME.US")                          # the US list has its own room
    with pytest.raises(Exception) as e:
        watchlist.add(user, "INFY")
    assert "Indian watchlist is full" in str(e.value.detail)
    with pytest.raises(Exception) as e:
        watchlist.add(user, "BANK.US")
    assert "US watchlist is full" in str(e.value.detail)
    markets = {i["base"]: i["market"] for i in watchlist.listing(user)["items"]}
    assert markets == {"TCS": "IN", "ACME.US": "US"}


def test_us_pages_fall_back_to_stored_data(us, clean_db, monkeypatch):
    from app import research
    from app.providers import yahoo
    us_market.run(log=lambda *_: None)

    def down(*a, **kw):
        raise RuntimeError("unreachable")
    monkeypatch.setattr(yahoo, "profile", down)
    monkeypatch.setattr(yahoo, "price_history", down)
    monkeypatch.setattr(sec, "company_facts", down)            # SEC down too (the ticker list is cached)
    monkeypatch.setattr(sec, "industry", lambda s: {"sector": "Technology", "industry": "Computers", "website": None, "sic": 3571})
    r = research.company_report("ACME.US")
    p = r["profile"]
    assert p["price"] == 12.0 and p["change_pct"] == pytest.approx((12 / 11 - 1) * 100)
    assert p["market_cap_cr"] == pytest.approx(12 * 105e6 / 1e6)
    checks = " ".join(r["financials"]["data_checks"])
    assert "28 Sep 2026 closing price" in checks and "statements are from FinSight's last refresh" in checks
    assert r["financials"]["years"][-1]["revenue"] == pytest.approx(1200)


def test_first_run_reads_sectors_from_the_bulk_file(us, clean_db, monkeypatch):
    monkeypatch.setattr(us_market, "BULK_SECTORS_ABOVE", 2)       # 4 companies without sectors > 2: bulk
    monkeypatch.setattr(sec.submissions, "__wrapped__", lambda cik: pytest.fail("no per-company requests expected"))
    us_market.run(log=lambda *_: None)
    assert us == [us_market.BULK_SUBMISSIONS, us_market.BULK_FACTS]
    sectors = {r["symbol"]: r["sector"] for r in clean_db.fetch_all("SELECT symbol, sector FROM us_companies")}
    assert sectors["ACME.US"] == "Technology" and sectors["BANK.US"] == "Financial Services"


def test_per_company_sector_lookups_stop_at_the_time_budget(us, clean_db, monkeypatch):
    monkeypatch.setattr(us_market, "SECTOR_MINUTES", -1)          # budget already used up
    us_market.sync_universe(log=lambda *_: None)
    assert us_market.fill_sectors(log=lambda *_: None) == 0
    assert clean_db.fetch_one("SELECT count(*) AS n FROM us_companies WHERE entity_type IS NULL")["n"] == 4
