"""Forecasting research harness: walk-forward backtest of return forecasters, split by market regime.

Why this exists: FinSight must not show a forecast to users unless it beats a naive baseline out of
sample, in every kind of market (the out-of-distribution lesson). New models - including time-series
foundation models such as FinCast or text+price models such as StockTime - plug in as a Forecaster and
face exactly the same gate.

Run:  cd backend && ../.venv/bin/python -m research.forecast_backtest
"""
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf


# A fixed list keeps results comparable between runs. Today's large caps -> survivorship bias (see caveats).
UNIVERSE = [
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY", "BHARTIARTL", "ITC", "SBIN", "LT", "HINDUNILVR",
    "BAJFINANCE", "KOTAKBANK", "AXISBANK", "HCLTECH", "MARUTI", "SUNPHARMA", "ASIANPAINT", "TITAN",
    "ULTRACEMCO", "NTPC", "ONGC", "POWERGRID", "WIPRO", "NESTLEIND", "M&M", "ADANIENT", "ADANIPORTS",
    "COALINDIA", "TATASTEEL", "JSWSTEEL", "BAJAJFINSV", "TECHM", "GRASIM", "HINDALCO", "DRREDDY",
    "CIPLA", "BRITANNIA", "EICHERMOT", "HEROMOTOCO", "APOLLOHOSP", "DIVISLAB", "TATACONSUM",
    "BAJAJ-AUTO", "SBILIFE", "HDFCLIFE", "INDUSINDBK", "SHRIRAMFIN", "TRENT", "BEL", "ETERNAL",
]

HORIZON = 63          # trading days ahead (~3 months)
STEP = 21             # re-forecast monthly
MIN_HISTORY = 504     # two years of data before the first forecast
INTERVAL = 0.8        # nominal coverage of the prediction interval
OUT = Path(__file__).resolve().parent.parent / "data" / "research" / "forecast_backtest.json"


# ---------------------------------------------------------------- forecasters

@dataclass
class Forecast:
    point: float   # predicted log return over HORIZON
    low: float     # lower bound of the INTERVAL prediction interval
    high: float


class Forecaster:
    """Interface. `history` is every stock's log price up to and including the forecast date - never after.

    To add a model (e.g. a FinCast checkpoint): subclass, implement predict() using only `history`,
    add it to FORECASTERS, and run this script. It is compared against RandomWalk in every regime."""
    name = "base"

    def predict(self, history: pd.DataFrame, t: int) -> dict[str, Forecast]:
        raise NotImplementedError


def _past_horizon_returns(logp: pd.Series, t: int, window: int) -> np.ndarray:
    """Non-overlapping-enough sample of past HORIZON-day log returns ending at or before t."""
    s = logp.iloc[max(0, t - window):t + 1].dropna().to_numpy()
    if len(s) <= HORIZON:
        return np.array([])
    return s[HORIZON:] - s[:-HORIZON]


def _interval(sample: np.ndarray, center: float) -> tuple[float, float]:
    q = (1 - INTERVAL) / 2
    dev = sample - sample.mean()
    return center + np.quantile(dev, q), center + np.quantile(dev, 1 - q)


class RandomWalk(Forecaster):
    """Baseline: expect no change. Interval from the stock's last year of 3-month moves."""
    name = "random_walk"

    def predict(self, history, t):
        out = {}
        for sym in history.columns:
            r = _past_horizon_returns(history[sym], t, 252)
            if len(r) < 30:
                continue
            out[sym] = Forecast(0.0, *_interval(r, 0.0))
        return out


class HistoricalDrift(Forecaster):
    """Expect the stock's average 3-month return over the past 3 years to continue."""
    name = "historical_drift"

    def predict(self, history, t):
        out = {}
        for sym in history.columns:
            r = _past_horizon_returns(history[sym], t, 756)
            if len(r) < 60:
                continue
            mu = float(r.mean())
            out[sym] = Forecast(mu, *_interval(r, mu))
        return out


class Momentum(Forecaster):
    """Point forecast = beta x trailing 12-1 month return, with beta re-estimated each date by pooled
    regression on data that was fully observable at that date (no look-ahead)."""
    name = "momentum_12_1"

    def _signal(self, history, t):
        if t < 252:
            return None
        return history.iloc[t - 21] - history.iloc[t - 252]

    def predict(self, history, t):
        xs, ys = [], []
        for past in range(max(252, t - 756), t - HORIZON + 1, STEP):  # outcomes known by t
            sig = self._signal(history, past)
            fwd = history.iloc[past + HORIZON] - history.iloc[past]
            ok = sig.notna() & fwd.notna()
            xs.append(sig[ok].to_numpy()); ys.append(fwd[ok].to_numpy())
        if not xs or sum(len(x) for x in xs) < 200:
            return {}
        x, y = np.concatenate(xs), np.concatenate(ys)
        beta = float(np.cov(x, y)[0, 1] / np.var(x)) if np.var(x) > 0 else 0.0
        alpha = float(y.mean() - beta * x.mean())
        resid = y - (alpha + beta * x)
        sig_now = self._signal(history, t)
        out = {}
        for sym in history.columns:
            s = sig_now.get(sym)
            if s is None or math.isnan(s):
                continue
            mu = alpha + beta * float(s)
            out[sym] = Forecast(mu, *_interval(resid, mu))
        return out


FORECASTERS: list[Forecaster] = [RandomWalk(), HistoricalDrift(), Momentum()]


# ---------------------------------------------------------------- regimes

