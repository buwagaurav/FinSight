"""The US screener's data: every exchange-listed US operating company, refreshed in bulk.

    python -m app.us_market                 # what's due: statements weekly, prices every run
    python -m app.us_market --statements    # force the statements refresh (SEC bulk file, ~1.4 GB)
    python -m app.us_market --statements --source api --limit 50   # small sample from the per-company API
    python -m app.us_market --prices        # prices and screener metrics only

Statements come from the SEC's nightly companyfacts.zip, one download instead of ~5,000 requests. Sectors come
from each company's SEC industry code, fetched once per company. Prices come from Yahoo in batches of 250 tickers.
Market cap, P/E, P/B and dividend yield are then computed from those prices and SEC's share counts and earnings, so
the screener needs no per-company Yahoo calls. Runs in GitHub Actions (see .github/workflows/refresh-data.yml).
"""
import argparse
import json
import math
import tempfile
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from app import db, screener
from app.analytics import fundamentals
from app.providers import sec

BULK_FACTS = "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip"
BULK_SUBMISSIONS = "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip"
BULK_SECTORS_ABOVE = 300      # more companies than this without a sector: one bulk download beats per-company calls
SECTOR_MINUTES = 20           # per-company lookups stop after this long and resume on the next run
STATEMENTS_MAX_AGE_DAYS = 7
STATEMENTS_MINUTES = 45       # the statements step stops after this long so prices and metrics still get written
PRICE_BATCH = 250

SCHEMA = """
CREATE TABLE IF NOT EXISTS us_companies (
    symbol          text PRIMARY KEY,           -- AAPL.US
    cik             int  NOT NULL,
    name            text NOT NULL,
    exchange        text,
    sic             int,
    sector          text,
    industry        text,
    entity_type     text,                       -- SEC: "operating" for businesses
    shares          double precision,           -- latest cover-page share count (all classes)
    ttm_net_income  double precision,           -- $, last twelve months
    ttm_through     date,
    equity_latest   double precision,           -- $, most recent balance sheet (latest 10-Q/10-K)
    added_at        timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS us_statements (
    symbol      text PRIMARY KEY REFERENCES us_companies(symbol) ON DELETE CASCADE,
    data        jsonb NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS us_prices (
    symbol          text PRIMARY KEY REFERENCES us_companies(symbol) ON DELETE CASCADE,
    price           double precision NOT NULL,
    previous_close  double precision,
    price_date      date NOT NULL,
    updated_at      timestamptz NOT NULL DEFAULT now()
);
-- Same columns as the NSE `metrics` table, so one screener query serves both markets. Amounts in $ millions.
CREATE TABLE IF NOT EXISTS us_metrics (
    symbol                text PRIMARY KEY REFERENCES us_companies(symbol) ON DELETE CASCADE,
    yahoo_symbol          text NOT NULL,        -- FinSight symbol (AAPL.US), named to match `metrics`
    name                  text NOT NULL,
    sector                text,
    price                 double precision,
    market_cap_cr         double precision,     -- $ millions for this table
    pe                    double precision,
    pb                    double precision,
    roe_pct               double precision,
    roce_pct              double precision,
    debt_to_equity        double precision,
    revenue_cagr_pct      double precision,
    profit_cagr_pct       double precision,
    operating_margin_pct  double precision,
    dividend_yield_pct    double precision,
    promoter_holding_pct  double precision,     -- not available for US companies; always NULL
    updated_at            timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE us_companies ADD COLUMN IF NOT EXISTS equity_latest double precision;
ALTER TABLE us_companies ADD COLUMN IF NOT EXISTS statements_checked_at timestamptz;
CREATE INDEX IF NOT EXISTS us_metrics_sector_idx ON us_metrics (sector);
CREATE INDEX IF NOT EXISTS us_metrics_mcap_idx ON us_metrics (market_cap_cr DESC NULLS LAST);
"""
_schema_ready = False


def ensure_schema():
    global _schema_ready
    if not _schema_ready:
        db.execute(SCHEMA)
        _schema_ready = True


# ---------------------------------------------------------------- universe and sectors

