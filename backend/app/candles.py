"""Candlestick data for the price chart: OHLC + volume from Yahoo's chart data (which still answers from cloud
hosts when its quote endpoint doesn't), plus whether the market is open so the page knows to keep refreshing.

Intraday candles are near-live (Yahoo updates them about once a minute), not tick-by-tick: streaming every trade
to the public needs a licensed data feed. Each stock's candles are cached briefly, so many viewers of the same
stock cost one Yahoo request per cache period.
"""
import math
from datetime import datetime, time as dtime, timezone
from zoneinfo import ZoneInfo

import yfinance as yf

from app.cache import cached
from app.providers import sec, yahoo

# range -> (Yahoo period, candle interval, seconds to cache)
RANGES = {
    "1d": ("1d", "1m", 30),
    "5d": ("5d", "5m", 60),
    "1mo": ("1mo", "30m", 300),
    "6mo": ("6mo", "1d", 900),
    "1y": ("1y", "1d", 900),
    "5y": ("5y", "1wk", 3600),
}
REFRESH_SECONDS = {"1d": 60, "5d": 120, "1mo": 300}   # how often an open chart re-asks while the market is open
# regular trading sessions (exchange holidays aren't listed: a closed day simply produces no fresh candles)
SESSIONS = {"IN": (ZoneInfo("Asia/Kolkata"), dtime(9, 15), dtime(15, 30)),
            "US": (ZoneInfo("America/New_York"), dtime(9, 30), dtime(16, 0))}
LIVE_WITHIN_MINUTES = 15   # the newest candle may start at most one candle plus this long ago to count as live


def market(symbol: str) -> str:
    return "US" if sec.is_us(symbol) else "IN"


def session_open(symbol: str, now: datetime | None = None) -> bool:
    tz, start, end = SESSIONS[market(symbol)]
    local = (now or datetime.now(timezone.utc)).astimezone(tz)
    return local.weekday() < 5 and start <= local.time() <= end


def _fetch(symbol: str, period: str, interval: str) -> list[list]:
    """[[label, open, high, low, close, volume, epoch_ms], ...] in the exchange's local time."""
    hist = yf.Ticker(yahoo.yahoo_ticker(symbol)).history(period=period, interval=interval, auto_adjust=False)
    fmt = "%d %b %H:%M" if interval.endswith("m") else "%d %b %Y"
    bars, gap = [], None
    for idx, row in hist.iterrows():
        o, h, l, c = (float(row[k]) for k in ("Open", "High", "Low", "Close"))
        if any(math.isnan(x) for x in (o, h, l, c)):
            gap = idx   # Yahoo leaves the current day's daily row empty for NSE stocks until it settles
            continue
        label = idx.strftime("%H:%M" if period == "1d" else fmt)
        bars.append([label, round(o, 2), round(h, 2), round(l, 2), round(c, 2), int(row["Volume"] or 0),
                     int(idx.timestamp() * 1000)])
    if interval == "1d" and gap is not None and (not bars or gap.timestamp() * 1000 > bars[-1][6]):
        today = _day_from_intraday(symbol, gap)
        if today:
            bars.append(today)
    return bars


def _day_from_intraday(symbol: str, day) -> list | None:
    """One daily candle built from the day's 5-minute candles."""
    intraday = yf.Ticker(yahoo.yahoo_ticker(symbol)).history(period="1d", interval="5m", auto_adjust=False).dropna()
    intraday = intraday[intraday.index.date == day.date()]
    if intraday.empty:
        return None
    return [day.strftime("%d %b %Y"), round(float(intraday["Open"].iloc[0]), 2), round(float(intraday["High"].max()), 2),
            round(float(intraday["Low"].min()), 2), round(float(intraday["Close"].iloc[-1]), 2),
            int(intraday["Volume"].sum()), int(day.timestamp() * 1000)]


def candles(symbol: str, range_: str) -> dict:
    """Candles for one range, and whether the chart should keep refreshing. LookupError if there's no data."""
    symbol = yahoo.normalize_symbol(symbol)
    period, interval, ttl = RANGES[range_]
    bars = cached(("candles", symbol, range_), ttl, lambda: _fetch(symbol, period, interval))
    if not bars:
        raise LookupError(symbol)
    now = datetime.now(timezone.utc)
    last = datetime.fromtimestamp(bars[-1][6] / 1000, timezone.utc)
    is_open = session_open(symbol, now)
    candle_minutes = int(interval[:-1]) if interval.endswith("m") else 0
    live = (is_open and range_ in REFRESH_SECONDS
            and (now - last).total_seconds() <= (candle_minutes + LIVE_WITHIN_MINUTES) * 60)
    return {
        "symbol": symbol,
        "range": range_,
        "interval": interval,
        "bars": bars,
        "market": {"id": market(symbol), "open": is_open, "live": live, "last_bar": last.isoformat(),
                   "delay_minutes": round((now - last).total_seconds() / 60) if is_open else None},
        "refresh_seconds": REFRESH_SECONDS[range_] if live else None,
        "source": {"name": "Yahoo Finance chart data", "url": f"https://finance.yahoo.com/quote/{yahoo.yahoo_ticker(symbol)}/chart"},
    }
