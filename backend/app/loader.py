"""Loads every NSE-listed company into PostgreSQL, resumably.

  - The company list comes from NSE's official EQUITY_L.csv.
  - `load_status` records where each company is, so every run continues from where the last one stopped.
  - Profiles (price, ratios) are refreshed daily; annual statements weekly (they only change after results).
  - Yahoo rate limits pause the run instead of marking companies as failed. Companies Yahoo doesn't know
    are retried monthly; other errors back off exponentially.

Run it by hand:   cd backend && ../.venv/bin/python -m app.loader            (until done or 60 minutes)
                  ../.venv/bin/python -m app.loader --status
The API also runs it in the background (disable with FINSIGHT_BACKGROUND_LOADER=0).
"""
import argparse
import csv
import io
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime

import requests
from yfinance.exceptions import YFRateLimitError

from app import db, screener
from app.analytics import fundamentals
from app.providers import nse, yahoo

EQUITY_LIST = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
SERIES = ("EQ", "BE")          # regular and trade-for-trade equity segments
PROFILE_MAX_AGE = "1 day"
STATEMENTS_MAX_AGE = "7 days"
PAUSE_BETWEEN_CALLS = 1.0      # seconds per worker between companies, to stay polite to Yahoo


class RateLimited(Exception):
    pass


def sync_universe() -> int:
    """Upsert the official NSE company list. Returns the number of companies listed."""
    r = requests.get(EQUITY_LIST, headers={"User-Agent": nse.HEADERS["User-Agent"]}, timeout=30)
    r.raise_for_status()
    rows = [{k.strip(): v.strip() for k, v in row.items()} for row in csv.DictReader(io.StringIO(r.text))]
    rows = [x for x in rows if x["SERIES"] in SERIES]
    with db.conn() as c:
        with c.cursor() as cur:
            cur.executemany("""
                INSERT INTO companies (symbol, name, isin, series, listed_on) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (symbol) DO UPDATE SET name = EXCLUDED.name, isin = EXCLUDED.isin, series = EXCLUDED.series""",
                [(x["SYMBOL"], x["NAME OF COMPANY"], x["ISIN NUMBER"], x["SERIES"],
                  datetime.strptime(x["DATE OF LISTING"], "%d-%b-%Y").date()) for x in rows])
            cur.execute("INSERT INTO load_status (symbol) SELECT symbol FROM companies ON CONFLICT DO NOTHING")
    return len(rows)


def claim(limit: int) -> list[dict]:
    """Claim the next companies that need work (never-loaded first, then the stalest).

    Claiming pushes next_try_at forward, so a second loader running at the same time (the API's background
    thread and a manual run, say) skips them. If a loader dies mid-batch its claims simply expire."""
    return db.fetch_all(f"""
        UPDATE load_status s SET next_try_at = now() + interval '20 minutes'
        WHERE s.symbol IN (
            SELECT symbol FROM load_status
            WHERE next_try_at <= now()
              AND (state IN ('pending', 'error')
                   OR (state = 'ok' AND (profile_at < now() - interval '{PROFILE_MAX_AGE}'
                                         OR statements_at < now() - interval '{STATEMENTS_MAX_AGE}')))
            ORDER BY (state = 'pending') DESC, profile_at NULLS FIRST
            LIMIT %s
            FOR UPDATE SKIP LOCKED)
        RETURNING s.symbol, s.state,
                  (s.statements_at IS NULL OR s.statements_at < now() - interval '{STATEMENTS_MAX_AGE}') AS need_statements""",
        (limit,))


