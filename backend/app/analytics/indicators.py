"""Technical indicators, computed as TradingView's built-ins do (Pine Script ta.ema, ta.rma, ta.rsi, ta.macd, ta.bb,
ta.atr, ta.supertrend, ta.dmi, ta.stoch, ta.vwap, ta.obv): EMAs seeded with an SMA, Wilder's smoothing (RMA) for
RSI, ATR and ADX, population standard deviation for Bollinger Bands.

Every function takes plain lists (oldest first) and returns a list of the same length, with None where there isn't
enough history yet (the "warm-up"). Pure arithmetic: fetching is done elsewhere.
"""
import math
import statistics

Series = list[float | None]


def sma(values: list[float], n: int) -> Series:
    out: Series = [None] * len(values)
    total = 0.0
    for i, v in enumerate(values):
        total += v
        if i >= n:
            total -= values[i - n]
        if i >= n - 1:
            out[i] = total / n
    return out


def _smooth(values: Series, n: int, alpha: float) -> Series:
    """Exponential smoothing seeded with the simple average of the first n available values."""
    out: Series = [None] * len(values)
    start = next((i for i, v in enumerate(values) if v is not None), None)
    if start is None or len(values) - start < n:
        return out
    seed = sum(values[start:start + n]) / n   # type: ignore[arg-type]
    out[start + n - 1] = prev = seed
    for i in range(start + n, len(values)):
        v = values[i]
        if v is None:
            continue
        prev = alpha * v + (1 - alpha) * prev
        out[i] = prev
    return out


def ema(values: Series, n: int) -> Series:
    return _smooth(values, n, 2 / (n + 1))


def rma(values: Series, n: int) -> Series:
    """Wilder's moving average (RSI, ATR, ADX)."""
    return _smooth(values, n, 1 / n)


def rsi(close: list[float], n: int = 14) -> Series:
    gains: Series = [None] + [max(b - a, 0.0) for a, b in zip(close, close[1:])]
    losses: Series = [None] + [max(a - b, 0.0) for a, b in zip(close, close[1:])]
    avg_gain, avg_loss = rma(gains, n), rma(losses, n)
    out: Series = []
    for g, l in zip(avg_gain, avg_loss):
        if g is None or l is None:
            out.append(None)
        elif l == 0:
            out.append(100.0)   # no down moves at all: 100, as TradingView shows
        else:
            out.append(100 - 100 / (1 + g / l))
    return out


