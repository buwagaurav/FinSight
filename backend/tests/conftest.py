"""Shared test setup.

Tests never touch the real database, market-data sources or AI providers: they run against a throwaway embedded
PostgreSQL, the background loader is off, and AI keys are blanked (set-but-empty keys also stop main.py's
load_dotenv from filling them in from backend/.env).
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.pop("DATABASE_URL", None)
os.environ["FINSIGHT_BACKGROUND_LOADER"] = "0"
for key in ("FINSIGHT_API_JWT_SECRET", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "MOONSHOT_API_KEY", "OPENAI_API_KEY"):
    os.environ[key] = ""

TABLES = ("watchlist, ai_usage, users, metrics, profiles, statements, load_status, companies, "
          "us_metrics, us_prices, us_statements, us_companies, gmp_entries")


@pytest.fixture(scope="session")
def database():
    """A private PostgreSQL for the whole test run, deleted afterwards."""
    import pgserver
    from app import db

    # short path: PostgreSQL's socket path must stay under macOS's 104-character limit
    data_dir = tempfile.mkdtemp(prefix="fs-test-", dir="/tmp")
    server = pgserver.get_server(data_dir, cleanup_mode="stop")
    os.environ["DATABASE_URL"] = server.get_uri()
    db._pool = None
    db.pool()
    yield db
    db._pool.close()
    db._pool = None
    os.environ.pop("DATABASE_URL", None)
    server.cleanup()
    shutil.rmtree(data_dir, ignore_errors=True)


@pytest.fixture
def clean_db(database):
    from app import auth, watchlist

    auth._ensure_schema()
    watchlist._ensure_schema()
    database.execute(f"TRUNCATE {TABLES} CASCADE")
    return database


def add_company(db, symbol: str, name: str, sector: str = "Technology", **metrics):
    """Insert a listed company with screener metrics and a stored quote."""
    db.execute("INSERT INTO companies (symbol, name) VALUES (%s, %s)", (symbol, name))
    row = {"price": 100.0, "market_cap_cr": 1000.0, "pe": 20.0, "pb": 3.0, "roe_pct": 15.0, **metrics}
    db.execute("""INSERT INTO metrics (symbol, yahoo_symbol, name, sector, price, market_cap_cr, pe, pb, roe_pct,
                                       roce_pct, debt_to_equity, profit_cagr_pct)
                  VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
               (symbol, f"{symbol}.NS", name, sector, row["price"], row["market_cap_cr"], row["pe"], row["pb"],
                row["roe_pct"], row.get("roce_pct"), row.get("debt_to_equity"), row.get("profit_cagr_pct")))
    db.execute("INSERT INTO profiles (symbol, data) VALUES (%s, %s)",
               (symbol, db.jsonb({"change_pct": 1.5, "week52_low": 80.0, "week52_high": 120.0})))


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    """Each test starts with empty rate-limit counters (they're per process, and the suite makes many requests)."""
    from app import security
    security.limiter.reset()
    yield
