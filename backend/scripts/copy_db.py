"""One-time copy of the local FinSight database to another PostgreSQL (e.g. Neon), so the cloud starts with
every company already loaded instead of re-downloading them all from Yahoo.

    cd backend
    ../.venv/bin/python -m scripts.copy_db "postgresql://user:pass@host/db?sslmode=require"

Replaces the target's FinSight tables. Run it with DATABASE_URL unset, so the source is the local database.
"""
import sys

import psycopg

from app import db

TABLES = ["companies", "load_status", "profiles", "statements", "metrics", "gmp_entries", "filing_summaries", "reports"]


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    target_url = sys.argv[1]
    with db.conn() as src, psycopg.connect(target_url) as dst:
        dst.execute(db.SCHEMA)
        dst.execute(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE")
        for table in TABLES:
            with src.cursor().copy(f"COPY {table} TO STDOUT") as out, dst.cursor().copy(f"COPY {table} FROM STDIN") as inp:
                for chunk in out:
                    inp.write(chunk)
            print(f"{table:18} {dst.execute(f'SELECT count(*) FROM {table}').fetchone()[0]:>6} rows")
        dst.execute("SELECT setval(pg_get_serial_sequence('gmp_entries', 'id'), coalesce(max(id), 1)) FROM gmp_entries")
    print("Done.")


if __name__ == "__main__":
    main()
