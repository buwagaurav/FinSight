"""The IPO list: InvestorGain's live table parsed, and NSE's official figures merged in. No network."""
from datetime import datetime

import pytest

from app import ipos
from app.cache import _store
from app.providers import investorgain, nse

ROW = ('<tr><td><div class="report-td "><div class="mono-num"><a href="/gmp/{slug}/{id}/" title="{name}" target="_parent">'
       '{name}</a> <span class="badge rounded-pill bg-secondary d-inline ms-2">{segment}</span>{status}</div></div></td>'
       '<td>{gmp}</td><td>🔥</td><td>{sub}</td><td>{price}</td><td>{size}</td><td>{lot}</td><td>{open}</td><td>{close}</td>'
       '<td>{boa}</td><td>{listing}</td><td>{updated}</td><td>✅</td></tr>')
BADGE = '<span class="badge rounded-pill bg-warning d-inline ms-2">{}</span>'
LISTED = "<span class='text-success d-inline ms-2'><small><b><a>[email&#160;protected]</a> (11.32%)</b></small></span>"


def row(**kw):
    base = dict(slug="x-ipo", id="1", name="X", segment="IPO", status=BADGE.format("O"), gmp="₹ 31 (23.85%) 20 ↓ / 31 ↑",
                sub="2.89x", price="126 to 130", size="₹345.50 Cr", lot="110", open="26-Sep", close="30-Sep",
                boa="1-Oct", listing="6-Oct", updated="29-Sep 22:02")
    return ROW.format(**{**base, **kw})


PAGE = "<table><tr><th>Name</th></tr>" + "".join([
    row(id="2121", name="SRIT India", slug="srit-india-ipo"),
    row(id="2370", name="TNA Solutions", segment="BSE SME", status=BADGE.format("U"), gmp="₹ 7 (10.00%) 7 ↓ / 7 ↑",
        sub="-", price="70", size="₹37.86 Cr", lot="2,000", open="30-Sep", close="6-Oct", boa="7-Oct", listing="9-Oct"),
    row(id="1637", name="EverestIMS Technologies", segment="NSE SME", status=BADGE.format("C") + BADGE.format("Allotted"),
        gmp="₹ -- (0.00%) 0 ↓ / 0 ↑", open="29-Sep GMP: 16", close="5-Oct", listing="8-Oct"),
    row(id="1600", name="Himalaya Nutravedics", segment="BSE SME", status=LISTED, price="106", open="22-Sep",
        close="24-Sep", boa="25-Sep", listing="29-Sep GMP: 0"),
]) + "</table>"

NSE_ROWS = [
    {"symbol": "SRIT", "name": "Srit India Limited", "segment": "Mainboard", "status": "Active", "open_date": "2026-09-26",
     "close_date": "2026-09-30", "price_low": 126.0, "price_high": 130.0, "shares_offered": 1000, "shares_bid": 2893,
     "subscription_times": 2.8936, "issue_size_cr": 345.0, "source": {"name": "NSE India", "url": "https://nse"}},
    {"symbol": "ONLYNSE", "name": "Only On NSE Limited", "segment": "SME", "status": "Forthcoming", "open_date": "2026-10-02",
     "close_date": "2026-10-06", "price_low": 50.0, "price_high": 52.0, "shares_offered": None, "shares_bid": None,
     "subscription_times": None, "issue_size_cr": None, "source": {"name": "NSE India", "url": "https://nse"}},
]


@pytest.fixture
def sources(monkeypatch):
    _store.clear()
    monkeypatch.setattr(investorgain, "_get", lambda url: PAGE)
    monkeypatch.setattr(nse, "current_ipos", lambda: NSE_ROWS)


def test_investorgain_table_is_parsed(sources, monkeypatch):
    rows = {r["name"]: r for r in investorgain.live_ipos()}
    srit, tna, ever, hima = (rows[n] for n in ("SRIT India", "TNA Solutions", "EverestIMS Technologies", "Himalaya Nutravedics"))
    assert (srit["segment"], srit["exchange"], srit["status"], srit["gmp"]) == ("Mainboard", "NSE, BSE", "Open", 31.0)
    assert (srit["price_low"], srit["price_high"], srit["lot"], srit["issue_size_cr"]) == (126.0, 130.0, 110, 345.5)
    assert (tna["segment"], tna["exchange"], tna["status"], tna["subscription_times"]) == ("SME", "BSE", "Upcoming", None)
    assert ever["status"] == "Allotted" and ever["gmp"] is None and ever["open_date"].endswith("-09-29")   # "29-Sep GMP: 16"
    assert hima["status"] == "Listed" and hima["listing_gain_pct"] == 11.32 and hima["listing_date"].endswith("-09-29")


def test_dates_take_the_nearest_year():
    now = datetime(2026, 12, 28, tzinfo=investorgain.IST)
    assert investorgain._date("2-Jan", now) == "2027-01-02"
    assert investorgain._date("20-Dec", now) == "2026-12-20"
    assert investorgain._date("-", now) is None


def test_merged_list_has_every_ipo_with_nse_figures_where_available(sources):
    rows = {r["symbol"]: r for r in ipos.current()}
    assert set(rows) == {"IG-2121", "IG-2370", "IG-1637", "IG-1600", "ONLYNSE"}
    srit = rows["IG-2121"]
    assert srit["nse_symbol"] == "SRIT" and srit["name"] == "Srit India Limited"
    assert srit["subscription_times"] == 2.8936                         # NSE's official figure wins
    assert srit["source"]["name"] == "NSE India" and srit["investorgain"]["gmp"] == 31.0
    assert rows["IG-2370"]["nse_symbol"] is None and rows["IG-2370"]["source"]["name"] == "InvestorGain"
    only = rows["ONLYNSE"]
    assert only["status"] == "Upcoming" and only["investorgain"] is None


def test_order_is_open_upcoming_then_closed_allotted_listed(sources):
    assert [r["status"] for r in ipos.current()] == ["Open", "Upcoming", "Upcoming", "Allotted", "Listed"]


def test_one_source_down_still_gives_a_list(sources, monkeypatch):
    def down():
        raise RuntimeError("NSE blocked")
    monkeypatch.setattr(nse, "current_ipos", down)
    assert len(ipos.current()) == 4
    monkeypatch.setattr(investorgain, "_get", lambda url: (_ for _ in ()).throw(RuntimeError("IG down")))
    _store.clear()
    with pytest.raises(RuntimeError):
        ipos.current()


def test_gmp_history_is_kept_across_keys(sources, clean_db, monkeypatch):
    from app import gmp
    monkeypatch.setattr(investorgain, "history", lambda url: [{"gmp": 25.0, "observed_at": datetime(2026, 9, 27, 10, tzinfo=investorgain.IST)}])
    gmp._last_sync = 0
    clean_db.execute("""INSERT INTO gmp_entries (symbol, gmp, source, observed_at)
                        VALUES ('SRIT', 20, 'InvestorGain', '2026-09-26 10:00+05:30')""")   # stored before stable keys
    rows = ipos.current()
    gmp.sync(rows)
    s = gmp.summaries(rows)["IG-2121"]
    assert [e["gmp"] for e in s["history"]] == [20.0, 25.0, 31.0]       # old NSE-keyed, first-sync history, current
    assert s["estimate"]["estimated_listing_price"] == 161.0
