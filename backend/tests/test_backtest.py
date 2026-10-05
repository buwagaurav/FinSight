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
    assert set(body["results"]) == {"buy_hold", *B.STRATEGIES} and len(B.STRATEGIES) == 13
    assert body["capital"] == 100_000 and body["currency"] == "INR" and len(body["warnings"]) >= 4
    assert body["results"]["buy_hold"]["trades"] == 0 and body["results"]["buy_hold"]["time_invested_pct"] > 99
    assert len(body["curves"]["dates"]) == len(body["curves"]["ema_trend"]) <= 302
    assert c.get("/api/company/TCS/backtest", params={"years": 5}).json()["period"]["years"] <= 5.01
    assert c.get("/api/company/TCS/backtest", params={"years": 7}).status_code == 422


def test_every_rule_produces_signals():
    import math
    import random
    rng = random.Random(1)
    # slow swings (long enough for 50/200 crossings) with day-to-day noise (so bands and oscillators hit extremes)
    close = [100 + 30 * math.sin(i / 60) + rng.gauss(0, 2) for i in range(900)]
    for i in range(15):                       # a sharp fall and a strong rally, so RSI reaches 30 and 70
        close[400 + i] -= 4 * i
        close[430 + i] += 4 * i
    high, low = [c + abs(rng.gauss(0, 1)) for c in close], [c - abs(rng.gauss(0, 1)) for c in close]
    vol = [rng.uniform(1000, 5000) for _ in close]
    for key in B.STRATEGIES:
        sig = B.signals(key, high, low, close, vol)
        assert len(sig) == 900 and sig[-1] in (0, 1), key
        assert 1 in sig and 0 in sig, f"{key} never changed position on a swinging price"
        assert B.STRATEGIES[key]["type"] in ("trend", "breakout", "mean reversion")


def test_breakout_and_mean_reversion_rules_follow_their_definitions():
    flat_then_jump = [100.0] * 30 + [120.0] * 5 + [90.0] * 15
    hi, lo = [c + 0.5 for c in flat_then_jump], [c - 0.5 for c in flat_then_jump]
    d = B.signals("donchian", hi, lo, flat_then_jump)
    assert d[30] == 1 and d[29] == 0          # closes above the previous 20-day high: buy
    assert d[35] == 0                          # breaks the previous 10-day low: sell
    dip = [100.0] * 25 + [80.0] + [100.0] * 5
    bb = B.signals("bollinger", dip, dip, dip)
    assert bb[25] == 1 and bb[26] == 0         # closed below the lower band, then back above the middle


def test_universe_summary_counts_and_medians():
    from app import backtest_universe as U
    def row(cagr, dd):
        return {"cagr_pct": cagr, "max_drawdown_pct": dd, "trades": 4, "time_invested_pct": 50.0}
    per_stock = {}
    for sym, (hold, rule) in {"A": (10, 12), "B": (10, 5), "C": (8, 9)}.items():
        per_stock[sym] = {"buy_hold": row(hold, -40), **{k: row(rule, -20) for k in B.STRATEGIES}}
    s = U.summarise(per_stock)
    r = s["rules"]["ema_trend"]
    assert (r["beat_hold"], r["smaller_drawdown"], r["stocks"]) == (2, 3, 3)
    assert r["median_cagr_gap_pts"] == 1 and r["median_drawdown_gap_pts"] == 20
    assert s["rules_tested"] == len(B.STRATEGIES) and s["buy_hold_median_cagr_pct"] == 10


def test_constituents_fall_back_to_the_built_in_list(monkeypatch):
    from app import backtest_universe as U
    monkeypatch.setattr(U.requests, "get", lambda *a, **k: (_ for _ in ()).throw(ConnectionError("blocked")))
    assert len(U.constituents()) == 50


def test_universe_api(clean_db):
    from app import backtest_universe as U
    c = TestClient(main.app)
    U.db.execute(U.SCHEMA)
    U.db.execute("DELETE FROM backtest_universe")
    assert c.get("/api/backtest/universe").status_code == 404
    U.db.execute("INSERT INTO backtest_universe (universe, years, data) VALUES ('NIFTY50', 5, %s)",
                 (U.db.jsonb({"rules": {}, "stocks": ["TCS"]}),))
    body = c.get("/api/backtest/universe", params={"years": 5}).json()
    assert body["stocks"] == ["TCS"] and "computed_at" in body
    assert c.get("/api/backtest/universe", params={"years": 10}).status_code == 422
