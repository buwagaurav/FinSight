"""Portfolio risk from daily closes: concentration, volatility, drawdown, correlation and beta.

Pure arithmetic over price histories the caller supplies, like technicals.py: no data fetching here.
"""
import math
import statistics

TRADING_DAYS = 252


def _returns(closes: list[float]) -> list[float]:
    return [b / a - 1 for a, b in zip(closes, closes[1:]) if a > 0]


def _vol_pct(returns: list[float]) -> float | None:
    return statistics.stdev(returns) * math.sqrt(TRADING_DAYS) * 100 if len(returns) > 2 else None


def _max_drawdown_pct(values: list[float]) -> float:
    peak, worst = values[0], 0.0
    for v in values:
        peak = max(peak, v)
        worst = min(worst, v / peak - 1)
    return worst * 100


def _beta(returns: list[float], market: list[float]) -> float | None:
    if len(returns) < 30 or len(returns) != len(market):
        return None
    var = statistics.variance(market)
    return statistics.covariance(returns, market) / var if var else None


def normalize_weights(holdings: list[dict]) -> list[dict]:
    """Weights may be given as percentages, amounts or share of 1; they're rescaled to sum to 100%."""
    total = sum(h["weight"] for h in holdings)
    if total <= 0 or any(h["weight"] < 0 for h in holdings):
        raise ValueError("weights must be positive")
    return [{**h, "weight_pct": h["weight"] / total * 100} for h in holdings]


def analyse(holdings: list[dict], histories: dict[str, list[dict]], sectors: dict[str, str | None],
            benchmark: list[dict] | None = None) -> dict:
    """holdings: [{symbol, weight}]; histories: symbol -> [{date, close}] daily, oldest first.
    Uses the last year of dates every holding traded on, so returns line up day by day."""
    holdings = normalize_weights(holdings)
    priced = [h for h in holdings if len(histories.get(h["symbol"]) or []) >= 30]
    missing = [h["symbol"] for h in holdings if h not in priced]

    weights = [h["weight_pct"] / 100 for h in holdings]
    by_sector: dict[str, float] = {}
    for h in holdings:
        key = sectors.get(h["symbol"]) or "Unknown"
        by_sector[key] = by_sector.get(key, 0.0) + h["weight_pct"]
    top = max(holdings, key=lambda h: h["weight_pct"])
    out = {
        "holdings": len(holdings),
        "effective_holdings": 1 / sum(w * w for w in weights),   # 1 / Herfindahl: equal-weight equivalent count
        "largest_holding": {"symbol": top["symbol"], "weight_pct": top["weight_pct"]},
        "sector_weights_pct": dict(sorted(by_sector.items(), key=lambda kv: -kv[1])),
        "missing_prices": missing,
    }
    if not priced:
        return {**out, "note": "No price history available, so volatility and drawdown can't be calculated."}

    common = set.intersection(*({p["date"] for p in histories[h["symbol"]]} for h in priced))
    if benchmark:
        with_market = common & {p["date"] for p in benchmark}
        common = with_market if len(with_market) >= 30 else common
    dates = sorted(common)[-(TRADING_DAYS + 1):]
    if len(dates) < 31:
        return {**out, "note": "The holdings share fewer than 30 trading days of prices; risk figures need more history."}

    total = sum(h["weight_pct"] for h in priced)
    closes = {h["symbol"]: dict((p["date"], p["close"]) for p in histories[h["symbol"]]) for h in priced}
    rets = {s: _returns([c[d] for d in dates]) for s, c in closes.items()}
    w = {h["symbol"]: h["weight_pct"] / total for h in priced}   # renormalised over holdings that have prices
    # Daily rebalanced to the stated weights: a standard simplification, stated in `method`
    port = [sum(w[s] * rets[s][i] for s in rets) for i in range(len(dates) - 1)]
    value = [1.0]
    for r in port:
        value.append(value[-1] * (1 + r))

    market = _returns([dict((p["date"], p["close"]) for p in benchmark)[d] for d in dates]) \
        if benchmark and set(dates) <= {p["date"] for p in benchmark} else None
    symbols = list(rets)
    pairs = [statistics.correlation(rets[a], rets[b]) for i, a in enumerate(symbols) for b in symbols[i + 1:]]
    per = [{"symbol": s, "weight_pct": w[s] * 100, "volatility_1y_pct": _vol_pct(rets[s]),
            "return_1y_pct": (closes[s][dates[-1]] / closes[s][dates[0]] - 1) * 100,
            "beta": _beta(rets[s], market) if market else None} for s in symbols]
    weighted_vol = sum(w[s] * (_vol_pct(rets[s]) or 0) for s in symbols)
    port_vol = _vol_pct(port)
    return {
        **out,
        "period": {"from": dates[0], "to": dates[-1], "trading_days": len(dates) - 1},
        "volatility_1y_pct": port_vol,
        "return_1y_pct": (value[-1] - 1) * 100,
        "max_drawdown_1y_pct": _max_drawdown_pct(value),
        "beta": _beta(port, market) if market else None,
        "average_pair_correlation": statistics.fmean(pairs) if pairs else None,
        "diversification_ratio": weighted_vol / port_vol if port_vol else None,
        "per_holding": per,
        "method": "Daily closes over the last year of shared trading days, rebalanced daily to the given weights. "
                  "Past volatility and drawdown describe history; they don't predict future losses.",
    }