def sync_universe(log=print) -> int:
    """Add newly listed companies (one row per company: the first ticker SEC lists for it, usually the main
    share class) and drop ones that are no longer exchange-listed."""
    ensure_schema()
    seen: set[int] = set()
    rows = []
    for ticker, r in sec.tickers().items():
        if r["cik"] in seen:
            continue
        seen.add(r["cik"])
        rows.append((ticker + sec.SUFFIX, r["cik"], sec._title(r["name"]), r["exchange"]))
    with db.conn() as c:
        c.execute("CREATE TEMP TABLE listed (symbol text, cik int, name text, exchange text) ON COMMIT DROP")
        with c.cursor().copy("COPY listed FROM STDIN") as copy:
            for row in rows:
                copy.write_row(row)
        added = c.execute("""INSERT INTO us_companies (symbol, cik, name, exchange)
                             SELECT symbol, cik, name, exchange FROM listed
                             ON CONFLICT (symbol) DO UPDATE SET name = EXCLUDED.name, exchange = EXCLUDED.exchange
                             RETURNING (xmax = 0) AS inserted""").fetchall()
        gone = c.execute("DELETE FROM us_companies WHERE symbol NOT IN (SELECT symbol FROM listed)").rowcount
    log(f"US universe: {len(rows):,} listed companies ({sum(r['inserted'] for r in added):,} new, {gone:,} delisted)")
    return len(rows)


def _download(url: str, path: Path, log=print) -> None:
    started = time.time()
    with sec._get(url, stream=True) as r, open(path, "wb") as f:
        for chunk in r.iter_content(chunk_size=1 << 20):
            f.write(chunk)
    log(f"Downloaded {url.rsplit('/', 1)[1]} ({path.stat().st_size / 1e9:.2f} GB) in {time.time() - started:.0f}s")


class _Batch:
    """Collects rows and writes them `size` at a time in one transaction. The database (Neon) is a network hop
    away from the job, so one statement per row would spend the whole run waiting on round trips."""

    def __init__(self, sql: str, size: int = 250):
        self.sql, self.size, self.rows, self.written = sql, size, [], 0

    def add(self, row: tuple) -> None:
        self.rows.append(row)
        if len(self.rows) >= self.size:
            self.flush()

    def flush(self) -> None:
        if self.rows:
            with db.conn() as c, c.cursor() as cur:
                cur.executemany(self.sql, self.rows)   # pipelined by psycopg: one round trip per batch, not per row
            self.written += len(self.rows)
            self.rows = []


SECTOR_SQL = "UPDATE us_companies SET sic = %s, sector = %s, industry = %s, entity_type = %s WHERE symbol = %s"


def _sector_row(symbol: str, s: dict) -> tuple:
    sic = int(s.get("sic") or 0) or None
    return (sic, sec._sector(sic) if sic else None, (s.get("sicDescription") or "").title() or None,
            s.get("entityType") or "unknown", symbol)