def load_one(symbol: str, need_statements: bool) -> str:
    ysym = f"{symbol}.NS"
    try:
        profile = yahoo.profile(ysym)
        if need_statements:
            statements = yahoo.annual_statements(ysym)
        else:
            row = db.fetch_one("SELECT data FROM statements WHERE symbol = %s", (symbol,))
            statements = row["data"] if row else yahoo.annual_statements(ysym)
            need_statements = row is None
        metrics = screener.metrics_row(profile, fundamentals.build_table(statements))
    except YFRateLimitError as e:
        raise RateLimited() from e
    except LookupError:
        db.execute("""UPDATE load_status SET state = 'not_found', attempts = attempts + 1, last_error = 'Not on Yahoo Finance',
                      next_try_at = now() + interval '30 days' WHERE symbol = %s""", (symbol,))
        return "not_found"
    except Exception as e:
        if "Too Many Requests" in str(e) or "429" in str(e):
            raise RateLimited() from e
        db.execute("""UPDATE load_status SET state = 'error', attempts = attempts + 1, last_error = %s,
                      next_try_at = now() + least(interval '48 hours', interval '1 hour' * power(2, attempts))
                      WHERE symbol = %s""", (str(e)[:500], symbol))
        return "error"

    with db.conn() as c:
        c.execute("""INSERT INTO profiles (symbol, data, updated_at) VALUES (%s, %s, now())
                     ON CONFLICT (symbol) DO UPDATE SET data = EXCLUDED.data, updated_at = now()""",
                  (symbol, db.jsonb(profile)))
        if need_statements:
            c.execute("""INSERT INTO statements (symbol, data, converted_from, updated_at) VALUES (%s, %s, %s, now())
                         ON CONFLICT (symbol) DO UPDATE SET data = EXCLUDED.data, converted_from = EXCLUDED.converted_from,
                         updated_at = now()""", (symbol, db.jsonb(statements), statements.get("converted_from")))
        cols = list(metrics)
        c.execute(f"""INSERT INTO metrics (symbol, {', '.join(cols)}, updated_at)
                      VALUES (%s, {', '.join(['%s'] * len(cols))}, now())
                      ON CONFLICT (symbol) DO UPDATE SET {', '.join(f'{k} = EXCLUDED.{k}' for k in cols)}, updated_at = now()""",
                  [symbol, *[float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v for v in metrics.values()]])
        c.execute(f"""UPDATE load_status SET state = 'ok', attempts = 0, last_error = NULL, profile_at = now(),
                      statements_at = CASE WHEN %s THEN now() ELSE statements_at END, next_try_at = now()
                      WHERE symbol = %s""", (need_statements, symbol))
    return "ok"


def status() -> dict:
    counts = {r["state"]: r["n"] for r in db.fetch_all("SELECT state, count(*) AS n FROM load_status GROUP BY state")}
    return {"listed": sum(counts.values()), "by_state": counts, **screener.coverage(),
            "due_now": db.fetch_one("SELECT count(*) AS n FROM load_status WHERE next_try_at <= now() AND state IN ('pending','error')")["n"]}


def run(max_minutes: float = 60, workers: int = 4, limit: int | None = None, log=print) -> dict:
    """Work through due companies until none are left, the time is up, or Yahoo rate-limits us."""
    deadline = time.time() + max_minutes * 60
    done = {"ok": 0, "not_found": 0, "error": 0}
    rate_limited = False
    started = time.time()

    def task(row):
        result = load_one(row["symbol"], row["need_statements"])
        time.sleep(PAUSE_BETWEEN_CALLS)
        return result

    with ThreadPoolExecutor(workers) as pool:
        while time.time() < deadline and not rate_limited:
            batch = claim(min(100, limit - sum(done.values())) if limit else 100)
            if not batch:
                break
            futures = {pool.submit(task, row) for row in batch}
            while futures:
                finished, futures = wait(futures, return_when=FIRST_COMPLETED)
                for f in finished:
                    try:
                        done[f.result()] += 1
                    except RateLimited:
                        rate_limited = True
                if rate_limited or time.time() > deadline:
                    for f in futures:
                        f.cancel()
                    # release claims on companies we didn't get to, so the next run takes them immediately
                    db.execute("UPDATE load_status SET next_try_at = now() WHERE state = 'pending' AND profile_at IS NULL "
                               "AND next_try_at > now() AND symbol = ANY(%s)",
                               ([r["symbol"] for r in batch],))
                    break
            n = sum(done.values())
            log(f"[loader] {n} processed in {time.time() - started:.0f}s: {done}  "
                f"(stored {screener.coverage()['loaded']:,})")
            if limit and n >= limit:
                break
    return {**done, "rate_limited": rate_limited, "seconds": round(time.time() - started)}


def run_forever(stop: threading.Event, log=print):
    """Background mode for the API: sync the list daily, keep loading, back off when rate-limited."""
    last_sync = 0.0
    while not stop.is_set():
        try:
            if time.time() - last_sync > 24 * 3600:
                log(f"[loader] NSE list synced: {sync_universe():,} companies")
                last_sync = time.time()
            result = run(max_minutes=20, workers=2, log=log)
            pause = 15 * 60 if result["rate_limited"] else (60 if sum(result[k] for k in ("ok", "not_found", "error")) else 30 * 60)
        except Exception as e:  # network down etc.; try again later rather than killing the thread
            log(f"[loader] error: {e}")
            pause = 10 * 60
        stop.wait(pause)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--minutes", type=float, default=60)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--limit", type=int, help="stop after this many companies")
    ap.add_argument("--status", action="store_true", help="show progress and exit")
    args = ap.parse_args()
    if not args.status:
        print(f"NSE list synced: {sync_universe():,} companies")
        print(run(args.minutes, args.workers, args.limit))
    print(status())


if __name__ == "__main__":
    main()
