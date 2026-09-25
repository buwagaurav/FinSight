"""Screener over every NSE company the loader has stored in PostgreSQL.

Metrics are computed with the same fundamentals engine as the company page (metrics_row) and kept in the
`metrics` table by app.loader, so a screen is a single SQL query however many companies are loaded.
"""
from app import db
from app.analytics import fundamentals

FIELDS = {
    "market_cap_cr": "Market cap (₹ Cr)",
    "pe": "P/E",
    "pb": "P/B",
    "roe_pct": "ROE %",
    "roce_pct": "ROCE %",
    "debt_to_equity": "Debt / Equity",
    "revenue_cagr_pct": "Revenue CAGR %",
    "profit_cagr_pct": "Profit CAGR %",
    "operating_margin_pct": "Operating margin %",
    "dividend_yield_pct": "Dividend yield %",
    "promoter_holding_pct": "Promoter / insider holding %",
}
SECTORS = ["Basic Materials", "Communication Services", "Consumer Cyclical", "Consumer Defensive", "Energy",
           "Financial Services", "Healthcare", "Industrials", "Real Estate", "Technology", "Utilities"]
OPS = {">": ">", ">=": ">=", "<": "<", "<=": "<="}
MAX_ROWS = 200


def metrics_row(profile: dict, table: list[dict]) -> dict:
    """Screener metrics for one company, from its profile and annual-statement table."""
    growth = fundamentals.growth_summary(table)
    last = table[-1] if table else {}
    financial = profile["sector"] == "Financial Services"
    return {
        "yahoo_symbol": profile["symbol"],
        "name": profile["name"],
        "sector": profile["sector"],
        "price": profile["price"],
        "market_cap_cr": profile["market_cap_cr"],
        "pe": profile["pe"],
        "pb": profile["pb"],
        "roe_pct": last.get("roe_pct"),
        "roce_pct": None if financial else last.get("roce_pct"),
        "debt_to_equity": None if financial else last.get("debt_to_equity"),
        "revenue_cagr_pct": growth.get("revenue_cagr_pct"),
        "profit_cagr_pct": growth.get("profit_cagr_pct"),
        "operating_margin_pct": last.get("operating_margin_pct"),
        "dividend_yield_pct": profile["dividend_yield_pct"],
        "promoter_holding_pct": profile["promoter_holding_pct"],
    }


def coverage() -> dict:
    """How much of the market is loaded. `pending` is work still to do; `unavailable` are companies the data
    source has nothing for (very new listings, rights-entitlement lines), which never count as "still loading"."""
    row = db.fetch_one("""
        SELECT (SELECT count(*) FROM companies) AS listed,
               (SELECT count(*) FROM metrics) AS loaded,
               (SELECT count(*) FROM load_status WHERE state IN ('pending', 'error')) AS pending,
               (SELECT max(updated_at) FROM metrics) AS updated_at""")
    unavailable = db.fetch_all("""SELECT c.symbol, c.name FROM load_status s JOIN companies c USING (symbol)
                                  WHERE s.state = 'not_found' ORDER BY c.symbol""")
    return {"listed": row["listed"], "loaded": row["loaded"], "pending": row["pending"],
            "unavailable": [f"{u['name']} ({u['symbol']})" for u in unavailable],
            "updated_at": row["updated_at"].timestamp() if row["updated_at"] else None}


def lookup(symbols: list[str]) -> dict[str, dict]:
    """Stored metrics for the given NSE symbols (with or without .NS)."""
    bases = [s.split(".")[0].upper() for s in symbols]
    rows = db.fetch_all("SELECT * FROM metrics WHERE symbol = ANY(%s)", (bases,))
    return {r["symbol"]: _public(r) for r in rows}


def _public(r: dict) -> dict:
    out = {k: r[k] for k in ("name", "sector", "price", *FIELDS)}
    return {"symbol": r["yahoo_symbol"], **out}


def run(filters: list[dict], sort: str | None = None, descending: bool = True, sectors: list[str] | None = None) -> dict:
    where, params = [], []
    if sectors:
        where.append("sector = ANY(%s)")
        params.append(sectors)
    for flt in filters:
        if flt["field"] not in FIELDS or flt["op"] not in OPS:
            raise ValueError(f"Unsupported filter {flt}")
        where.append(f'{flt["field"]} IS NOT NULL AND {flt["field"]} {OPS[flt["op"]]} %s')  # names are whitelisted
        params.append(flt["value"])
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    order = sort if sort in FIELDS else "market_cap_cr"
    direction = "DESC" if descending else "ASC"
    with db.conn() as c:
        count = c.execute(f"SELECT count(*) AS n FROM metrics {clause}", params).fetchone()["n"]
        rows = c.execute(f"SELECT * FROM metrics {clause} ORDER BY {order} {direction} NULLS LAST LIMIT {MAX_ROWS}",
                         params).fetchall()
    cov = coverage()
    return {
        "universe": f"{cov['loaded']:,} of {cov['listed']:,} NSE stocks loaded" if cov["listed"] else "No stocks loaded yet",
        "coverage": cov,
        "built_at": cov["updated_at"],
        "count": count,
        "shown": len(rows),
        "query": " AND ".join(([f"Sector in ({', '.join(sectors)})"] if sectors else [])
                              + [f"{FIELDS[f['field']]} {f['op']} {f['value']}" for f in filters]) or "All stocks",
        "rows": [_public(r) for r in rows],
    }
