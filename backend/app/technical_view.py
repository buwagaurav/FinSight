"""The stock page's Technicals tab: price bars with common indicators, and a plain-language reading of each.

Matches TradingView's defaults so the numbers agree with what traders see there:
- prices adjusted for splits but not dividends (Yahoo's unadjusted OHLC is already split-adjusted);
- indicators computed over as much history as Yahoo gives (10 years daily, all weekly, 60 days of 5-minute bars),
  so long averages have forgotten their starting point, as on TradingView, which uses the full history;
- standard settings, including TradingView's Stochastic (14, 1, 3).
Readings describe what an indicator shows now; they are not buy or sell signals.
"""
from datetime import datetime, timezone

from app import candles
from app.analytics import indicators as I
from app.cache import cached
from app.providers import sec, yahoo

# timeframe -> (Yahoo period fetched, interval, bars shown, adjust for dividends, cache seconds, bar noun)
TIMEFRAMES = {
    "daily": ("10y", "1d", 252, False, 900, "day"),
    "weekly": ("max", "1wk", 260, False, 3600, "week"),
    "intraday": ("60d", "5m", 375, False, 120, "bar"),   # 5-minute bars: ~75 a day, so 5 days are shown
}
# While the market is open, the page re-asks this often and the server keeps fetched bars at most this long, so
# today's bar and every indicator move with the market (Yahoo itself is ~1-2 minutes behind). One Yahoo request per
# stock per period, however many people are watching.
LIVE_SECONDS = {"intraday": 60, "daily": 180, "weekly": 900}


def _r(v, digits=2):
    return None if v is None else round(v, digits)


def _cross(a: list, b: list, within: int) -> int | None:
    """+1 if `a` crossed above `b` in the last `within` bars, -1 if below, else None."""
    for i in range(len(a) - 1, max(len(a) - 1 - within, 0), -1):
        if None in (a[i], b[i], a[i - 1], b[i - 1]):
            break
        if a[i - 1] <= b[i - 1] and a[i] > b[i]:
            return 1
        if a[i - 1] >= b[i - 1] and a[i] < b[i]:
            return -1
    return None


def build(symbol: str, timeframe: str = "daily") -> dict:
    symbol = yahoo.normalize_symbol(symbol)
    period, interval, shown, adjust, ttl, noun = TIMEFRAMES[timeframe]
    is_open = candles.session_open(symbol)
    if is_open:
        ttl = LIVE_SECONDS[timeframe]
    bars = cached(("indicator-bars", symbol, timeframe), ttl, lambda: candles._fetch(symbol, period, interval, adjust))
    if len(bars) < 30:
        raise LookupError(symbol)
    o, h, l, c, v = ([b[k] for b in bars] for k in (1, 2, 3, 4, 5))
    ts = [b[6] for b in bars]
    sym = "$" if sec.is_us(symbol) else "₹"

    ema20, ema50, ema200 = I.ema(c, 20), I.ema(c, 50), I.ema(c, 200)
    sma50, sma200 = I.sma(c, 50), I.sma(c, 200)
    bb_up, bb_mid, bb_low = I.bollinger(c)
    st_line, st_dir = I.supertrend(h, l, c)
    rsi = I.rsi(c)
    macd, macd_sig, macd_hist = I.macd(c)
    k, d = I.stochastic(h, l, c)   # TradingView's default (14, 1, 3)
    adx, pdi, mdi = I.adx(h, l, c)
    atr = I.atr(h, l, c)
    obv = I.obv(c, v)
    sessions = [datetime.fromtimestamp(t / 1000, candles.SESSIONS[candles.market(symbol)][0]).date().isoformat() for t in ts]
    vwap = I.vwap(h, l, c, v, sessions) if timeframe == "intraday" else None
    dc_up, dc_mid, dc_low = I.donchian(h, l)
    kc_up, kc_mid, kc_low = I.keltner(h, l, c)
    aroon_up, aroon_down = I.aroon(h, l)
    ich = I.ichimoku(h, l)
    piv = _pivots(bars, sessions, timeframe, is_open)

    series = {"ema20": ema20, "ema50": ema50, "ema200": ema200, "sma50": sma50, "sma200": sma200,
              "bb_upper": bb_up, "bb_mid": bb_mid, "bb_lower": bb_low, "supertrend": st_line, "supertrend_dir": st_dir,
              "rsi": rsi, "macd": macd, "macd_signal": macd_sig, "macd_hist": macd_hist, "stoch_k": k, "stoch_d": d,
              "adx": adx, "plus_di": pdi, "minus_di": mdi, "atr": atr, "obv": obv,
              "donchian_upper": dc_up, "donchian_mid": dc_mid, "donchian_lower": dc_low,
              "keltner_upper": kc_up, "keltner_mid": kc_mid, "keltner_lower": kc_low,
              "cci": I.cci(h, l, c), "williams_r": I.williams_r(h, l, c), "mfi": I.mfi(h, l, c, v),
              "aroon_up": aroon_up, "aroon_down": aroon_down, "roc": I.roc(c), "psar": I.psar(h, l),
              "ichimoku_tenkan": ich["tenkan"], "ichimoku_kijun": ich["kijun"],
              "ichimoku_span_a": ich["span_a"], "ichimoku_span_b": ich["span_b"]}
    if vwap:
        series["vwap"] = vwap
    start = max(0, len(bars) - shown)
    out_series = {name: [(_r(x) if not isinstance(x, int) or name == "obv" else x) for x in vals[start:]]
                  for name, vals in series.items()}

    return {
        "symbol": symbol, "timeframe": timeframe, "interval": interval, "bar": noun,
        "bars": bars[start:], "series": out_series,
        "readings": readings(c, v, series, sym, noun, long_term=timeframe != "intraday", pivot=piv),
        "pivots": piv,
        "market": {"id": candles.market(symbol), "open": is_open,
                   "last_bar": datetime.fromtimestamp(ts[-1] / 1000, timezone.utc).isoformat()},
        "refresh_seconds": LIVE_SECONDS[timeframe] if is_open else None,
        "source": {"name": "Yahoo Finance chart data", "url": f"https://finance.yahoo.com/quote/{yahoo.yahoo_ticker(symbol)}/chart"},
        "note": "Indicators describe past price and volume behaviour. They are not buy or sell signals and don't "
                "predict prices. Settings and price adjustment (splits, not dividends) match TradingView's defaults; "
                "OBV's level depends on where the history starts, so compare its direction rather than its value.",
    }