def fill_sectors(log=print, limit: int | None = None, source: str | None = None) -> int:
    """SEC industry code and entity type for companies that don't have them yet, needed only once per company.
    Many missing (the first run): read them all from SEC's bulk submissions.zip. A few (new listings): one small
    request each, stopping after SECTOR_MINUTES so a slow day can't stall the refresh (the rest resume next run)."""
    ensure_schema()
    todo = db.fetch_all("SELECT symbol, cik FROM us_companies WHERE entity_type IS NULL ORDER BY symbol"
                        + (f" LIMIT {int(limit)}" if limit else ""))
    if not todo:
        return 0
    started = time.time()
    batch = _Batch(SECTOR_SQL)
    if (source or ("bulk" if len(todo) > BULK_SECTORS_ABOVE else "api")) == "bulk":
        by_cik = {r["cik"]: r["symbol"] for r in todo}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "submissions.zip"
            _download(BULK_SUBMISSIONS, path, log)
            with zipfile.ZipFile(path) as z:
                for name in z.namelist():        # CIK0000320193.json (+ -submissions-001.json overflow pages)
                    if not name.endswith(".json") or "-" in name:
                        continue
                    try:
                        cik = int(name[3:13])
                    except ValueError:
                        continue
                    if cik in by_cik:
                        batch.add(_sector_row(by_cik[cik], json.loads(z.read(name))))
        batch.flush()
        log(f"Sectors filled for {batch.written:,} of {len(todo):,} companies from the bulk file "
            f"in {time.time() - started:.0f}s")
        return batch.written

    deadline = time.monotonic() + SECTOR_MINUTES * 60

    def one(r):
        if time.monotonic() > deadline:
            return None
        try:
            return _sector_row(r["symbol"], sec.submissions.__wrapped__(r["cik"]))   # uncached: each is read once
        except Exception as e:
            log(f"  {r['symbol']}: submissions unavailable ({e})")
            return None

    # a few requests in flight at once; sec._get still spaces them to SEC's 10-a-second limit
    with ThreadPoolExecutor(max_workers=6) as pool:
        for i, row in enumerate(pool.map(one, todo)):
            if row:
                batch.add(row)
            if (i + 1) % 500 == 0:
                log(f"  sectors: {i + 1:,} of {len(todo):,}")
    batch.flush()
    log(f"Sectors filled for {batch.written:,} of {len(todo):,} companies"
        + (" (time budget reached; the rest continue next run)" if batch.written < len(todo) and time.monotonic() > deadline else ""))
    return batch.written


def _operating() -> list[dict]:
    """Companies worth screening: operating businesses, not shells, funds or trusts."""
    return db.fetch_all("""SELECT symbol, cik FROM us_companies
                           WHERE entity_type = 'operating' AND (sic IS NULL OR sic <> ALL(%s)) ORDER BY symbol""",
                        (list(sec.NON_OPERATING_SIC),))


# ---------------------------------------------------------------- statements

STATEMENTS_SQL = """INSERT INTO us_statements (symbol, data, updated_at) VALUES (%s, %s, now())
                    ON CONFLICT (symbol) DO UPDATE SET data = EXCLUDED.data, updated_at = now()"""
FACTS_SQL = """UPDATE us_companies SET shares = %s, ttm_net_income = %s, ttm_through = %s, equity_latest = %s,
                   statements_checked_at = now() WHERE symbol = %s"""
CHECKED_SQL = "UPDATE us_companies SET statements_checked_at = now() WHERE symbol = %s"


def _statements_due_list(limit: int | None = None) -> list[dict]:
    """Screenable companies whose statements weren't checked in the last STATEMENTS_MAX_AGE_DAYS, oldest first,
    so a run that stops early is continued by the next one."""
    rows = db.fetch_all(f"""SELECT symbol, cik FROM us_companies
                            WHERE entity_type = 'operating' AND (sic IS NULL OR sic <> ALL(%s))
                              AND (statements_checked_at IS NULL
                                   OR statements_checked_at < now() - interval '{STATEMENTS_MAX_AGE_DAYS} days')
                            ORDER BY statements_checked_at NULLS FIRST, symbol""", (list(sec.NON_OPERATING_SIC),))
    return rows[:limit] if limit else rows


