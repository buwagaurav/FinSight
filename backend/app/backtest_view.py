"""The stock page's Backtest tab: how four standard indicator rules would have traded this stock, next to buy-and-hold.

Uses the same 10 years of daily bars as the Technicals tab (one Yahoo request serves both). Results are cached as
long as those bars are.
"""
from datetime import datetime

from app import candles, technical_view
from app.analytics import backtest
from app.cache import cached
from app.providers import yahoo

WARNINGS = [
    "Past results don't predict future returns. This shows how fixed rules would have traded this stock's past "
    "prices; it isn't a recommendation to use any of them.",
    "Survivorship bias: only companies still listed today can be tested. Ones that collapsed or were delisted are "
    "missing, which makes every rule look better than it would have been.",
    "A decade of daily prices covers only a few market phases, and a rule that fitted one period often fails in the "
    "next. Compare across several stocks before drawing conclusions.",
    "Costs are approximate and tax isn't included. Rules that trade often pay short-term capital gains tax "
    "(20% in India) more often than buy-and-hold, which qualifies for the lower long-term rate (12.5% above "
    "₹1.25 lakh a year).",
    "Trades happen at the next day's open with 0.05% slippage; prices that gap overnight can fill worse.",
]


def build(symbol: str, years: int | None = None) -> dict:
    symbol = yahoo.normalize_symbol(symbol)
    market = candles.market(symbol)
    period, interval, _, adjust, ttl, _ = technical_view.TIMEFRAMES["daily"]
    if candles.session_open(symbol):
        ttl = technical_view.LIVE_SECONDS["daily"]

    def compute():
        bars = cached(("indicator-bars", symbol, "daily"), ttl, lambda: candles._fetch(symbol, period, interval, adjust))
        tz = candles.SESSIONS[market][0]
        dates = [datetime.fromtimestamp(b[6] / 1000, tz).date() for b in bars]   # the exchange's calendar date
        o, h, l, c = ([b[k] for b in bars] for k in (1, 2, 3, 4))
        return backtest.run_all(dates, o, h, l, c, market, years)

    result = cached(("backtest", symbol, years), ttl, compute)
    return {"symbol": symbol, "market": market, "currency": "USD" if market == "US" else "INR", **result,
            "warnings": WARNINGS,
            "source": {"name": "Yahoo Finance daily prices (split-adjusted)",
                       "url": f"https://finance.yahoo.com/quote/{yahoo.yahoo_ticker(symbol)}/history"}}
