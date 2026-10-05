"""Every backtest rule run on every Nifty 50 stock, so one stock's lucky result can't pass for a rule that works.

With 13 rules tested, some will beat buy-and-hold on any single stock by chance. What matters is how often a rule
does it across many stocks, and by how much. This job runs every rule (and buy-and-hold) on each current Nifty 50
company, for the full ~9 years and the last 5, and stores a summary per rule. It makes ~50 Yahoo requests, so it
runs as a nightly job (GitHub Actions) rather than on page views:

    python -m app.backtest_universe            # all 50
    python -m app.backtest_universe --limit 5  # quick check

Caveat shown with the results: these are today's Nifty 50 members, companies that did well enough to be in the
index now (survivorship bias), so absolute returns are flattering; comparing rules with buy-and-hold on the same
stocks is the useful part.
"""
import argparse
import csv
import io
import statistics
import sys
import time
from datetime import datetime

import requests

from app import candles, db
from app.analytics import backtest

UNIVERSE = "NIFTY50"
CONSTITUENTS = ["https://archives.nseindia.com/content/indices/ind_nifty50list.csv",
                "https://www.niftyindices.com/IndexConstituent/ind_nifty50list.csv"]
# NSE's list as of 2026-10-05, used if NSE's site can't be reached (it sometimes blocks cloud servers). The index
# changes a few times a year; the live list is always tried first.
FALLBACK_NIFTY50 = """
    ADANIENT ADANIPORTS APOLLOHOSP ASIANPAINT AXISBANK BSE BAJAJ-AUTO BAJFINANCE BAJAJFINSV BEL
    BHARTIARTL CIPLA COALINDIA DRREDDY EICHERMOT ETERNAL GRASIM HCLTECH HDFCBANK HDFCLIFE HINDALCO
    HINDUNILVR ICICIBANK ITC INFY INDIGO JSWSTEEL JIOFIN KOTAKBANK LT M&M MARUTI MAXHEALTH NTPC
    NESTLEIND ONGC POWERGRID RELIANCE SBILIFE SHRIRAMFIN SBIN SUNPHARMA TCS TATACONSUM TMPV
    TATASTEEL TECHM TITAN TRENT ULTRACEMCO
""".split()
PERIODS = (None, 5)   # all available (~9 years after warm-up), and the last 5 years
PAUSE = 0.5           # between Yahoo requests

SCHEMA = """
CREATE TABLE IF NOT EXISTS backtest_universe (
    universe     text NOT NULL,
    years        int  NOT NULL,          -- 0 = all available
    data         jsonb NOT NULL,
    computed_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (universe, years)
);
"""


def constituents() -> list[str]:
    """Today's Nifty 50 symbols from NSE's published list."""
    for url in CONSTITUENTS:
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
            r.raise_for_status()
            rows = list(csv.DictReader(io.StringIO(r.text)))
            symbols = [row["Symbol"].strip() for row in rows if row.get("Symbol")]
            if len(symbols) >= 45:
                return symbols
        except Exception as e:
            print(f"[universe] {url}: {e}", file=sys.stderr)
    print("[universe] using the built-in Nifty 50 list (NSE unreachable)", file=sys.stderr)
    return list(FALLBACK_NIFTY50)


def summarise(per_stock: dict[str, dict]) -> dict:
    """Per rule: on how many stocks it beat buy-and-hold, and the median gaps (rule minus buy-and-hold)."""
    rules = {}
    for key, info in backtest.STRATEGIES.items():
        rows = [{"symbol": sym, "cagr_pct": r[key]["cagr_pct"], "hold_cagr_pct": r["buy_hold"]["cagr_pct"],
                 "max_drawdown_pct": r[key]["max_drawdown_pct"], "hold_max_drawdown_pct": r["buy_hold"]["max_drawdown_pct"],
                 "trades": r[key]["trades"], "time_invested_pct": r[key]["time_invested_pct"]}
                for sym, r in per_stock.items()]
        gaps = [x["cagr_pct"] - x["hold_cagr_pct"] for x in rows]
        dd_gaps = [x["max_drawdown_pct"] - x["hold_max_drawdown_pct"] for x in rows]   # > 0: a smaller worst fall
        rules[key] = {**info, "stocks": len(rows),
                      "beat_hold": sum(g > 0 for g in gaps),
                      "smaller_drawdown": sum(d > 0 for d in dd_gaps),
                      "median_cagr_gap_pts": statistics.median(gaps),
                      "median_drawdown_gap_pts": statistics.median(dd_gaps),
                      "median_trades": statistics.median(x["trades"] for x in rows),
                      "per_stock": sorted(rows, key=lambda x: x["symbol"])}
    holds = [r["buy_hold"]["cagr_pct"] for r in per_stock.values()]
    return {"rules": rules, "stocks": sorted(per_stock), "buy_hold_median_cagr_pct": statistics.median(holds),
            "rules_tested": len(backtest.STRATEGIES)}


def run(limit: int | None = None) -> dict:
    db.execute(SCHEMA)
    symbols = constituents()[:limit]
    results = {p: {} for p in PERIODS}
    skipped = []
    tz = candles.SESSIONS["IN"][0]
    for i, sym in enumerate(symbols):
        try:
            bars = candles._fetch(f"{sym}.NS", "10y", "1d", False)
            dates = [datetime.fromtimestamp(b[6] / 1000, tz).date() for b in bars]
            o, h, l, c, v = ([b[k] for b in bars] for k in (1, 2, 3, 4, 5))
            for years in PERIODS:
                results[years][sym] = backtest.run_all(dates, o, h, l, c, "IN", years, volumes=v, detail=False)["results"]
            print(f"[universe] {i + 1}/{len(symbols)} {sym}")
        except Exception as e:   # a recent listing without enough history, or a failed fetch
            skipped.append(sym)
            print(f"[universe] {sym} skipped: {e}", file=sys.stderr)
        time.sleep(PAUSE)
    for years in PERIODS:
        if results[years]:
            data = {**summarise(results[years]), "skipped": skipped, "universe": "Nifty 50 (current members)"}
            db.execute("""INSERT INTO backtest_universe (universe, years, data, computed_at) VALUES (%s, %s, %s, now())
                          ON CONFLICT (universe, years) DO UPDATE SET data = EXCLUDED.data, computed_at = now()""",
                       (UNIVERSE, years or 0, db.jsonb(data)))
    return {"tested": len(symbols) - len(skipped), "skipped": skipped}


def latest(years: int | None = None) -> dict | None:
    db.execute(SCHEMA)
    row = db.fetch_one("SELECT data, computed_at FROM backtest_universe WHERE universe = %s AND years = %s",
                       (UNIVERSE, years or 0))
    return {**row["data"], "computed_at": row["computed_at"].isoformat()} if row else None


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--limit", type=int, help="only the first N stocks (for a quick check)")
    print(run(ap.parse_args().limit))
