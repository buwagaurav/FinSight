"""Assembles a full company analysis from the providers and the deterministic analytics engine.

Shared by the REST API and the AI assistant's tools, so both always see identical numbers.
"""
from concurrent.futures import ThreadPoolExecutor

from app import db
from app.analytics import fundamentals, scores, technicals, valuation
from app.providers import sec, yahoo


# Shared by all requests: a few upstream fetches per page in flight at once, bounded so a burst of visitors
# can't open hundreds of connections to Yahoo and SEC.
_pool = ThreadPoolExecutor(max_workers=24, thread_name_prefix="fetch")


def _stored(symbol: str) -> tuple[dict, dict, str] | None:
    """Profile and statements the loader saved (refreshed twice a day), for when live Yahoo data can't be
    fetched, e.g. Yahoo refusing requests from a cloud host."""
    try:
        row = db.fetch_one("""SELECT p.data AS profile, s.data AS statements, p.updated_at FROM profiles p
                              JOIN statements s USING (symbol) WHERE p.symbol = %s""", (symbol.split(".")[0],))
    except Exception:  # no database configured / reachable
        return None
    return (row["profile"], row["statements"], row["updated_at"].strftime("%d %b %Y, %H:%M UTC")) if row else None


def _us_profile_from_sec(symbol: str) -> dict:
    """What SEC EDGAR alone can say about a US company when Yahoo's quote is unavailable: no live price."""
    info, ind = sec.lookup(symbol), sec.industry(symbol)
    blank = dict.fromkeys(["summary", "price", "previous_close", "change_pct", "market_cap_cr", "week52_high",
                           "week52_low", "pe", "forward_pe", "pb", "ev_ebitda", "ps", "peg", "dividend_yield_pct",
                           "roe_ttm_pct", "debt_to_equity_ttm", "promoter_holding_pct", "institutional_holding_pct",
                           "beta", "trailing_eps"])
    return {**blank, "symbol": symbol, "name": sec._title(info["name"]), "exchange": info["exchange"],
            "sector": ind["sector"], "industry": ind["industry"], "website": ind["website"], "currency": "USD",
            "financial_currency": "USD",
            "source": {"name": "SEC EDGAR", "url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={info['cik']}"}}


def _stored_us(symbol: str) -> dict | None:
    try:
        row = db.fetch_one("SELECT data FROM us_statements WHERE symbol = %s", (symbol,))
    except Exception:   # no database, or the US tables don't exist yet
        return None
    return row["data"] if row else None


def _stored_us_quote(symbol: str) -> dict | None:
    """Last close and screener multiples saved by the daily US refresh (app.us_market)."""
    try:
        row = db.fetch_one("""SELECT p.price, p.previous_close, p.price_date, m.market_cap_cr, m.pe, m.pb,
                                     m.dividend_yield_pct
                              FROM us_prices p LEFT JOIN us_metrics m USING (symbol) WHERE p.symbol = %s""", (symbol,))
    except Exception:
        return None
    if not row:
        return None
    prev = row.pop("previous_close")
    row["change_pct"] = (row["price"] / prev - 1) * 100 if prev else None
    return row


def _us_quote_from_history(profile: dict, symbol: str, table: list[dict], history: list[dict]) -> str | None:
    """Price and ratios for a US company when Yahoo's quote endpoint refuses us but its price history doesn't:
    the latest close from the history, everything else from SEC filings (as the US screener computes them)."""
    closes = [p["close"] for p in history]
    price, prev = closes[-1], (closes[-2] if len(closes) > 1 else None)
    year = closes[-252:]
    profile.update(price=price, previous_close=prev, change_pct=(price / prev - 1) * 100 if prev else None,
                   week52_high=max(year), week52_low=min(year))
    try:
        facts = sec.company_facts(sec.lookup(symbol)["cik"])
        shares, ttm, balance = sec.shares_from_facts(facts), sec.ttm_net_income(facts), sec.latest_balance(facts)
    except Exception:
        shares, ttm, balance = None, None, {}
    if not table:
        # foreign companies (20-F/ADRs): the share count is in ordinary shares but the price is per ADR, and the
        # ratio isn't in the filings, so a market cap would be wrong by that ratio
        shares = None
    last = table[-1] if table else {}
    # latest quarter's balance sheet when reported (as quote providers do), else the last annual one ($M)
    equity = balance["equity"] / sec.MILLION if balance.get("equity") else last.get("equity")
    debt = (balance["total_debt"] / sec.MILLION if balance.get("total_debt") is not None
            else last.get("total_debt")) if balance else last.get("total_debt")
    if shares:
        mcap = price * shares / sec.MILLION
        profile["market_cap_cr"] = mcap
        dividends = -(last.get("dividends_paid") or 0)
        profile["dividend_yield_pct"] = dividends / mcap * 100 if dividends > 0 else 0.0
        if equity and equity > 0:
            profile["pb"] = mcap / equity
        if ttm:
            profile["trailing_eps"] = ttm[0] / shares
            profile["pe"] = price / profile["trailing_eps"] if ttm[0] > 0 else None
        if profile.get("pe") is not None and profile["pe"] < 1:
            # a P/E under 1 means the share count and the price are on different share bases (e.g. per-class
            # reporting); show nothing rather than a wrong market cap
            for k in ("market_cap_cr", "pe", "pb", "dividend_yield_pct", "trailing_eps"):
                profile[k] = None
    if ttm and equity and equity > 0:
        profile["roe_ttm_pct"] = ttm[0] / sec.MILLION / equity * 100
    if equity and equity > 0 and debt is not None and profile.get("sector") != "Financial Services":
        profile["debt_to_equity_ttm"] = debt / equity
    return ("Yahoo's live quote is unavailable right now: the price is the latest close from Yahoo's price history, "
            "and market cap and ratios are computed from SEC filings.")


