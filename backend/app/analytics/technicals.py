import math
import statistics


def _sma(closes: list[float], n: int) -> float | None:
    return sum(closes[-n:]) / n if len(closes) >= n else None


def summarize(history: list[dict]) -> dict:
    closes = [p["close"] for p in history]
    if len(closes) < 30:
        return {"trend": "Insufficient data", "reasons": []}
    last = closes[-1]
    sma50, sma200 = _sma(closes, 50), _sma(closes, 200)
    year = closes[-252:]
    daily = [math.log(b / a) for a, b in zip(year, year[1:]) if a > 0 and b > 0]
    volatility = statistics.stdev(daily) * math.sqrt(252) * 100 if len(daily) > 2 else None
    peak, max_dd = year[0], 0.0
    for c in year:
        peak = max(peak, c)
        max_dd = min(max_dd, c / peak - 1)

    reasons = []
    if sma200:
        above200 = last > sma200
        reasons.append(f"Price is {'above' if above200 else 'below'} its 200-day average (₹{sma200:,.0f}).")
    if sma50 and sma200:
        reasons.append(f"50-day average is {'above' if sma50 > sma200 else 'below'} the 200-day average.")
    if sma50 and sma200 and last > sma50 > sma200:
        trend = "Uptrend"
    elif sma50 and sma200 and last < sma50 < sma200:
        trend = "Downtrend"
    else:
        trend = "Sideways"

    return {
        "trend": trend,
        "price": last,
        "sma50": sma50,
        "sma200": sma200,
        "return_1y_pct": (last / year[0] - 1) * 100,
        "volatility_1y_pct": volatility,
        "max_drawdown_1y_pct": max_dd * 100,
        "reasons": reasons,
    }
