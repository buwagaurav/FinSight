from datetime import datetime, timezone

import pandas as pd
import pytest

from app import candles
from app.cache import _store


@pytest.fixture(autouse=True)
def fresh_cache():
    _store.clear()


def fake_history(index, rows):
    df = pd.DataFrame(rows, columns=["Open", "High", "Low", "Close", "Volume"], index=pd.DatetimeIndex(index))

    class Ticker:
        calls = 0

        def __init__(self, t):
            Ticker.last_ticker = t

        def history(self, **kw):
            Ticker.calls += 1
            Ticker.kw = kw
            return df
    return Ticker


def test_sessions_follow_each_exchange_clock():
    utc = lambda s: datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    assert candles.session_open("TCS.NS", utc("2026-09-29T04:00:00"))        # 09:30 IST Tuesday
    assert not candles.session_open("TCS.NS", utc("2026-09-29T10:30:00"))    # 16:00 IST
    assert candles.session_open("AAPL.US", utc("2026-09-29T14:00:00"))       # 10:00 New York
    assert not candles.session_open("AAPL.US", utc("2026-09-29T04:00:00"))   # 00:00 New York
    assert not candles.session_open("AAPL.US", utc("2026-09-27T15:00:00"))   # Sunday


def test_candles_are_cached_and_skip_empty_rows(monkeypatch):
    now = datetime(2026, 9, 29, 15, 0, tzinfo=timezone.utc)           # US market open
    idx = pd.to_datetime(["2026-09-29 10:57", "2026-09-29 10:58", "2026-09-29 10:59"]).tz_localize("America/New_York")
    Ticker = fake_history(idx, [[1, 2, 0.5, 1.5, 100], [float("nan")] * 4 + [0], [1.5, 2.5, 1.4, 2.0, 50]])
    monkeypatch.setattr(candles.yf, "Ticker", Ticker)
    monkeypatch.setattr(candles, "datetime", type("dt", (datetime,), {"now": staticmethod(lambda tz=None: now)}))
    d = candles.candles("AAPL.US", "1d")
    assert Ticker.last_ticker == "AAPL" and Ticker.kw["interval"] == "1m"
    assert [b[0] for b in d["bars"]] == ["10:57", "10:59"]             # the empty minute is dropped
    assert d["bars"][-1][1:6] == [1.5, 2.5, 1.4, 2.0, 50]
    assert d["market"]["live"] and d["refresh_seconds"] == 60 and d["market"]["delay_minutes"] == 1
    candles.candles("AAPL.US", "1d")
    assert Ticker.calls == 1                                           # second viewer: served from cache


def test_closed_market_and_long_ranges_do_not_refresh(monkeypatch):
    idx = pd.to_datetime(["2026-09-21", "2026-09-28"]).tz_localize("Asia/Kolkata")
    monkeypatch.setattr(candles.yf, "Ticker", fake_history(idx, [[10, 12, 9, 11, 1000], [11, 13, 10, 12, 900]]))
    d = candles.candles("TCS", "5y")
    assert d["symbol"] == "TCS.NS" and d["interval"] == "1wk"
    assert d["bars"][0][0] == "21 Sep 2026" and d["refresh_seconds"] is None and not d["market"]["live"]


def test_no_data_is_a_lookup_error(monkeypatch):
    monkeypatch.setattr(candles.yf, "Ticker", fake_history([], []))
    with pytest.raises(LookupError):
        candles.candles("NOPE.NS", "1d")


def test_empty_current_day_is_rebuilt_from_intraday_candles(monkeypatch):
    days = pd.to_datetime(["2026-09-28", "2026-09-29"]).tz_localize("Asia/Kolkata")
    minutes = pd.to_datetime(["2026-09-29 09:15", "2026-09-29 09:20", "2026-09-29 15:25"]).tz_localize("Asia/Kolkata")
    daily = pd.DataFrame([[10, 12, 9, 11, 100], [float("nan")] * 4 + [0]], columns=["Open", "High", "Low", "Close", "Volume"], index=days)
    intra = pd.DataFrame([[11, 13, 10.5, 12, 5], [12, 14, 11, 13, 6], [13, 13.5, 8, 9, 7]],
                         columns=["Open", "High", "Low", "Close", "Volume"], index=minutes)

    class Ticker:
        def __init__(self, t): pass

        def history(self, interval, **kw):
            return intra if interval == "5m" else daily
    monkeypatch.setattr(candles.yf, "Ticker", Ticker)
    bars = candles.candles("RELIANCE.NS", "1y")["bars"]
    assert [b[0] for b in bars] == ["28 Sep 2026", "29 Sep 2026"]
    assert bars[-1][1:6] == [11.0, 14.0, 8.0, 9.0, 18]      # first open, highest high, lowest low, last close, total volume
