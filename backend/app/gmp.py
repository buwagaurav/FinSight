"""Grey Market Premium (GMP) records.

GMP is an unofficial, unregulated indication traded outside the exchange. FinSight therefore
stores it separately from every official dataset: each entry carries its source and the time it
was observed, and it is never folded into company scores.
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from app import db
from app.providers import investorgain

SYNC_EVERY = 30 * 60
_last_sync = 0.0
_sync_lock = threading.Lock()

DISCLAIMER = ("GMP is unofficial and unverified: a price quoted in an unregulated grey market, not exchange data. "
              "It changes quickly and often differs from the actual listing price.")


def history(symbol: str) -> list[dict]:
    rows = db.fetch_all("""SELECT gmp, source, source_url, observed_at FROM gmp_entries
                           WHERE symbol = %s ORDER BY observed_at""", (symbol.upper(),))
    return [{**r, "observed_at": r["observed_at"].isoformat()} for r in rows]


def add(symbol: str, gmp: float, source: str, source_url: str | None, observed_at: str | None) -> dict:
    when = datetime.fromisoformat(observed_at) if observed_at else datetime.now(timezone.utc)
    db.execute("""INSERT INTO gmp_entries (symbol, gmp, source, source_url, observed_at) VALUES (%s, %s, %s, %s, %s)
                  ON CONFLICT (symbol, source, observed_at) DO NOTHING""", (symbol.upper(), gmp, source, source_url, when))
    return {"gmp": gmp, "source": source, "source_url": source_url, "observed_at": when.isoformat(timespec="seconds")}


HISTORY_PAGES_PER_SYNC = 15   # detail pages fetched per sync, for IPOs with no stored readings yet


def sync(ipos: list[dict]) -> None:
    """Record InvestorGain's current GMP for every tracked IPO (one page for all of them), and the full reading
    history from each IPO's own page the first time it's seen. Runs at most every 30 minutes; readings already
    stored are skipped, so the history only grows."""
    global _last_sync
    if time.time() - _last_sync < SYNC_EVERY or not _sync_lock.acquire(blocking=False):
        return
    try:
        tracked = [r for r in ipos if r.get("investorgain")]
        readings = [(r["symbol"], r["investorgain"]["gmp"], "InvestorGain", r["investorgain"]["url"],
                     datetime.fromisoformat(r["investorgain"]["updated"]))
                    for r in tracked if r["investorgain"]["gmp"] is not None and r["investorgain"]["updated"]]
        have = {row["symbol"] for row in db.fetch_all("SELECT DISTINCT symbol FROM gmp_entries WHERE symbol = ANY(%s)",
                                                      ([r["symbol"] for r in tracked],))}
        new = [r for r in tracked if r["symbol"] not in have][:HISTORY_PAGES_PER_SYNC]

        def past(r):
            try:
                return [(r["symbol"], p["gmp"], "InvestorGain", r["investorgain"]["url"], p["observed_at"])
                        for p in investorgain.history(r["investorgain"]["url"])]
            except Exception:
                return []

        with ThreadPoolExecutor(6) as pool:
            for rows in pool.map(past, new):
                readings += rows
        if readings:
            with db.conn() as c, c.cursor() as cur:   # one round trip for the lot
                cur.executemany("""INSERT INTO gmp_entries (symbol, gmp, source, source_url, observed_at)
                                   VALUES (%s, %s, %s, %s, %s) ON CONFLICT (symbol, source, observed_at) DO NOTHING""",
                                readings)
        _last_sync = time.time()
    except Exception as e:  # GMP is optional; never break the IPO page over it
        print(f"[gmp] InvestorGain sync failed: {e}")
    finally:
        _sync_lock.release()


def _summary(entries: list[dict], price_high: float | None) -> dict:
    latest = entries[-1] if entries else None
    estimate = None
    if latest and price_high:
        estimate = {
            "estimated_listing_price": price_high + latest["gmp"],
            "estimated_premium_pct": latest["gmp"] / price_high * 100,
            "label": "Estimate from unofficial GMP. Not a forecast.",
        }
    return {"official": False, "disclaimer": DISCLAIMER, "latest": latest, "estimate": estimate, "history": entries}


def summary(symbol: str, price_high: float | None) -> dict:
    return _summary(history(symbol), price_high)


def summaries(ipos: list[dict]) -> dict[str, dict]:
    """GMP summary for every IPO in one query. An IPO's readings may be stored under its NSE symbol too (from
    before IPOs had a stable key), so both are read."""
    keys = {r["symbol"]: [r["symbol"]] + ([r["nse_symbol"]] if r.get("nse_symbol") else []) for r in ipos}
    rows = db.fetch_all("""SELECT symbol, gmp, source, source_url, observed_at FROM gmp_entries
                           WHERE symbol = ANY(%s) ORDER BY observed_at""",
                        ([k for ks in keys.values() for k in ks],))
    by_symbol: dict[str, list[dict]] = {}
    for r in rows:
        by_symbol.setdefault(r["symbol"], []).append(
            {"gmp": r["gmp"], "source": r["source"], "source_url": r["source_url"], "observed_at": r["observed_at"].isoformat()})
    out = {}
    for ipo in ipos:
        entries = sorted((e for k in keys[ipo["symbol"]] for e in by_symbol.get(k, [])), key=lambda e: e["observed_at"])
        out[ipo["symbol"]] = _summary(entries, ipo["price_high"])
    return out