def _pivots(bars: list, sessions: list[str], timeframe: str, is_open: bool) -> dict | None:
    """Classic pivots from the last completed period: the previous day for daily and intraday views, the previous
    week for weekly. A bar still forming (market open) doesn't count."""
    if timeframe == "intraday":
        days = sorted(set(sessions))
        done = days[:-1] if is_open else days   # today's session isn't finished while the market is open
        if not done:
            return None
        day = [b for b, d in zip(bars, sessions) if d == done[-1]]
        h, l, c = max(b[2] for b in day), min(b[3] for b in day), day[-1][4]
        label = datetime.fromisoformat(done[-1]).strftime("%d %b %Y")   # same style as daily bars
    else:
        bar = bars[-2] if is_open and len(bars) > 1 else bars[-1]
        h, l, c, label = bar[2], bar[3], bar[4], bar[0]
    return {"basis": f"{'week of ' if timeframe == 'weekly' else ''}{label}",
            "levels": {k: round(x, 2) for k, x in I.pivots(h, l, c).items()}}


def readings(c: list, v: list, s: dict, sym: str, noun: str, long_term: bool = True, pivot: dict | None = None) -> list[dict]:
    """One plain-language line per indicator, with a tone: positive, negative or neutral."""
    price = c[-1]
    last = {name: I.last(vals) for name, vals in s.items()}
    out = []

    def add(key, name, value, text, tone="neutral"):
        out.append({"key": key, "name": name, "value": value, "reading": text, "tone": tone})

    for key, n, label in (("ema20", 20, "EMA 20"), ("ema50", 50, "EMA 50"), ("ema200", 200, "EMA 200")):
        if last[key] is not None:
            above = price > last[key]
            add(key, label, f"{sym}{last[key]:,.2f}",
                f"Price is {'above' if above else 'below'} its {n}-{noun} exponential average.", "positive" if above else "negative")
    if last["sma50"] is not None and last["sma200"] is not None:
        cross = _cross(s["sma50"], s["sma200"], 20)
        golden = last["sma50"] > last["sma200"]
        span = "long-term" if long_term else "200-bar"   # 200 five-minute bars is under three trading days
        text = f"50 above 200 ({'a recent golden cross' if cross == 1 else f'{span} uptrend'})" if golden else \
               f"50 below 200 ({'a recent death cross' if cross == -1 else f'{span} downtrend'})"
        add("sma", "SMA 50 / 200", f"{sym}{last['sma50']:,.0f} / {sym}{last['sma200']:,.0f}", text + ".", "positive" if golden else "negative")

    r = last["rsi"]
    if r is not None:
        if r >= 70:
            add("rsi", "RSI (14)", f"{r:.1f}", "Above 70: overbought zone. Strong trends can stay here for a while.", "neutral")
        elif r <= 30:
            add("rsi", "RSI (14)", f"{r:.1f}", "Below 30: oversold zone. Falling stocks can stay here for a while.", "neutral")
        else:
            add("rsi", "RSI (14)", f"{r:.1f}", f"{'Above' if r >= 50 else 'Below'} 50: {'bullish' if r >= 50 else 'bearish'} momentum.",
                "positive" if r >= 50 else "negative")

    if last["macd"] is not None and last["macd_signal"] is not None:
        above = last["macd"] > last["macd_signal"]
        cross = _cross(s["macd"], s["macd_signal"], 5)
        extra = " Crossed in the last 5 bars." if cross else ""
        add("macd", "MACD (12, 26, 9)", f"{last['macd']:.2f}",
            f"MACD is {'above' if above else 'below'} its signal line: momentum {'improving' if above else 'weakening'}.{extra}",
            "positive" if above else "negative")

    if last["bb_upper"] is not None:
        up, low = last["bb_upper"], last["bb_lower"]
        pct_b = (price - low) / (up - low) * 100 if up != low else 50
        widths = [(a - b) / m for a, b, m in zip(s["bb_upper"][-126:], s["bb_lower"][-126:], s["bb_mid"][-126:])
                  if None not in (a, b, m) and m]
        squeeze = len(widths) > 20 and widths[-1] <= sorted(widths)[len(widths) // 10]
        where = "above the upper band" if price > up else "below the lower band" if price < low else f"{pct_b:.0f}% of the way up the bands"
        add("bollinger", "Bollinger Bands (20, 2)", f"{sym}{low:,.0f} – {sym}{up:,.0f}",
            f"Price is {where}." + (" The bands are unusually narrow (a squeeze), which often comes before a bigger move." if squeeze else ""))

    if last["supertrend"] is not None:
        up = s["supertrend_dir"][-1] == 1
        flips = [i for i in range(len(s["supertrend_dir"]) - 1, max(len(s["supertrend_dir"]) - 6, 0), -1)
                 if s["supertrend_dir"][i] != s["supertrend_dir"][i - 1] and s["supertrend_dir"][i - 1] is not None]
        add("supertrend", "Supertrend (10, 3)", f"{sym}{last['supertrend']:,.2f}",
            f"{'Uptrend' if up else 'Downtrend'}: price is {'above' if up else 'below'} the line." + (" Flipped in the last 5 bars." if flips else ""),
            "positive" if up else "negative")

    a, d_plus, d_minus = last["adx"], last["plus_di"], last["minus_di"]
    if a is not None:
        direction = "up" if d_plus > d_minus else "down"
        text = ("No clear trend (below 20)." if a < 20 else f"A trend may be forming ({direction})." if a < 25
                else f"Strong {direction}trend (above 25).")
        add("adx", "ADX (14)", f"{a:.1f}", text + f" +DI {d_plus:.0f}, −DI {d_minus:.0f}.",
            "neutral" if a < 25 else "positive" if direction == "up" else "negative")

    kk, dd = last["stoch_k"], last["stoch_d"]
    if kk is not None and dd is not None:
        zone = "overbought zone (above 80)" if kk >= 80 else "oversold zone (below 20)" if kk <= 20 else "middle of its range"
        add("stochastic", "Stochastic (14, 1, 3)", f"{kk:.1f}", f"%K is in the {zone}, {'above' if kk > dd else 'below'} %D.")

    if last["atr"] is not None:
        add("atr", "ATR (14)", f"{sym}{last['atr']:,.2f}",
            f"Typical range per {noun if long_term else '5-minute bar'}: {sym}{last['atr']:,.2f} "
            f"({last['atr'] / price * 100:.1f}% of the price).")

    if len(s["obv"]) > 21:
        obv_up, price_up = s["obv"][-1] > s["obv"][-21], c[-1] > c[-21]
        text = ("Volume flow is rising with the price (confirms the move)." if obv_up and price_up else
                "Volume flow is falling with the price (confirms the move)." if not obv_up and not price_up else
                "Volume flow and price disagree over the last 20 bars (a divergence).")
        add("obv", "OBV", f"{s['obv'][-1]:,.0f}", text, "positive" if obv_up and price_up else "negative" if not (obv_up or price_up) else "neutral")

    sa, sb = last["ichimoku_span_a"], last["ichimoku_span_b"]
    if sa is not None and sb is not None:
        top, bottom = max(sa, sb), min(sa, sb)
        where = "above" if price > top else "below" if price < bottom else "inside"
        cross = "conversion line above the base line" if last["ichimoku_tenkan"] > last["ichimoku_kijun"] else "conversion line below the base line"
        add("ichimoku", "Ichimoku (9, 26, 52)", f"{sym}{bottom:,.0f} – {sym}{top:,.0f}",
            f"Price is {where} the cloud; {cross}.", "positive" if where == "above" else "negative" if where == "below" else "neutral")

    if last["psar"] is not None:
        below = last["psar"] < price
        add("psar", "Parabolic SAR", f"{sym}{last['psar']:,.2f}",
            f"SAR is {'below' if below else 'above'} the price: {'uptrend' if below else 'downtrend'}.", "positive" if below else "negative")

    if last["donchian_upper"] is not None:
        up, low = last["donchian_upper"], last["donchian_lower"]
        prior_up = s["donchian_upper"][-2] if len(s["donchian_upper"]) > 1 else None
        prior_low = s["donchian_lower"][-2] if len(s["donchian_lower"]) > 1 else None
        if prior_up is not None and price > prior_up:
            text, tone = f"Closed at a new 20-{noun} high (a breakout).", "positive"
        elif prior_low is not None and price < prior_low:
            text, tone = f"Closed at a new 20-{noun} low (a breakdown).", "negative"
        else:
            text, tone = f"Price is {(price - low) / (up - low) * 100 if up != low else 50:.0f}% of the way up its 20-{noun} range.", "neutral"
        add("donchian", "Donchian Channels (20)", f"{sym}{low:,.0f} – {sym}{up:,.0f}", text, tone)

    if last["keltner_upper"] is not None:
        up, low = last["keltner_upper"], last["keltner_lower"]
        text = ("Price is above the upper channel: a strong move up." if price > up else
                "Price is below the lower channel: a strong move down." if price < low else "Price is inside the channel.")
        add("keltner", "Keltner Channels (20, 2)", f"{sym}{low:,.0f} – {sym}{up:,.0f}", text,
            "positive" if price > up else "negative" if price < low else "neutral")

    if last["cci"] is not None:
        x = last["cci"]
        text = ("Above +100: unusually strong upward momentum." if x > 100 else
                "Below −100: unusually strong downward momentum." if x < -100 else "Between −100 and +100: no extreme.")
        add("cci", "CCI (20)", f"{x:.0f}", text, "positive" if x > 100 else "negative" if x < -100 else "neutral")

    if last["williams_r"] is not None:
        x = last["williams_r"]
        zone = "overbought zone (above −20)" if x > -20 else "oversold zone (below −80)" if x < -80 else "middle of its range"
        add("williams_r", "Williams %R (14)", f"{x:.1f}", f"In the {zone}.")

    if last["mfi"] is not None:
        x = last["mfi"]
        if x >= 80:
            add("mfi", "MFI (14)", f"{x:.1f}", "Above 80: overbought zone, with heavy volume on up days.")
        elif x <= 20:
            add("mfi", "MFI (14)", f"{x:.1f}", "Below 20: oversold zone, with heavy volume on down days.")
        else:
            add("mfi", "MFI (14)", f"{x:.1f}", f"{'Above' if x >= 50 else 'Below'} 50: money flow is {'positive' if x >= 50 else 'negative'}.",
                "positive" if x >= 50 else "negative")

    au, ad = last["aroon_up"], last["aroon_down"]
    if au is not None and ad is not None:
        if au >= 70 and ad <= 30:
            text, tone = "Recent highs, no recent lows: an uptrend.", "positive"
        elif ad >= 70 and au <= 30:
            text, tone = "Recent lows, no recent highs: a downtrend.", "negative"
        else:
            text, tone = "No clear trend from the timing of highs and lows.", "neutral"
        add("aroon", "Aroon (14)", f"Up {au:.0f} / Down {ad:.0f}", text, tone)

    if last["roc"] is not None:
        x = last["roc"]
        add("roc", "Rate of Change (9)", f"{x:+.2f}%", f"Price is {'up' if x >= 0 else 'down'} {abs(x):.2f}% over 9 {noun}s.",
            "positive" if x >= 0 else "negative")

    if pivot:
        lv = pivot["levels"]
        above = [k for k in ("R1", "R2", "R3") if lv[k] > price]
        below = [k for k in ("S1", "S2", "S3") if lv[k] < price]
        nxt = f"next resistance {above[0]} {sym}{lv[above[0]]:,.2f}" if above else "above all resistance levels"
        sup = f"support {below[0]} {sym}{lv[below[0]]:,.2f}" if below else "below all support levels"
        add("pivots", "Pivot points (classic)", f"{sym}{lv['P']:,.2f}",
            f"From {pivot['basis']}. Price is {'above' if price > lv['P'] else 'below'} the pivot; {nxt}; {sup}.",
            "positive" if price > lv["P"] else "negative")

    if s.get("vwap") and last.get("vwap") is not None:
        above = price > last["vwap"]
        add("vwap", "VWAP (today)", f"{sym}{last['vwap']:,.2f}", f"Price is {'above' if above else 'below'} today's volume-weighted average.",
            "positive" if above else "negative")
    return out