def macd(close: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[Series, Series, Series]:
    f, s = ema(close, fast), ema(close, slow)
    line: Series = [a - b if a is not None and b is not None else None for a, b in zip(f, s)]
    sig = ema(line, signal)
    hist: Series = [a - b if a is not None and b is not None else None for a, b in zip(line, sig)]
    return line, sig, hist


def bollinger(close: list[float], n: int = 20, k: float = 2.0) -> tuple[Series, Series, Series]:
    mid = sma(close, n)
    upper: Series = [None] * len(close)
    lower: Series = [None] * len(close)
    for i in range(n - 1, len(close)):
        sd = statistics.pstdev(close[i - n + 1:i + 1])   # population SD, as Bollinger defined it
        upper[i], lower[i] = mid[i] + k * sd, mid[i] - k * sd   # type: ignore[operator]
    return upper, mid, lower


def true_range(high: list[float], low: list[float], close: list[float]) -> list[float]:
    return [high[0] - low[0]] + [max(h - l, abs(h - pc), abs(l - pc)) for h, l, pc in zip(high[1:], low[1:], close)]


def atr(high: list[float], low: list[float], close: list[float], n: int = 14) -> Series:
    return rma(true_range(high, low, close), n)


def supertrend(high: list[float], low: list[float], close: list[float], n: int = 10, mult: float = 3.0) -> tuple[Series, list[int | None]]:
    """(line, direction): direction 1 = price above the line (uptrend), -1 = below (downtrend)."""
    a = atr(high, low, close, n)
    line: Series = [None] * len(close)
    direction: list[int | None] = [None] * len(close)
    upper_prev = lower_prev = None
    for i in range(len(close)):
        if a[i] is None:
            continue
        mid = (high[i] + low[i]) / 2
        upper, lower = mid + mult * a[i], mid - mult * a[i]
        if upper_prev is not None:
            # bands only tighten while the trend holds, so the line trails price
            upper = upper if upper < upper_prev or close[i - 1] > upper_prev else upper_prev
            lower = lower if lower > lower_prev or close[i - 1] < lower_prev else lower_prev
        prev_dir = direction[i - 1] if i > 0 else None
        if prev_dir is None:
            d = 1 if close[i] > upper else -1
        elif prev_dir == -1:
            d = 1 if close[i] > upper_prev else -1   # type: ignore[operator]
        else:
            d = -1 if close[i] < lower_prev else 1   # type: ignore[operator]
        direction[i] = d
        line[i] = lower if d == 1 else upper
        upper_prev, lower_prev = upper, lower
    return line, direction


def adx(high: list[float], low: list[float], close: list[float], n: int = 14) -> tuple[Series, Series, Series]:
    """(ADX, +DI, -DI). ADX above ~25 means a strong trend (in either direction)."""
    plus_dm: Series = [None]
    minus_dm: Series = [None]
    for i in range(1, len(close)):
        up, down = high[i] - high[i - 1], low[i - 1] - low[i]
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
    tr: Series = [None] + true_range(high, low, close)[1:]
    s_tr, s_plus, s_minus = rma(tr, n), rma(plus_dm, n), rma(minus_dm, n)
    plus_di: Series = []
    minus_di: Series = []
    dx: Series = []
    for t, p, m in zip(s_tr, s_plus, s_minus):
        if t is None or p is None or m is None or t == 0:
            plus_di.append(None)
            minus_di.append(None)
            dx.append(None)
            continue
        pdi, mdi = 100 * p / t, 100 * m / t
        plus_di.append(pdi)
        minus_di.append(mdi)
        dx.append(100 * abs(pdi - mdi) / (pdi + mdi) if pdi + mdi else 0.0)
    return rma(dx, n), plus_di, minus_di


def stochastic(high: list[float], low: list[float], close: list[float], n: int = 14, smooth_k: int = 1,
               smooth_d: int = 3) -> tuple[Series, Series]:
    """Stochastic (%K, %D), 0-100: where the close sits in the last n bars' high-low range. Defaults are
    TradingView's (14, 1, 3); smooth_k=3 gives the "slow" stochastic."""
    fast: list[float] = []
    first = n - 1
    for i in range(first, len(close)):
        hh, ll = max(high[i - n + 1:i + 1]), min(low[i - n + 1:i + 1])
        fast.append(50.0 if hh == ll else 100 * (close[i] - ll) / (hh - ll))
    k = sma(fast, smooth_k)                                         # same length as fast, warm-up at the front
    d = _align(sma([v for v in k if v is not None], smooth_d), len(k))
    pad: Series = [None] * first
    return pad + k, pad + d


def _align(values: Series, length: int) -> Series:
    """Right-align `values` within `length` (warm-up Nones at the front)."""
    return [None] * (length - len(values)) + list(values)


def vwap(high: list[float], low: list[float], close: list[float], volume: list[float], session: list[str]) -> Series:
    """Volume-weighted average of the typical price, restarting each session (day)."""
    out: Series = []
    pv = vol = 0.0
    current = None
    for h, l, c, v, s in zip(high, low, close, volume, session):
        if s != current:
            current, pv, vol = s, 0.0, 0.0
        pv += (h + l + c) / 3 * v
        vol += v
        out.append(pv / vol if vol else None)
    return out


def obv(close: list[float], volume: list[float]) -> Series:
    out: Series = [0.0] if close else []
    for i in range(1, len(close)):
        step = volume[i] if close[i] > close[i - 1] else -volume[i] if close[i] < close[i - 1] else 0.0
        out.append(out[-1] + step)   # type: ignore[operator]
    return out


def last(series: Series) -> float | None:
    v = series[-1] if series else None
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else v


# ---------------------------------------------------------------- more indicators (TradingView defaults)

def highest(values: list[float], n: int) -> Series:
    return [None if i < n - 1 else max(values[i - n + 1:i + 1]) for i in range(len(values))]


def lowest(values: list[float], n: int) -> Series:
    return [None if i < n - 1 else min(values[i - n + 1:i + 1]) for i in range(len(values))]


def donchian(high: list[float], low: list[float], n: int = 20) -> tuple[Series, Series, Series]:
    """(upper, middle, lower): the highest high and lowest low of the last n bars, and their midpoint."""
    up, lo = highest(high, n), lowest(low, n)
    return up, [None if a is None else (a + b) / 2 for a, b in zip(up, lo)], lo


def keltner(high: list[float], low: list[float], close: list[float], n: int = 20, mult: float = 2.0,
            atr_n: int = 10) -> tuple[Series, Series, Series]:
    """(upper, middle, lower): an EMA of the close with bands mult x ATR away (TradingView: 20, 2, ATR 10)."""
    mid, a = ema(close, n), atr(high, low, close, atr_n)
    upper: Series = [None if m is None or r is None else m + mult * r for m, r in zip(mid, a)]
    lower: Series = [None if m is None or r is None else m - mult * r for m, r in zip(mid, a)]
    return upper, mid, lower


def cci(high: list[float], low: list[float], close: list[float], n: int = 20) -> Series:
    """Commodity Channel Index: how far the typical price is from its average, in units of mean deviation."""
    tp = [(h + l + c) / 3 for h, l, c in zip(high, low, close)]
    avg = sma(tp, n)
    out: Series = [None] * len(tp)
    for i in range(n - 1, len(tp)):
        window = tp[i - n + 1:i + 1]
        md = sum(abs(x - avg[i]) for x in window) / n
        out[i] = 0.0 if md == 0 else (tp[i] - avg[i]) / (0.015 * md)
    return out


def williams_r(high: list[float], low: list[float], close: list[float], n: int = 14) -> Series:
    """Williams %R, -100 to 0: where the close sits below the last n bars' high."""
    hh, ll = highest(high, n), lowest(low, n)
    return [None if a is None else (-50.0 if a == b else -100 * (a - c) / (a - b)) for a, b, c in zip(hh, ll, close)]


def mfi(high: list[float], low: list[float], close: list[float], volume: list[float], n: int = 14) -> Series:
    """Money Flow Index, 0-100: RSI-like, weighting each day's typical price by its volume."""
    tp = [(h + l + c) / 3 for h, l, c in zip(high, low, close)]
    pos = [0.0] + [tp[i] * volume[i] if tp[i] > tp[i - 1] else 0.0 for i in range(1, len(tp))]
    neg = [0.0] + [tp[i] * volume[i] if tp[i] < tp[i - 1] else 0.0 for i in range(1, len(tp))]
    out: Series = [None] * len(tp)
    for i in range(n, len(tp)):
        up, down = sum(pos[i - n + 1:i + 1]), sum(neg[i - n + 1:i + 1])
        out[i] = 100.0 if down == 0 else 100 - 100 / (1 + up / down)
    return out


def aroon(high: list[float], low: list[float], n: int = 14) -> tuple[Series, Series]:
    """(Aroon up, Aroon down), 0-100: how recently the highest high / lowest low of the last n+1 bars happened."""
    up: Series = [None] * len(high)
    down: Series = [None] * len(high)
    for i in range(n, len(high)):
        hw, lw = high[i - n:i + 1], low[i - n:i + 1]
        since_high = n - max(range(n + 1), key=lambda j: (hw[j], j))   # most recent bar wins a tie
        since_low = n - max(range(n + 1), key=lambda j: (-lw[j], j))
        up[i], down[i] = 100 * (n - since_high) / n, 100 * (n - since_low) / n
    return up, down


def roc(close: list[float], n: int = 9) -> Series:
    """Rate of change: % change over the last n bars."""
    return [None if i < n or close[i - n] == 0 else (close[i] / close[i - n] - 1) * 100 for i in range(len(close))]


def psar(high: list[float], low: list[float], start: float = 0.02, step: float = 0.02, cap: float = 0.2) -> Series:
    """Parabolic SAR (Wilder): a stop that trails the trend and jumps to the other side when price crosses it."""
    out: Series = [None] * len(high)
    if len(high) < 2:
        return out
    up = high[1] >= high[0]
    sar = low[0] if up else high[0]
    ep = high[1] if up else low[1]
    af = start
    for i in range(1, len(high)):
        sar = sar + af * (ep - sar)
        if up:
            sar = min(sar, low[i - 1], low[i - 2] if i >= 2 else low[i - 1])
            if low[i] < sar:   # reversal to down
                up, sar, ep, af = False, ep, low[i], start
            elif high[i] > ep:
                ep, af = high[i], min(af + step, cap)
        else:
            sar = max(sar, high[i - 1], high[i - 2] if i >= 2 else high[i - 1])
            if high[i] > sar:   # reversal to up
                up, sar, ep, af = True, ep, high[i], start
            elif low[i] < ep:
                ep, af = low[i], min(af + step, cap)
        out[i] = sar
    return out


def ichimoku(high: list[float], low: list[float], conv: int = 9, base: int = 26, span_b: int = 52,
             shift: int = 26) -> dict[str, Series]:
    """Conversion (Tenkan) and base (Kijun) lines, and the cloud (Senkou A/B) as it stands at each bar: the cloud
    values were computed shift-1 bars earlier and plotted forward, as TradingView draws it."""
    def mid(n):
        hh, ll = highest(high, n), lowest(low, n)
        return [None if a is None else (a + b) / 2 for a, b in zip(hh, ll)]
    tenkan, kijun, b_raw = mid(conv), mid(base), mid(span_b)
    a_raw: Series = [None if t is None or k is None else (t + k) / 2 for t, k in zip(tenkan, kijun)]
    lag = shift - 1
    return {"tenkan": tenkan, "kijun": kijun,
            "span_a": [None] * lag + a_raw[:len(a_raw) - lag], "span_b": [None] * lag + b_raw[:len(b_raw) - lag]}


def pivots(high: float, low: float, close: float) -> dict[str, float]:
    """Classic floor-trader pivot levels from one completed period's high, low and close."""
    p = (high + low + close) / 3
    return {"P": p, "R1": 2 * p - low, "S1": 2 * p - high, "R2": p + (high - low), "S2": p - (high - low),
            "R3": high + 2 * (p - low), "S3": low - 2 * (high - p)}
