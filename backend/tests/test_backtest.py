"""Backtest engine: no look-ahead, whole shares, costs, metrics, and the Backtest tab API. Synthetic prices only."""
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app import cache, candles, main
from app.analytics import backtest as B

FREE = B.Costs(slippage=0.0)
DAYS = [date(2020, 1, 1) + timedelta(days=i) for i in range(10)]


def test_trades_at_the_next_open_never_the_signal_close():
    opens = [100, 110, 120, 130, 140, 150, 160, 170, 180, 190]
    closes = [o + 5 for o in opens]
    desired = [0, 1, 1, 1, 0, 0, 0, 0, 0, 0]          # buy decided at close of bar 1, sell at close of bar 4
    res = B.simulate(DAYS, opens, closes, desired, 0, FREE, capital=1000)
    trade = res.trades[0]
    assert (trade["entry_date"], trade["entry_price"]) == (DAYS[2].isoformat(), 120)   # bar 2's open
    assert (trade["exit_date"], trade["exit_price"]) == (DAYS[5].isoformat(), 150)     # bar 5's open
    assert trade["shares"] == 8                                                       # whole shares: 1000 // 120
    assert res.equity[-1] == pytest.approx(1000 - 8 * 120 + 8 * 150)


def test_costs_are_charged_on_both_sides():
    c = B.INDIA.charge("buy", 100_000)
    assert c == pytest.approx(100 + 2.97 + 0.1 + (2.97 + 0.1) * 0.18 + 15)          # STT, exchange, SEBI, GST, stamp
    s = B.INDIA.charge("sell", 100_000)
    assert s == pytest.approx(100 + 2.97 + 0.1 + (2.97 + 0.1) * 0.18 + 15.93)       # STT ... + depository charge
    capped = B.Costs(brokerage=0.0003, brokerage_cap=20).charge("buy", 1_000_000)
    assert capped == pytest.approx(20)


def test_signals_follow_their_rules():
    up = [100 + i for i in range(300)]
    hlc = ([p + 1 for p in up], [p - 1 for p in up], up)
    assert B.signals("ema_trend", *hlc)[-1] == 1 and B.signals("ema_trend", *hlc)[198] is None
    assert B.signals("supertrend", *hlc)[-1] == 1
    falling_then_rising = [100 - i for i in range(40)] + [60 + 3 * i for i in range(40)]
    r = B.signals("rsi", falling_then_rising, falling_then_rising, falling_then_rising)
    assert 1 in r and r[-1] == 0          # bought when oversold, sold once RSI passed 70


def test_metrics_drawdown_and_cagr():
    days = [date(2020, 1, 1), date(2021, 1, 1), date(2022, 1, 1)]
    m = B.metrics([100_000, 50_000, 121_000], days)
    assert m["max_drawdown_pct"] == pytest.approx(-50)
    assert m["cagr_pct"] == pytest.approx(10, abs=0.1)        # 1.21x over two years


def test_yearly_breakdown_marks_partial_years():
    days = [date(2020, 6, 1), date(2020, 12, 31), date(2021, 6, 30), date(2021, 12, 31)]
    rows = B.yearly(days, {"x": [100_000, 110_000, 99_000, 121_000]})
    assert [(r["year"], round(r["x"], 1), r["partial"]) for r in rows] == [(2020, 10.0, True), (2021, 10.0, False)]


@pytest.fixture
def fake_daily(monkeypatch):
    import math
    def bars(symbol, period, interval, adjust=False):
        start = 1_500_000_000_000
        close = [100 + 20 * math.sin(i / 60) + i * 0.05 for i in range(1500)]
        return [[f"b{i}", c - 0.5, c + 1, c - 1, c, 1000, start + i * 86_400_000] for i, c in enumerate(close)]
    monkeypatch.setattr(candles, "_fetch", bars)
    monkeypatch.setattr(candles, "session_open", lambda symbol, now=None: False)
    cache._store.clear()


def test_backtest_api(fake_daily):
    c = TestClient(main.app)
    body = c.get("/api/company/TCS/backtest").json()
    assert set(body["results"]) == {"buy_hold", "ema_trend", "rsi", "macd", "supertrend"}
    assert body["capital"] == 100_000 and body["currency"] == "INR" and len(body["warnings"]) >= 4
    assert body["results"]["buy_hold"]["trades"] == 0 and body["results"]["buy_hold"]["time_invested_pct"] > 99
    assert len(body["curves"]["dates"]) == len(body["curves"]["ema_trend"]) <= 302
    assert c.get("/api/company/TCS/backtest", params={"years": 5}).json()["period"]["years"] <= 5.01
    assert c.get("/api/company/TCS/backtest", params={"years": 7}).status_code == 422
