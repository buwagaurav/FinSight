from datetime import date, timedelta

import pytest

from app.analytics import technicals, valuation


def test_scenarios_are_ordered_and_explained():
    pe_hist = [{"pe": 18}, {"pe": 25}, {"pe": 30}]
    s = valuation.scenarios(price=1000, eps_ttm=50, eps_cagr_pct=10, pe_history=pe_hist, current_pe=20)
    c = s["cases"]
    assert c["bear"]["implied_price"] < c["base"]["implied_price"] < c["bull"]["implied_price"]
    assert c["base"]["growth_pct"] == 10 and c["bear"]["growth_pct"] == 4 and c["bull"]["growth_pct"] == 14
    assert c["base"]["exit_pe"] == pytest.approx((20 + 22.5) / 2)   # halfway to the median of 18, 20, 25, 30
    assert len(s["assumptions"]) == 5


def test_scenarios_cap_growth_and_need_data():
    s = valuation.scenarios(1000, 50, 80, [{"pe": 20}, {"pe": 25}], None)
    assert s["cases"]["base"]["growth_pct"] == 25
    assert valuation.scenarios(1000, -5, 10, [{"pe": 20}, {"pe": 25}], 20) is None
    assert valuation.scenarios(1000, 50, 10, [{"pe": 20}], None) is None


def test_historical_pe_uses_close_on_or_before_year_end():
    history = [{"date": "2025-03-28", "close": 110.0}, {"date": "2025-04-01", "close": 999.0}]
    table = [{"year": "FY25", "period_end": "2025-03-31", "eps": 10.0}, {"year": "FY24", "period_end": "2024-03-31", "eps": 9.0}]
    assert valuation.historical_pe(table, history) == [{"year": "FY25", "price": 110.0, "eps": 10.0, "pe": 11.0}]


def prices(closes):
    start = date(2025, 1, 1)
    return [{"date": (start + timedelta(days=i)).isoformat(), "close": c} for i, c in enumerate(closes)]


def test_technicals_trend_and_drawdown():
    up = technicals.summarize(prices([100 + i for i in range(260)]))
    assert up["trend"] == "Uptrend" and up["max_drawdown_1y_pct"] == 0
    down = technicals.summarize(prices([400 - i for i in range(260)]))
    assert down["trend"] == "Downtrend" and down["max_drawdown_1y_pct"] < -30
    assert technicals.summarize(prices([100] * 10))["trend"] == "Insufficient data"