def label_regimes(index_logp: pd.Series) -> pd.DataFrame:
    """Market condition at each date, from the Nifty 50 index, using only information up to that date."""
    ret6m = index_logp - index_logp.shift(126)
    drawdown = np.exp(index_logp - index_logp.rolling(252, min_periods=1).max()) - 1
    trend = np.where(ret6m > math.log(1.08), "bull", np.where(ret6m < math.log(0.92), "bear", "sideways"))
    return pd.DataFrame({"trend": trend, "stress": np.where(drawdown < -0.15, "crash", "normal")}, index=index_logp.index)


# ---------------------------------------------------------------- evaluation

def _metrics(rows: pd.DataFrame) -> dict:
    if rows.empty:
        return {}
    err = rows["point"] - rows["actual"]
    nonzero = rows["point"] != 0
    by_date = rows.groupby("date")
    spreads = []
    for _, g in by_date:
        if len(g) >= 10 and g["point"].nunique() > 1:
            q = g["point"].rank(pct=True)
            spreads.append(g.loc[q > 0.8, "actual"].mean() - g.loc[q <= 0.2, "actual"].mean())
    return {
        "n": int(len(rows)),
        "dates": int(rows["date"].nunique()),
        "mae_pct": float(np.abs(err).mean() * 100),
        "directional_accuracy": float((np.sign(rows.loc[nonzero, "point"]) == np.sign(rows.loc[nonzero, "actual"])).mean())
        if nonzero.any() else None,
        "interval_coverage": float(((rows["actual"] >= rows["low"]) & (rows["actual"] <= rows["high"])).mean()),
        "top_minus_bottom_quintile_pct": float(np.mean(spreads) * 100) if spreads else None,
    }


def run() -> dict:
    tickers = [f"{s}.NS" for s in UNIVERSE]
    raw = yf.download(tickers + ["^NSEI"], period="10y", interval="1d", auto_adjust=True, progress=False)["Close"]
    raw = raw.dropna(how="all")
    logp = np.log(raw)
    index = logp.pop("^NSEI").ffill()
    regimes = label_regimes(index)
    dates = logp.index

    records = []
    for t in range(MIN_HISTORY, len(dates) - HORIZON, STEP):
        actual = logp.iloc[t + HORIZON] - logp.iloc[t]
        history = logp.iloc[:t + 1]
        for f in FORECASTERS:
            for sym, fc in f.predict(history, t).items():
                a = actual.get(sym)
                if a is None or math.isnan(a):
                    continue
                records.append({"model": f.name, "date": dates[t], "symbol": sym, "point": fc.point, "low": fc.low,
                                "high": fc.high, "actual": float(a), "trend": regimes["trend"].iloc[t],
                                "stress": regimes["stress"].iloc[t]})
    df = pd.DataFrame(records)
    midpoint = df["date"].min() + (df["date"].max() - df["date"].min()) / 2

    slices = {
        "all": lambda d: d,
        "bull": lambda d: d[d.trend == "bull"],
        "sideways": lambda d: d[d.trend == "sideways"],
        "bear": lambda d: d[d.trend == "bear"],
        "crash (Nifty >15% below 1y high)": lambda d: d[d.stress == "crash"],
        f"first half (to {midpoint:%Y-%m})": lambda d: d[d.date < midpoint],
        f"second half (from {midpoint:%Y-%m})": lambda d: d[d.date >= midpoint],
    }
    results = {name: {m: _metrics(fn(df[df.model == m])) for m in df.model.unique()} for name, fn in slices.items()}

    gate = {}
    for f in FORECASTERS[1:]:
        failures = [s for s, per_model in results.items()
                    if per_model.get(f.name) and per_model[f.name]["mae_pct"] >= per_model["random_walk"]["mae_pct"]]
        coverage = results["all"][f.name]["interval_coverage"]
        if abs(coverage - INTERVAL) > 0.05:
            failures.append(f"interval coverage {coverage:.0%} vs nominal {INTERVAL:.0%}")
        gate[f.name] = {"show_to_users": not failures, "fails_on": failures}

    report = {
        "setup": {
            "universe": f"{len(UNIVERSE)} current large-cap NSE stocks",
            "period": f"{dates[0]:%Y-%m-%d} to {dates[-1]:%Y-%m-%d}",
            "horizon_trading_days": HORIZON,
            "rebalance_every_days": STEP,
            "forecast_dates": int(df["date"].nunique()),
            "caveats": [
                "Survivorship bias: the universe is today's large caps, so past returns look better than an investor could have got.",
                "Forecasts overlap (3-month horizon, monthly steps), so observations are not independent.",
                "Log returns; costs, taxes and slippage ignored.",
            ],
        },
        "results": results,
        "promotion_gate": {
            "rule": "A model is shown to users only if its MAE beats the random walk in every slice and its "
                    f"{INTERVAL:.0%} interval covers {INTERVAL:.0%} +/- 5 points of outcomes.",
            "models": gate,
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str))
    return report


def _print(report: dict):
    print(json.dumps(report["setup"], indent=2))
    for slice_name, per_model in report["results"].items():
        print(f"\n{slice_name}")
        print(f"  {'model':18} {'n':>6} {'MAE%':>7} {'dir.acc':>8} {'cover':>6} {'Q5-Q1%':>7}")
        for m, r in per_model.items():
            if not r:
                continue
            da = f"{r['directional_accuracy']:.1%}" if r["directional_accuracy"] is not None else "-"
            sp = f"{r['top_minus_bottom_quintile_pct']:.2f}" if r["top_minus_bottom_quintile_pct"] is not None else "-"
            print(f"  {m:18} {r['n']:>6} {r['mae_pct']:>7.2f} {da:>8} {r['interval_coverage']:>6.1%} {sp:>7}")
    print("\nPromotion gate:", json.dumps(report["promotion_gate"], indent=2))


if __name__ == "__main__":
    _print(run())
