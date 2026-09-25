"""Deterministic fundamentals engine: line items -> yearly table -> derived ratios and growth.

Every number FinSight shows (and every number an AI explanation cites) comes from here, never
from a language model doing arithmetic.
"""
from app.providers.yahoo import CRORE

# First key that exists wins. Banks and insurers use different line items than industrials.
LINE_ITEMS = {
    "income": {
        "revenue": ["Total Revenue", "Operating Revenue"],
        "ebitda": ["EBITDA", "Normalized EBITDA"],
        "operating_profit": ["Operating Income", "EBIT"],
        "ebit": ["EBIT", "Operating Income"],
        "interest_expense": ["Interest Expense", "Interest Expense Non Operating"],
        "net_profit": ["Net Income Common Stockholders", "Net Income", "Net Income From Continuing Operation Net Minority Interest"],
        "reported_eps": ["Diluted EPS", "Basic EPS"],
        "basic_shares": ["Basic Average Shares"],
    },
    "balance": {
        "equity": ["Stockholders Equity", "Common Stock Equity"],
        "total_debt": ["Total Debt"],
        "cash": ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"],
        "working_capital": ["Working Capital"],
        "total_assets": ["Total Assets"],
    },
    "cashflow": {
        "operating_cash_flow": ["Operating Cash Flow"],
        "capex": ["Capital Expenditure"],
        "free_cash_flow": ["Free Cash Flow"],
        "dividends_paid": ["Cash Dividends Paid"],
    },
}
RAW_UNITS = {"reported_eps", "basic_shares"}  # not converted to crore


def _pick(row: dict, keys: list[str]):
    for k in keys:
        if row.get(k) is not None:
            return row[k]
    return None


def _ratio(a, b, scale=1.0):
    if a is None or b in (None, 0):
        return None
    return a / b * scale


def cagr(first, last, years: int) -> float | None:
    """Compound annual growth in %. Undefined when either end is non-positive."""
    if first is None or last is None or years <= 0 or first <= 0 or last <= 0:
        return None
    return ((last / first) ** (1 / years) - 1) * 100


def build_table(statements: dict) -> list[dict]:
    years = sorted(set(statements["income"]) | set(statements["balance"]) | set(statements["cashflow"]))
    table = []
    for fy in years:
        row = {"year": fy}
        for stmt, items in LINE_ITEMS.items():
            src = statements[stmt].get(fy, {})
            row.setdefault("period_end", src.get("period_end"))
            for name, keys in items.items():
                v = _pick(src, keys)
                row[name] = v if v is None or name in RAW_UNITS else v / CRORE
        if row["revenue"] is None and row["net_profit"] is None:
            continue  # Yahoo sometimes returns an empty oldest column
        # Reported EPS is not always restated for later bonus issues/splits (e.g. HDFC Bank FY23),
        # while the average share count is. Deriving EPS keeps it comparable with adjusted prices.
        if row["net_profit"] is not None and row["basic_shares"]:
            row["eps"] = row["net_profit"] * CRORE / row.pop("basic_shares")
        else:
            row.pop("basic_shares")
            row["eps"] = row["reported_eps"]
        row.pop("reported_eps")
        table.append(row)

    for i, r in enumerate(table):
        prev = table[i - 1] if i else None
        avg_equity = (r["equity"] + prev["equity"]) / 2 if prev and prev["equity"] and r["equity"] else r["equity"]
        capital_employed = (r["equity"] or 0) + (r["total_debt"] or 0) if r["equity"] else None
        r["operating_margin_pct"] = _ratio(r["operating_profit"], r["revenue"], 100)
        r["net_margin_pct"] = _ratio(r["net_profit"], r["revenue"], 100)
        r["roe_pct"] = _ratio(r["net_profit"], avg_equity, 100)
        r["roce_pct"] = _ratio(r["ebit"], capital_employed, 100)
        r["debt_to_equity"] = _ratio(r["total_debt"], r["equity"])
        r["interest_coverage"] = _ratio(r["ebit"], abs(r["interest_expense"]) if r["interest_expense"] else None)
        r["cash_conversion"] = _ratio(r["operating_cash_flow"], r["net_profit"])
        r["revenue_growth_pct"] = _ratio(r["revenue"] - prev["revenue"], abs(prev["revenue"]), 100) if prev and r["revenue"] is not None and prev["revenue"] else None
        r["profit_growth_pct"] = _ratio(r["net_profit"] - prev["net_profit"], abs(prev["net_profit"]), 100) if prev and r["net_profit"] is not None and prev["net_profit"] else None
    return table


def growth_summary(table: list[dict]) -> dict:
    if len(table) < 2:
        return {}
    first, last = table[0], table[-1]
    n = len(table) - 1
    return {
        "years": n,
        "from": first["year"],
        "to": last["year"],
        "revenue_cagr_pct": cagr(first["revenue"], last["revenue"], n),
        "profit_cagr_pct": cagr(first["net_profit"], last["net_profit"], n),
        "eps_cagr_pct": cagr(first["eps"], last["eps"], n),
        "ebitda_cagr_pct": cagr(first["ebitda"], last["ebitda"], n),
    }


def data_checks(table: list[dict], profile: dict, converted_from: str | None = None) -> list[str]:
    """Cross-checks that tell the user when the numbers deserve extra scrutiny."""
    checks = []
    for prev, r in zip(table, table[1:]):
        if prev.get("equity") and r.get("equity") and r["equity"] / prev["equity"] > 1.6:
            checks.append(f"Equity rose {r['equity'] / prev['equity']:.1f}x in {r['year']} (merger, acquisition or "
                          f"capital raise?). Comparisons across {prev['year']}→{r['year']} may not be like-for-like.")
    computed, reported = (table[-1].get("roe_pct") if table else None), profile.get("roe_ttm_pct")
    if computed and reported and abs(computed - reported) / abs(reported) > 0.25:
        checks.append(f"Sources disagree on ROE: {computed:.1f}% computed from annual statements vs "
                      f"{reported:.1f}% trailing-twelve-month figure from the data provider. Verify against the annual report.")
    if converted_from:
        checks.append(f"Statements are reported in {converted_from} and were converted to ₹ at the "
                      f"exchange rate on each fiscal year-end date, so growth rates include currency movements.")
    if len(table) < 5:
        checks.append(f"Only {len(table)} years of statements are available from the current data source.")
    return checks