def load_statements(source: str = "bulk", limit: int | None = None, log=print, force: bool = False,
                    minutes: float = STATEMENTS_MINUTES) -> int:
    """Refresh statements for companies that are due (all of them with force), from the SEC bulk file or (for
    small samples) the API. Stops after `minutes`; whatever is left continues on the next run."""
    ensure_schema()
    if force:
        db.execute("UPDATE us_companies SET statements_checked_at = NULL")
    companies = _statements_due_list(limit)
    if not companies:
        log("Statements are up to date")
        return 0
    by_cik = {c["cik"]: c["symbol"] for c in companies}
    deadline = time.monotonic() + minutes * 60
    statements, facts_rows, checked = _Batch(STATEMENTS_SQL, 100), _Batch(FACTS_SQL), _Batch(CHECKED_SQL)

    def store(symbol: str, cik: int, facts: dict) -> None:
        try:
            st = sec.statements_from_facts(facts, cik, symbol)
        except LookupError:
            checked.add((symbol,))   # no US-GAAP 10-K (foreign filer, or too new): look again next week
            return
        ttm = sec.ttm_net_income(facts)
        statements.add((symbol, db.jsonb(st)))
        facts_rows.add((sec.shares_from_facts(facts), ttm[0] if ttm else None, ttm[1] if ttm else None,
                        sec.latest_balance(facts).get("equity"), symbol))

    def flush():
        statements.flush()   # statements first: facts_rows marks the company as done
        facts_rows.flush()
        checked.flush()

    started = time.time()
    if source == "api":
        for c in companies:
            if time.monotonic() > deadline:
                break
            try:
                store(c["symbol"], c["cik"], sec.company_facts.__wrapped__(c["cik"]))
            except Exception as e:
                log(f"  {c['symbol']}: {e}")
    else:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "companyfacts.zip"
            _download(BULK_FACTS, path, log)
            with zipfile.ZipFile(path) as z:
                present = set()
                for name in z.namelist():           # CIK0000320193.json
                    if time.monotonic() > deadline:
                        break
                    try:
                        cik = int(name[3:13])
                    except ValueError:
                        continue
                    if cik in by_cik:
                        present.add(cik)
                        store(by_cik[cik], cik, json.loads(z.read(name)))
                        if (len(present)) % 500 == 0:
                            flush()
                            log(f"  statements: {len(present):,} of {len(companies):,}")
                else:
                    for cik in set(by_cik) - present:   # SEC has no XBRL facts for them at all
                        checked.add((by_cik[cik],))
    flush()
    stopped = time.monotonic() > deadline
    log(f"Statements stored for {statements.written:,} of {len(companies):,} due companies in {time.time() - started:.0f}s"
        + (" (time budget reached; the rest continue next run)" if stopped else ""))
    return statements.written


def statements_due() -> bool:
    ensure_schema()
    return bool(_statements_due_list(limit=1))


# ---------------------------------------------------------------- prices and screener metrics

def _closes(tickers: list[str]) -> dict[str, "pd.Series"]:
    """Recent daily closes per ticker from one batched Yahoo request (tickers Yahoo returns nothing for are left out)."""
    import pandas as pd
    import yfinance as yf

    df = yf.download(tickers, period="7d", interval="1d", group_by="ticker", auto_adjust=False, threads=True,
                     progress=False)
    out = {}
    for t in tickers:
        try:
            closes = (df[t]["Close"] if isinstance(df.columns, pd.MultiIndex) else df["Close"]).dropna()
        except KeyError:
            continue
        if not closes.empty and math.isfinite(closes.iloc[-1]):
            out[t] = closes
    return out


def refresh_prices(log=print) -> int:
    """Latest close for every company with statements, in batches through yfinance. Tickers a batch comes back
    empty for (Yahoo occasionally drops a few) are retried once together."""
    ensure_schema()
    symbols = [r["symbol"] for r in db.fetch_all("SELECT symbol FROM us_statements ORDER BY symbol")]
    by_ticker = {sec.ticker(s): s for s in symbols}
    tickers = list(by_ticker)
    found: dict = {}
    for i in range(0, len(tickers), PRICE_BATCH):
        try:
            found.update(_closes(tickers[i:i + PRICE_BATCH]))
        except Exception as e:
            log(f"  prices batch {i // PRICE_BATCH + 1} failed: {e}")
        log(f"  prices: {min(i + PRICE_BATCH, len(tickers)):,} of {len(tickers):,}")
    missing = [t for t in tickers if t not in found]
    if missing:
        time.sleep(5)
        for i in range(0, len(missing), PRICE_BATCH):
            try:
                found.update(_closes(missing[i:i + PRICE_BATCH]))
            except Exception as e:
                log(f"  retry batch failed: {e}")
    batch = _Batch("""INSERT INTO us_prices (symbol, price, previous_close, price_date, updated_at)
                      VALUES (%s, %s, %s, %s, now())
                      ON CONFLICT (symbol) DO UPDATE SET price = EXCLUDED.price,
                      previous_close = EXCLUDED.previous_close, price_date = EXCLUDED.price_date, updated_at = now()""", 500)
    for t, closes in found.items():
        prev = float(closes.iloc[-2]) if len(closes) > 1 else None
        batch.add((by_ticker[t], float(closes.iloc[-1]), prev, closes.index[-1].date()))
    batch.flush()
    log(f"Prices saved for {len(found):,} of {len(tickers):,} companies"
        + (f" (retried {len(missing):,})" if missing else ""))
    return len(found)


