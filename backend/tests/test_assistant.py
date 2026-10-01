"""Ask FinSight routing, sources and warnings. No AI is called: the model is stubbed out."""
import json
import math
from datetime import date, datetime, timedelta, timezone

import pytest

from app import gmp, ipos
from app.ai import assistant, intent, llm
from app.ai import tools as T
from app.analytics import fundamentals, portfolio, technicals


@pytest.mark.parametrize("question,symbol,expected", [
    ("What is a P/E ratio?", None, "general_finance"),
    ("How does an IPO work?", "TCS.NS", "general_finance"),
    ("What is ROE?", "TCS.NS", "company_research"),            # that company's ROE
    ("Tell me about Reliance", "RELIANCE.NS", "company_research"),
    ("Find stocks with ROE above 20% and low debt", None, "stock_screening"),
    ("Compare TCS vs Infosys", None, "company_comparison"),
    ("Is the valuation high compared to its own history?", "TCS.NS", "valuation"),
    ("What did management say about attrition in the annual report?", "TCS.NS", "filing_question"),
    ("What is the GMP of the Tata Capital IPO?", None, "ipo_research"),
    ("Is the stock above its 200-day moving average?", "TCS.NS", "technical_analysis"),
    ("My portfolio is 50% TCS, 30% INFY and 20% HDFCBANK. How risky is it?", None, "portfolio_risk"),
])
def test_intent(question, symbol, expected):
    assert intent.classify(question, symbol) == expected


def test_every_intent_routes_to_real_tools():
    names = {t["name"] for t in T.TOOLS}
    assert set(intent.TOOLS) == set(intent.INTENTS) == set(intent.GUIDANCE)
    for kind in intent.INTENTS:
        assert set(intent.tools_for(kind, "TCS.NS")) <= names
    assert "get_financials" not in intent.tools_for("ipo_research")
    assert "get_financials" in intent.tools_for("ipo_research", "TCS.NS")   # the company in view stays reachable


def test_sources_carry_type_period_and_time():
    s = T.Sources()
    s.add("NSE filing", "https://nse/x.pdf", "TCS: results", "2026-07-10")
    s.add("InvestorGain GMP (unofficial)", None, "X: GMP")
    s.add("Yahoo Finance quote", None, "TCS: price")
    assert [i["source_type"] for i in s.items] == ["official", "unofficial", "secondary"]
    assert s.items[0]["period"] == "2026-07-10" and s.items[0]["retrieved_at"]


def _closes(start: float, daily: list[float]) -> list[dict]:
    out, price, day = [], start, date(2025, 1, 1)
    for i, r in enumerate([0.0] + daily):
        price *= 1 + r
        out.append({"date": (day + timedelta(days=i)).isoformat(), "close": price})
    return out


def test_portfolio_risk():
    moves = [0.01 * math.sin(i) for i in range(260)]
    a, b = _closes(100, moves), _closes(50, moves)                 # perfectly correlated
    result = portfolio.analyse([{"symbol": "A.NS", "weight": 3}, {"symbol": "B.NS", "weight": 1},
                                {"symbol": "C.NS", "weight": 4}],
                               {"A.NS": a, "B.NS": b, "C.NS": []}, {"A.NS": "Tech", "B.NS": "Tech"}, benchmark=a)
    assert result["largest_holding"] == {"symbol": "C.NS", "weight_pct": 50.0}
    assert result["sector_weights_pct"] == {"Unknown": 50.0, "Tech": 50.0}
    assert result["missing_prices"] == ["C.NS"]
    assert result["effective_holdings"] == pytest.approx(1 / (0.375 ** 2 + 0.125 ** 2 + 0.5 ** 2))
    assert result["average_pair_correlation"] == pytest.approx(1)
    assert result["beta"] == pytest.approx(1)
    assert result["diversification_ratio"] == pytest.approx(1)  # identical moves: no diversification
    assert result["period"]["trading_days"] == 252
    with pytest.raises(ValueError):
        portfolio.normalize_weights([{"symbol": "A", "weight": 0}])


def test_period_returns():
    history = [{"close": 100.0 + i} for i in range(300)]
    r = technicals.period_returns(history)
    assert r["return_1m_pct"] == pytest.approx((399 / 378 - 1) * 100)
    assert set(r) == {"return_1m_pct", "return_3m_pct", "return_6m_pct", "return_1y_pct"}


