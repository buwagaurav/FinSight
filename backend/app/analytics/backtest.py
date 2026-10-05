"""Backtests of a few standard indicator rules on one stock, always next to buy-and-hold.

Rules are fixed (standard settings, nothing to tune), long-only (Indian delivery trades can't be short), and traded
honestly:
- no look-ahead: a signal uses the day's close and the trade happens at the next day's open;
- whole shares from a fixed starting capital, idle cash earns nothing;
- every trade pays costs: Indian delivery charges (STT, exchange and SEBI fees, GST, stamp duty, depository charge)
  or US fees, plus slippage. Rates are approximate; tax on gains is not included.
Pure arithmetic over bars the caller supplies.
"""
from dataclasses import dataclass, field
from datetime import date

from app.analytics import indicators as I

CAPITAL = 100_000.0                          # ₹1 lakh
CAPITAL_BY_MARKET = {"IN": CAPITAL, "US": 10_000.0}   # $10,000 for US stocks


@dataclass(frozen=True)
class Costs:
    stt: float = 0.0                 # securities transaction tax, each side (India delivery: 0.1%)
    exchange: float = 0.0            # exchange transaction charge, each side
    sebi: float = 0.0                # SEBI turnover fee, each side
    stamp_buy: float = 0.0           # stamp duty on buys
    gst: float = 0.0                 # GST on brokerage + exchange + SEBI charges
    brokerage: float = 0.0           # per side, fraction of value
    brokerage_cap: float = 0.0       # per order (0 = no cap)
    fee_sell: float = 0.0            # regulatory fee on sells (US SEC fee)
    per_sell: float = 0.0            # flat charge per sell (India depository/DP charge)
    slippage: float = 0.0005         # worse fill than the open price, each side

    def charge(self, side: str, value: float) -> float:
        brokerage = value * self.brokerage
        if self.brokerage_cap:
            brokerage = min(brokerage, self.brokerage_cap)
        exchange, sebi = value * self.exchange, value * self.sebi
        total = brokerage + exchange + sebi + value * self.stt + (brokerage + exchange + sebi) * self.gst
        if side == "buy":
            total += value * self.stamp_buy
        else:
            total += value * self.fee_sell + self.per_sell
        return total


# Approximate 2026 rates; brokers differ (many charge no brokerage on delivery trades)
INDIA = Costs(stt=0.001, exchange=0.0000297, sebi=0.000001, stamp_buy=0.00015, gst=0.18, per_sell=15.93)
US = Costs(fee_sell=0.0000278)
COST_NOTES = {
    "IN": "STT 0.1% on each side, NSE charges 0.00297%, SEBI fee, 18% GST on those, stamp duty 0.015% on buys, "
          "₹15.93 depository charge per sale, and 0.05% slippage each way. No brokerage (most brokers charge none "
          "on delivery trades).",
    "US": "SEC fee on sales and 0.05% slippage each way; no commission.",
}

STRATEGIES = {
    "ema_trend": {"name": "EMA 50/200 trend", "rule": "Hold while the 50-day EMA is above the 200-day EMA; otherwise stay in cash."},
    "rsi": {"name": "RSI 30/70", "rule": "Buy when RSI (14) falls below 30; sell when it rises above 70."},
    "macd": {"name": "MACD crossover", "rule": "Hold while MACD (12, 26, 9) is above its signal line; otherwise stay in cash."},
    "supertrend": {"name": "Supertrend", "rule": "Hold while Supertrend (10, 3) shows an uptrend; otherwise stay in cash."},
}
WARM_UP = 200   # bars before the first trade, so every rule (EMA 200 needs most) starts on the same day


def signals(strategy: str, high: list, low: list, close: list) -> list[int | None]:
    """Desired position after each bar's close: 1 = hold the stock, 0 = cash, None = not enough data yet."""
    if strategy == "ema_trend":
        fast, slow = I.ema(close, 50), I.ema(close, 200)
        return [None if f is None or s is None else int(f > s) for f, s in zip(fast, slow)]
    if strategy == "macd":
        line, sig, _ = I.macd(close)
        return [None if a is None or b is None else int(a > b) for a, b in zip(line, sig)]
    if strategy == "supertrend":
        _, direction = I.supertrend(high, low, close)
        return [None if d is None else int(d == 1) for d in direction]
    if strategy == "rsi":
        r, out, holding = I.rsi(close), [], 0
        for v in r:
            if v is None:
                out.append(None)
                continue
            if not holding and v < 30:
                holding = 1
            elif holding and v > 70:
                holding = 0
            out.append(holding)
        return out
    raise ValueError(f"Unknown strategy {strategy}")


@dataclass
class Result:
    equity: list[float] = field(default_factory=list)
    trades: list[dict] = field(default_factory=list)
    costs_paid: float = 0.0
    bars_invested: int = 0


