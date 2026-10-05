"""Technical indicators: textbook properties and the Technicals tab's API. No network: synthetic prices."""
import math

import pytest
from fastapi.testclient import TestClient

from app import cache, candles, main, technical_view
from app.analytics import indicators as I

UP = [100 + i for i in range(300)]                  # rises 1 a bar
DOWN = [400 - i for i in range(300)]
FLAT = [100.0] * 300


def _hlc(close, spread=1.0):
    return [c + spread for c in close], [c - spread for c in close], close


def test_moving_averages():
    assert I.sma([1, 2, 3, 4], 2) == [None, 1.5, 2.5, 3.5]
    assert I.ema(FLAT, 20)[-1] == pytest.approx(100)
    e = I.ema(UP, 20)
    assert e[18] is None and e[19] == pytest.approx(sum(UP[:20]) / 20)       # seeded with the simple average
    assert UP[-1] - 10 < e[-1] < UP[-1]                                     # lags a rising price


def test_rsi_extremes():
    assert I.rsi(UP)[-1] == pytest.approx(100)
    assert I.rsi(DOWN)[-1] == pytest.approx(0)
    assert I.rsi(FLAT)[-1] == 100                                           # no down moves: 100, as on TradingView
    assert I.rsi(UP)[13] is None and I.rsi(UP)[14] is not None              # 14 changes needed


def test_macd_bollinger_and_atr():
    line, signal, hist = I.macd(FLAT)
    assert line[-1] == pytest.approx(0) and hist[-1] == pytest.approx(0)
    assert next(i for i, v in enumerate(signal) if v is not None) == 33     # 26 + 9 - 2
    up, mid, low = I.bollinger(FLAT)
    assert up[-1] == mid[-1] == low[-1] == pytest.approx(100)
    assert I.atr(*_hlc(FLAT, spread=2))[-1] == pytest.approx(4)            # high - low = 4 every bar


def test_trend_indicators_follow_the_trend():
    _, direction = I.supertrend(*_hlc(UP))
    assert direction[-1] == 1
    _, direction = I.supertrend(*_hlc(DOWN))
    assert direction[-1] == -1
    adx, plus, minus = I.adx(*_hlc(UP))
    assert adx[-1] > 50 and plus[-1] > minus[-1]


def test_stochastic_vwap_and_obv():
    k, d = I.stochastic(*_hlc(UP))
    assert k[-1] > 90 and d[-1] > 90 and len(k) == len(d) == len(UP)
    vw = I.vwap([11, 21], [9, 19], [10, 20], [100, 300], ["d1", "d1"])
    assert vw == [10, pytest.approx((10 * 100 + 20 * 300) / 400)]
    assert I.vwap([11, 21], [9, 19], [10, 20], [100, 300], ["d1", "d2"])[1] == 20      # restarts each day
    assert I.obv([1, 2, 2, 1], [5, 7, 9, 4]) == [0, 7, 7, 3]


@pytest.fixture
def fake_bars(monkeypatch):
    def bars(symbol, period, interval, adjust=False):
        close = [100 + 10 * math.sin(i / 15) + i * 0.2 for i in range(520)]
        return [[f"b{i}", c, c + 1, c - 1, c, 1000 + i, 1_700_000_000_000 + i * 86_400_000] for i, c in enumerate(close)]
    monkeypatch.setattr(candles, "_fetch", bars)
    cache._store.clear()   # fresh cache per test


def test_technicals_view_and_api(fake_bars):
    view = technical_view.build("TCS", "daily")
    assert len(view["bars"]) == 252 and all(len(v) == 252 for v in view["series"].values())
    assert view["series"]["ema200"][0] is not None                         # warmed up before the first shown bar
    keys = [r["key"] for r in view["readings"]]
    assert {"rsi", "macd", "bollinger", "supertrend", "adx", "stochastic", "atr", "obv", "sma"} <= set(keys)
    assert all(r["tone"] in ("positive", "negative", "neutral") for r in view["readings"])
    assert all("buy" not in r["reading"].lower() and "sell" not in r["reading"].lower() for r in view["readings"])
    intraday = technical_view.build("TCS", "intraday")
    assert "vwap" in intraday["series"] and "vwap" not in view["series"]

    c = TestClient(main.app)
    assert c.get("/api/company/TCS/indicators", params={"timeframe": "weekly"}).json()["timeframe"] == "weekly"
    assert c.get("/api/company/TCS/indicators", params={"timeframe": "hourly"}).status_code == 422


def test_refreshes_only_while_the_market_is_open(fake_bars, monkeypatch):
    monkeypatch.setattr(candles, "session_open", lambda symbol, now=None: True)
    assert technical_view.build("TCS", "intraday")["refresh_seconds"] == 60
    assert technical_view.build("TCS", "daily")["refresh_seconds"] == 180
    monkeypatch.setattr(candles, "session_open", lambda symbol, now=None: False)
    view = technical_view.build("TCS", "weekly")
    assert view["refresh_seconds"] is None and view["market"]["open"] is False