def test_stale_statements_are_flagged():
    table = [{"year": "FY24", "period_end": "2024-03-31"}]
    assert any("newer results may exist" in c for c in fundamentals.data_checks(table, {}, today=date(2025, 9, 1)))
    assert not any("newer results" in c for c in fundamentals.data_checks(table, {}, today=date(2024, 9, 1)))


def test_peer_stats_use_only_companies_with_the_figure():
    stats = T._peer_stats([{"pe": 10.0, "roe_pct": 20.0}, {"pe": 30.0, "roe_pct": None}, {"pe": 20.0}])
    assert stats["pe"] == {"median": 20.0, "average": 20.0, "companies": 3}
    assert "roe_pct" not in stats   # one value is not a peer average


def test_ipo_tool_keeps_gmp_unofficial(monkeypatch):
    rows = [{"symbol": "IG-1", "nse_symbol": "TATACAP", "name": "Tata Capital Ltd", "segment": "Mainboard",
             "exchange": "NSE, BSE", "status": "Open", "open_date": "2026-09-29", "close_date": "2026-10-01",
             "allotment_date": None, "listing_date": None, "price_low": 310.0, "price_high": 326.0, "lot": 46,
             "issue_size_cr": 15511.0, "subscription_times": 1.9, "listing_gain_pct": None,
             "source": {"name": "NSE India", "url": "https://nse/ipo"}}]
    monkeypatch.setattr(ipos, "current", lambda: rows)
    monkeypatch.setattr(gmp, "summaries", lambda rs: {"IG-1": gmp._summary(
        [{"gmp": 12.0, "source": "InvestorGain", "source_url": "https://ig/x", "observed_at": "2026-09-30T10:00:00+05:30"}],
        326.0)})
    sources = T.Sources()
    out, err = T.run_tool("get_ipo_data", {"query": "Tata Capital IPO"}, sources)
    data = json.loads(out)
    assert not err and data["ipos"][0]["gmp_unofficial"]["gmp_rs"] == 12.0
    assert [s["source_type"] for s in sources.items] == ["official", "unofficial"]
    assert json.loads(T.run_tool("get_ipo_data", {"query": "Nonexistent Widgets"}, T.Sources())[0])["ipos"] == []


def test_warnings_come_from_the_data():
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    old = (now - timedelta(days=6)).isoformat()
    outputs = [
        json.dumps({"data_checks": ["Only 4 years of statements are available from the current data source."]}),
        json.dumps({"note": "Amounts are in each company's own currency. The latest annual figures cover different "
                            "fiscal years (FY25, FY26); say so when comparing them."}),
        json.dumps({"ipos": [{"name": "Live Co", "status": "Open", "gmp_unofficial": {"observed_at": old}},
                             {"name": "Listed Co", "status": "Listed", "gmp_unofficial": {"observed_at": old}}]}),
        "not json",
    ]
    cited = [{"source_type": "unofficial"}]
    calls = [{"tool": "get_news", "error": True}, {"tool": "get_financials", "error": False}]
    w = assistant.warnings(outputs, cited, calls, now)
    assert w[0].startswith("Only 4 years")
    assert any(x.startswith("The latest annual figures cover different fiscal years (FY25, FY26)") for x in w)
    assert any("Live Co is 6 days old" in x for x in w) and not any("Listed Co" in x for x in w)
    assert any("unofficial" in x for x in w) and any("get news" in x for x in w)


def test_ask_routes_by_intent_and_returns_research_fields(monkeypatch):
    seen = {}

    def fake_agent(system, messages, tool_names, sources, question, **kw):
        seen.update(system=system, tools=tool_names, preloaded=kw["preloaded"], content=messages[-1]["content"])
        sid = sources.add("NSE IPO data", "https://nse/ipo", "X: issue details")
        return {"answer": f"Price band ₹326 [{sid}].", "outputs": [], "calls": [], "unverified": [],
                "misattributed": [], "model": "stub", "usage": {}}

    monkeypatch.setattr(llm, "run_agent", fake_agent)
    monkeypatch.setattr(T, "run_tool", lambda *a: pytest.fail("IPO questions shouldn't prefetch company data"))
    result = assistant.ask("What is the IPO price band?", "TCS.NS")
    assert result["intent"] == "ipo_research" and "get_ipo_data" in seen["tools"]
    assert "GMP is unofficial grey-market data" in seen["system"] and seen["preloaded"] == []
    assert result["disclaimer"] == assistant.DISCLAIMER and result["data_timestamp"]
    assert result["sources"][0]["source_type"] == "official" and result["warnings"] == []
