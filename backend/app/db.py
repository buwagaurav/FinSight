"""PostgreSQL storage for FinSight.

By default FinSight runs its own PostgreSQL 16 from the project's Python environment (pgserver), with data in
backend/data/postgres/. Set DATABASE_URL to use any other PostgreSQL instead (Postgres.app, Neon, Supabase...);
nothing else changes.
"""
import json
import os
import threading
from contextlib import contextmanager
from pathlib import Path

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "postgres"

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    symbol      text PRIMARY KEY,          -- NSE symbol without suffix, e.g. TCS
    name        text NOT NULL,
    isin        text,
    series      text,
    listed_on   date,
    added_at    timestamptz NOT NULL DEFAULT now()
);

-- One row per company: where the loader is with it. Lets every run resume instead of starting over.
CREATE TABLE IF NOT EXISTS load_status (
    symbol         text PRIMARY KEY REFERENCES companies(symbol) ON DELETE CASCADE,
    state          text NOT NULL DEFAULT 'pending',   -- pending | ok | not_found | error
    attempts       int  NOT NULL DEFAULT 0,
    last_error     text,
    profile_at     timestamptz,
    statements_at  timestamptz,
    next_try_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS profiles (
    symbol      text PRIMARY KEY REFERENCES companies(symbol) ON DELETE CASCADE,
    data        jsonb NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS statements (
    symbol          text PRIMARY KEY REFERENCES companies(symbol) ON DELETE CASCADE,
    data            jsonb NOT NULL,
    converted_from  text,
    updated_at      timestamptz NOT NULL DEFAULT now()
);

-- Screener-ready numbers, one row per company, recomputed whenever profile or statements change.
CREATE TABLE IF NOT EXISTS metrics (
    symbol                text PRIMARY KEY REFERENCES companies(symbol) ON DELETE CASCADE,
    yahoo_symbol          text NOT NULL,
    name                  text NOT NULL,
    sector                text,
    price                 double precision,
    market_cap_cr         double precision,
    pe                    double precision,
    pb                    double precision,
    roe_pct               double precision,
    roce_pct              double precision,
    debt_to_equity        double precision,
    revenue_cagr_pct      double precision,
    profit_cagr_pct       double precision,
    operating_margin_pct  double precision,
    dividend_yield_pct    double precision,
    promoter_holding_pct  double precision,
    updated_at            timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS metrics_sector_idx ON metrics (sector);
CREATE INDEX IF NOT EXISTS metrics_mcap_idx ON metrics (market_cap_cr DESC NULLS LAST);

CREATE TABLE IF NOT EXISTS gmp_entries (
    id           bigserial PRIMARY KEY,
    symbol       text NOT NULL,
    gmp          double precision NOT NULL,
    source       text NOT NULL,
    source_url   text,
    observed_at  timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS gmp_symbol_idx ON gmp_entries (symbol, observed_at);
CREATE UNIQUE INDEX IF NOT EXISTS gmp_reading_uniq ON gmp_entries (symbol, source, observed_at);

CREATE TABLE IF NOT EXISTS filing_summaries (
    announcement_id  text PRIMARY KEY,
    symbol           text NOT NULL,
    data             jsonb NOT NULL,
    created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS reports (
    symbol      text PRIMARY KEY,             -- Yahoo symbol, e.g. TCS.NS
    data        jsonb NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);
"""

_pool: ConnectionPool | None = None
_server = None
_lock = threading.Lock()


def _uri() -> str:
    global _server
    if url := os.environ.get("DATABASE_URL"):
        return url
    import pgserver  # embedded PostgreSQL, only needed when no external database is configured
    DATA_DIR.parent.mkdir(parents=True, exist_ok=True)
    _server = pgserver.get_server(DATA_DIR, cleanup_mode="stop")
    return _server.get_uri()


def pool() -> ConnectionPool:
    global _pool
    with _lock:
        if _pool is None:
            p = ConnectionPool(_uri(), min_size=1, max_size=10, kwargs={"row_factory": dict_row}, open=True)
            with p.connection() as conn:
                conn.execute(SCHEMA)
            _pool = p
    return _pool


@contextmanager
def conn():
    with pool().connection() as c:
        yield c


def fetch_all(sql: str, params=None) -> list[dict]:
    with conn() as c:
        return c.execute(sql, params).fetchall()


def fetch_one(sql: str, params=None) -> dict | None:
    with conn() as c:
        return c.execute(sql, params).fetchone()


def execute(sql: str, params=None) -> None:
    with conn() as c:
        c.execute(sql, params)


def jsonb(value) -> Jsonb:
    """Store Python data as JSONB. Round-trips through json so numpy floats and dates serialise."""
    return Jsonb(json.loads(json.dumps(value, default=str)))
