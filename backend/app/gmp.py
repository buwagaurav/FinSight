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


def sync(ipos: list[dict]) -> None:
    """Store InvestorGain's GMP readings for the current NSE IPOs. Runs at most every 30 minutes;
    readings already stored are skipped, so the history only grows."""
    global _last_sync
    if time.time() - _last_sync < SYNC_EVERY or not _sync_lock.acquire(blocking=False):
        return
    try:
        listed = investorgain.live_list()
        pairs = [(i["symbol"], m) for i in ipos if (m := investorgain.match(i["name"], listed))]

        def store(pair):
            symbol, m = pair
            for p in investorgain.history(m["url"]):
                add(symbol, p["gmp"], "InvestorGain", m["url"], p["observed_at"].isoformat())

        with ThreadPoolExecutor(6) as pool:
            list(pool.map(store, pairs))
        _last_sync = time.time()
    except Exception as e:  # GMP is optional; never break the IPO page over it
        print(f"[gmp] InvestorGain sync failed: {e}")
    finally:
        _sync_lock.release()


def summary(symbol: str, price_high: float | None) -> dict:
    entries = history(symbol)
    latest = entries[-1] if entries else None
    estimate = None
    if latest and price_high:
        estimate = {
            "estimated_listing_price": price_high + latest["gmp"],
            "estimated_premium_pct": latest["gmp"] / price_high * 100,
            "label": "Estimate from unofficial GMP. Not a forecast.",
        }
    return {"official": False, "disclaimer": DISCLAIMER, "latest": latest, "estimate": estimate, "history": entries}
