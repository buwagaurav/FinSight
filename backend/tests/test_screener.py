import pytest

from app import screener
from tests.conftest import add_company


@pytest.fixture
def db(clean_db):
    add_company(clean_db, "TCS", "TCS", market_cap_cr=750000, pe=15, roe_pct=48, debt_to_equity=0.1)
    add_company(clean_db, "ZOMATO", "Zomato", sector="Consumer Cyclical", market_cap_cr=200000, pe=300, roe_pct=2)
    add_company(clean_db, "HDFCBANK", "HDFC Bank", sector="Financial Services", market_cap_cr=1100000, pe=20, roe_pct=None)
    return clean_db


def test_filters_sort_and_describe_the_query(db):
    out = screener.run([{"field": "roe_pct", "op": ">", "value": 15}, {"field": "pe", "op": "<", "value": 30}])
    assert [r["symbol"] for r in out["rows"]] == ["TCS.NS"]
    assert out["query"] == "ROE % > 15 AND P/E < 30"


def test_missing_values_never_pass_a_filter(db):
    out = screener.run([{"field": "roe_pct", "op": "<", "value": 100}])
    assert "HDFCBANK.NS" not in [r["symbol"] for r in out["rows"]]


def test_sector_filter_and_default_sort(db):
    assert [r["symbol"] for r in screener.run([])["rows"]] == ["HDFCBANK.NS", "TCS.NS", "ZOMATO.NS"]
    out = screener.run([], sort="pe", descending=False, sectors=["Technology", "Consumer Cyclical"])
    assert [r["symbol"] for r in out["rows"]] == ["TCS.NS", "ZOMATO.NS"]


@pytest.mark.parametrize("bad", [{"field": "pe; DROP TABLE metrics", "op": ">", "value": 1},
                                 {"field": "pe", "op": "!= 0 OR 1=1 --", "value": 1}])
def test_only_whitelisted_fields_and_operators(db, bad):
    with pytest.raises(ValueError):
        screener.run([bad])
    assert db.fetch_one("SELECT count(*) AS n FROM metrics")["n"] == 3


def test_unknown_sort_falls_back_to_market_cap(db):
    rows = screener.run([], sort="name; DROP TABLE metrics")["rows"]
    assert rows[0]["symbol"] == "HDFCBANK.NS"