def _us_inputs(symbol: str) -> tuple[dict, dict, str | None]:
    """Profile (Yahoo quote, or SEC-only) and SEC statements for a US listing. LookupError if not listed."""
    sec.lookup(symbol)
    note = None
    quote = _pool.submit(yahoo.profile, symbol)          # Yahoo and SEC at the same time
    filings = _pool.submit(sec.annual_statements, symbol)
    try:
        profile = dict(quote.result())
    except Exception:   # price and ratios are filled in by company_report from price history or stored data
        profile = _us_profile_from_sec(symbol)
    if not profile.get("sector"):
        profile["sector"] = sec.industry(symbol)["sector"]
    try:
        statements = filings.result()
    except LookupError:
        statements = None
    except Exception:   # SEC unreachable: use the statements the nightly US refresh stored, if any
        statements = _stored_us(symbol)
        if statements:
            note = ((note + " ") if note else "") + "SEC EDGAR is unavailable right now; statements are from FinSight's last refresh."
        else:
            raise
    if statements is None:
        statements = {"income": {}, "balance": {}, "cashflow": {}, "converted_from": None, "scale": sec.MILLION}
        note = ((note + " ") if note else "") + (
            "This company doesn't file US-GAAP annual reports (10-K) with the SEC, typically because it is a "
            "foreign company filing a 20-F under IFRS, so FinSight can't show its financial statements yet.")
    return profile, statements, note


def company_report(symbol: str) -> dict:
    """Raises LookupError when the symbol is not a listed company."""
    symbol = yahoo.normalize_symbol(symbol)
    stale_note = None
    # The quote, statements and price history come from separate requests: start them all at once rather than
    # one after another. (The statements fetch needs the quote too; the cache makes it wait for the same call.)
    prices = _pool.submit(yahoo.price_history, symbol)
    if sec.is_us(symbol):
        profile, statements, stale_note = _us_inputs(symbol)
    else:
        quote = _pool.submit(yahoo.profile, symbol)
        filed = _pool.submit(yahoo.annual_statements, symbol)
        try:
            profile = dict(quote.result())  # copy: we override some multiples below, the cached original stays intact
            statements = filed.result()
        except Exception:
            stored = _stored(symbol)
            if not stored:
                raise LookupError(symbol)
            profile, statements, as_of = dict(stored[0]), stored[1], stored[2]
            stale_note = f"Live market data is unavailable right now; showing FinSight's last stored data ({as_of})."
    table = fundamentals.build_table(statements)
    growth = fundamentals.growth_summary(table)
    try:
        history = prices.result()
    except Exception:
        history = []  # chart and trend show "insufficient data"; fundamentals still work
    if sec.is_us(symbol) and profile.get("price") is None:   # Yahoo's quote failed
        note = None
        if history:
            note = _us_quote_from_history(profile, symbol, table, history)
        elif stored := _stored_us_quote(symbol):
            profile.update({k: v for k, v in stored.items() if k != "price_date"})
            note = (f"Live prices from Yahoo Finance are unavailable right now; showing the {stored['price_date']:%d %b %Y} "
                    "closing price from FinSight's daily refresh.")
        note = note or "Live prices from Yahoo Finance are unavailable right now; fundamentals below are from SEC filings."
        stale_note = f"{note} {stale_note}" if stale_note else note
    technical = technicals.summarize(history, "$" if sec.is_us(symbol) else "₹")
    pe_history = valuation.historical_pe(table, history)
    checks = fundamentals.data_checks(table, profile, statements.get("converted_from"))
    if stale_note:
        checks.insert(0, stale_note)
    _own_multiples(profile, table)
    company_scores = scores.compute(profile, table, growth, technical, pe_history)
    if checks and company_scores["confidence"] == "High":
        company_scores["confidence"] = "Medium"

    return {
        "profile": profile,
        "financials": {"unit": "$ M (EPS in $)" if sec.is_us(symbol) else "₹ Cr (EPS in ₹)", "years": table,
                       "growth": growth, "data_checks": checks,
                       "source": statements.get("source") or {"name": "Company filings via Yahoo Finance",
                                                              "url": profile["source"]["url"] + "/financials"}},
        "scores": company_scores,
        "technical": technical,
        "valuation": {
            "pe_history": pe_history,
            "scenarios": valuation.scenarios(profile["price"], profile["trailing_eps"], growth.get("eps_cagr_pct"),
                                             pe_history, profile["pe"]),
        },
        # Weekly closes keep the payload small; the chart does not need daily points over 5 years.
        "prices": history[::5] + ([history[-1]] if history and len(history) % 5 != 1 else []),
    }


def _own_multiples(profile: dict, table: list[dict]) -> None:
    """Recompute P/S and EV/EBITDA from our rupee statements. The provider's versions mix currencies
    for companies that report in USD."""
    last = table[-1] if table else {}
    mcap = profile.get("market_cap_cr")
    if not mcap:
        return
    if last.get("revenue"):
        profile["ps"] = mcap / last["revenue"]
    if last.get("ebitda") and last["ebitda"] > 0 and profile.get("sector") != "Financial Services":
        profile["ev_ebitda"] = (mcap + (last.get("total_debt") or 0) - (last.get("cash") or 0)) / last["ebitda"]
    elif profile.get("sector") == "Financial Services":
        profile["ev_ebitda"] = None  # enterprise value is not meaningful for lenders