def metrics_for(company: dict, statements: dict, price: float | None) -> dict:
    """Screener row for one US company, in $ millions, from SEC statements and the latest price."""
    table = fundamentals.build_table(statements)
    last = table[-1] if table else {}
    shares = company.get("shares")
    mcap = price * shares / sec.MILLION if price and shares else None
    ttm = company.get("ttm_net_income")
    pe = price / (ttm / shares) if price and shares and ttm and ttm > 0 else None
    if pe is not None and pe < 1:   # share count and price on different share bases: leave these blank
        mcap = pe = None
    equity = company["equity_latest"] / sec.MILLION if company.get("equity_latest") else last.get("equity")
    dividends = -(last.get("dividends_paid") or 0)
    profile = {
        "symbol": company["symbol"], "name": company["name"], "sector": company.get("sector"), "price": price,
        "market_cap_cr": mcap, "pe": pe,
        "pb": mcap / equity if mcap and equity and equity > 0 else None,
        "dividend_yield_pct": dividends / mcap * 100 if mcap and dividends > 0 else (0.0 if mcap else None),
        "promoter_holding_pct": None,
    }
    return screener.metrics_row(profile, table)


def recompute_metrics(log=print) -> int:
    ensure_schema()
    rows = db.fetch_all("""SELECT c.symbol, c.name, c.sector, c.shares, c.ttm_net_income, c.equity_latest, s.data AS statements,
                                  p.price
                           FROM us_companies c JOIN us_statements s USING (symbol) LEFT JOIN us_prices p USING (symbol)""")
    cols = ["yahoo_symbol", "name", "sector", "price", "market_cap_cr", "pe", "pb", "roe_pct", "roce_pct",
            "debt_to_equity", "revenue_cagr_pct", "profit_cagr_pct", "operating_margin_pct", "dividend_yield_pct",
            "promoter_holding_pct"]
    batch = _Batch(f"""INSERT INTO us_metrics (symbol, {", ".join(cols)}, updated_at)
                       VALUES (%s, {", ".join(["%s"] * len(cols))}, now())
                       ON CONFLICT (symbol) DO UPDATE SET {", ".join(f"{k} = EXCLUDED.{k}" for k in cols)},
                       updated_at = now()""", 500)
    for r in rows:
        m = metrics_for(r, r["statements"], r["price"])
        batch.add((r["symbol"], *[m[k] for k in cols]))
    batch.flush()
    db.execute("DELETE FROM us_metrics WHERE symbol NOT IN (SELECT symbol FROM us_statements)")
    log(f"US screener metrics computed for {len(rows):,} companies")
    return len(rows)


def _timed(log, started: float):
    """Prefix each log line with minutes since the run started, so slow phases are easy to spot in CI logs."""
    return lambda msg: log(f"[{(time.time() - started) / 60:5.1f} min] {msg}")


def run(statements: bool | None = None, prices: bool = True, source: str = "bulk", limit: int | None = None,
        log=print) -> None:
    """One refresh: universe, sectors for new companies, statements when due (or forced), prices, metrics."""
    started = time.time()
    log = _timed(log, started)
    sync_universe(log)
    fill_sectors(log, limit=limit)
    if statements or (statements is None and statements_due()):
        load_statements(source, limit, log, force=bool(statements))
    if prices:
        refresh_prices(log)
    recompute_metrics(log)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--statements", action="store_true", help="refresh statements now, even if not due")
    ap.add_argument("--prices", action="store_true", help="prices and metrics only (skip statements)")
    ap.add_argument("--source", choices=["bulk", "api"], default="bulk")
    ap.add_argument("--limit", type=int, help="only this many companies (for testing)")
    a = ap.parse_args()
    started = time.time()
    run(statements=True if a.statements else (False if a.prices else None), source=a.source, limit=a.limit)
    print(f"Done in {(time.time() - started) / 60:.1f} min")


if __name__ == "__main__":
    main()