def simulate(dates: list[date], opens: list[float], closes: list[float], desired: list[int | None], start: int,
             costs: Costs, capital: float = CAPITAL) -> Result:
    """Trade `desired` (decided at each close) at the next open, from bar `start`. Equity is marked at each close."""
    res = Result()
    cash, shares, entry = capital, 0, None
    for t in range(start, len(closes)):
        want = desired[t - 1] if t > start else None   # yesterday's close decides today's open
        if want == 1 and shares == 0:
            price = opens[t] * (1 + costs.slippage)
            qty = int(cash // price)
            while qty > 0 and qty * price + costs.charge("buy", qty * price) > cash:
                qty -= 1
            if qty > 0:
                fee = costs.charge("buy", qty * price)
                cash -= qty * price + fee
                res.costs_paid += fee
                shares, entry = qty, {"entry_date": dates[t].isoformat(), "entry_price": price, "cost_in": fee}
        elif want == 0 and shares > 0:
            price = opens[t] * (1 - costs.slippage)
            fee = costs.charge("sell", shares * price)
            cash += shares * price - fee
            res.costs_paid += fee
            invested = shares * entry["entry_price"] + entry["cost_in"]
            res.trades.append({**_trade(entry, shares), "exit_date": dates[t].isoformat(), "exit_price": price,
                               "return_pct": ((shares * price - fee) / invested - 1) * 100, "open": False})
            shares, entry = 0, None
        res.equity.append(cash + shares * closes[t])
        res.bars_invested += shares > 0
    if shares:   # still holding at the end: shown at the last close, not sold
        invested = shares * entry["entry_price"] + entry["cost_in"]
        res.trades.append({**_trade(entry, shares), "exit_date": None, "exit_price": closes[-1],
                           "return_pct": (shares * closes[-1] / invested - 1) * 100, "open": True})
    return res


def _trade(entry: dict, shares: int) -> dict:
    return {"entry_date": entry["entry_date"], "entry_price": entry["entry_price"], "shares": shares}


def metrics(equity: list[float], dates: list[date], res: Result | None = None, capital: float = CAPITAL) -> dict:
    years = max((dates[-1] - dates[0]).days / 365.25, 1 / 365.25)
    peak, worst = equity[0], 0.0
    for v in equity:
        peak = max(peak, v)
        worst = min(worst, v / peak - 1)
    out = {"final_value": equity[-1], "total_return_pct": (equity[-1] / capital - 1) * 100,
           "cagr_pct": ((equity[-1] / capital) ** (1 / years) - 1) * 100 if equity[-1] > 0 else -100.0,
           "max_drawdown_pct": worst * 100}
    if res is not None:
        closed = [t for t in res.trades if not t["open"]]
        wins = [t["return_pct"] for t in closed if t["return_pct"] > 0]
        losses = [t["return_pct"] for t in closed if t["return_pct"] <= 0]
        streak = longest = 0
        for t in closed:
            streak = streak + 1 if t["return_pct"] <= 0 else 0
            longest = max(longest, streak)
        out.update(trades=len(closed), open_trade=any(t["open"] for t in res.trades),
                   time_invested_pct=res.bars_invested / len(equity) * 100,
                   win_rate_pct=len(wins) / len(closed) * 100 if closed else None,
                   avg_win_pct=sum(wins) / len(wins) if wins else None,
                   avg_loss_pct=sum(losses) / len(losses) if losses else None,
                   worst_losing_streak=longest, costs_paid=res.costs_paid)
    return out


def yearly(dates: list[date], curves: dict[str, list[float]], capital: float = CAPITAL) -> list[dict]:
    """Calendar-year returns for each equity curve (the first year is partial)."""
    rows, prev = [], {k: capital for k in curves}
    for i, d in enumerate(dates):
        if i == len(dates) - 1 or dates[i + 1].year != d.year:   # the year's last bar
            rows.append({"year": d.year, "partial": False,
                         **{k: (curve[i] / prev[k] - 1) * 100 for k, curve in curves.items()}})
            prev = {k: curve[i] for k, curve in curves.items()}
    if rows:   # a year the period only partly covers
        rows[0]["partial"] = (dates[0].month, dates[0].day) > (1, 7)
        rows[-1]["partial"] = rows[-1]["partial"] or (dates[-1].month, dates[-1].day) < (12, 24)
    return rows


def run_all(dates: list[date], opens: list, highs: list, lows: list, closes: list, market: str,
            years: int | None = None) -> dict:
    """Every strategy and buy-and-hold over the same period: from the later of WARM_UP bars in and `years` back."""
    costs = INDIA if market == "IN" else US
    capital = CAPITAL_BY_MARKET[market]
    start = WARM_UP
    if years:
        cutoff = date(dates[-1].year - years, dates[-1].month, min(dates[-1].day, 28))
        start = max(start, next((i for i, d in enumerate(dates) if d >= cutoff), start))
    if len(closes) - start < 60:
        raise ValueError("Not enough price history to backtest (needs about a year after a 200-day warm-up).")
    period = dates[start:]

    hold = simulate(dates, opens, closes, [1] * len(closes), start, costs, capital)   # buys at the first open, never sells
    curves = {"buy_hold": hold.equity}
    out = {"buy_hold": {"name": "Buy and hold", "rule": "Buy on the first day and hold to the end.",
                        **metrics(hold.equity, period, hold, capital)}}
    for key, info in STRATEGIES.items():
        res = simulate(dates, opens, closes, signals(key, highs, lows, closes), start, costs, capital)
        curves[key] = res.equity
        out[key] = {**info, **metrics(res.equity, period, res, capital), "trades_list": res.trades}
    for key in STRATEGIES:
        out[key]["cagr_vs_hold_pct"] = out[key]["cagr_pct"] - out["buy_hold"]["cagr_pct"]
    step = max(1, -(-len(period) // 300))   # at most ~300 points per curve: plenty for a chart
    idx = list(range(0, len(period), step))
    if idx[-1] != len(period) - 1:
        idx.append(len(period) - 1)
    return {
        "period": {"from": period[0].isoformat(), "to": period[-1].isoformat(),
                   "years": round((period[-1] - period[0]).days / 365.25, 1), "bars": len(period)},
        "capital": capital, "costs": COST_NOTES[market],
        "results": out,
        "curves": {"dates": [period[i].isoformat() for i in idx], **{k: [round(c[i], 2) for i in idx] for k, c in curves.items()}},
        "yearly": yearly(period, curves, capital),
    }

