"""Market data from Yahoo Finance (via yfinance) for NSE/BSE-listed companies.

All monetary statement values are converted to ₹ crore (1 Cr = 1e7) at this boundary,
so everything downstream works in the units Indian investors read.
"""
import math
import re

import pandas as pd
import yfinance as yf

from app.cache import ttl_cache

CRORE = 1e7
INDIAN_EXCHANGES = {"NSI": "NSE", "BSE": "BSE"}


def normalize_symbol(symbol: str) -> str:
    symbol = symbol.strip().upper()
    if "." not in symbol:
        symbol += ".NS"
    return symbol


def _clean(value):
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return value
    return None if math.isnan(f) or math.isinf(f) else f


@ttl_cache(seconds=3600)
def search(query: str) -> list[dict]:
    results = yf.Search(query, max_results=12, news_count=0).quotes
    seen, out = set(), []
    for q in results:
        exchange = INDIAN_EXCHANGES.get(q.get("exchange"))
        if not exchange:
            continue
        base = q["symbol"].split(".")[0]
        if base in seen:  # prefer the NSE listing when a company trades on both
            continue
        seen.add(base)
        out.append({
            "symbol": q["symbol"],
            "name": q.get("longname") or q.get("shortname") or q["symbol"],
            "exchange": exchange,
            "sector": q.get("sectorDisp") or q.get("sector"),
        })
    return out


@ttl_cache(seconds=600)
def profile(symbol: str) -> dict:
    info = yf.Ticker(symbol).info
    has_name = info.get("longName") or info.get("shortName")
    if not info or not has_name or info.get("quoteType") not in ("EQUITY", None):
        raise LookupError(symbol)
    price = _clean(info.get("currentPrice") or info.get("regularMarketPrice"))
    prev = _clean(info.get("previousClose"))
    debt_to_equity = _clean(info.get("debtToEquity"))
    return {
        "symbol": symbol,
        "name": info.get("longName") or info.get("shortName"),
        "exchange": "BSE" if symbol.endswith(".BO") else "NSE",
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "summary": info.get("longBusinessSummary"),
        "website": info.get("website"),
        "currency": info.get("currency", "INR"),
        "price": price,
        "previous_close": prev,
        "change_pct": (price / prev - 1) * 100 if price and prev else None,
        "market_cap_cr": _clean(info.get("marketCap")) / CRORE if info.get("marketCap") else None,
        "week52_high": _clean(info.get("fiftyTwoWeekHigh")),
        "week52_low": _clean(info.get("fiftyTwoWeekLow")),
        "pe": _clean(info.get("trailingPE")),
        "forward_pe": _clean(info.get("forwardPE")),
        "pb": _clean(info.get("priceToBook")),
        "ev_ebitda": _clean(info.get("enterpriseToEbitda")),
        "ps": _clean(info.get("priceToSalesTrailing12Months")),
        "peg": _clean(info.get("trailingPegRatio")),
        "dividend_yield_pct": _clean(info.get("dividendYield")),
        "roe_ttm_pct": _clean(info.get("returnOnEquity")) * 100 if info.get("returnOnEquity") is not None else None,
        # Yahoo reports D/E as a percentage (10.2 means 0.102x)
        "debt_to_equity_ttm": debt_to_equity / 100 if debt_to_equity is not None else None,
        "promoter_holding_pct": _clean(info.get("heldPercentInsiders")) * 100 if info.get("heldPercentInsiders") is not None else None,
        "institutional_holding_pct": _clean(info.get("heldPercentInstitutions")) * 100 if info.get("heldPercentInstitutions") is not None else None,
        "beta": _clean(info.get("beta")),
        "trailing_eps": _clean(info.get("trailingEps")),
        "financial_currency": info.get("financialCurrency") or info.get("currency", "INR"),
        "source": {"name": "Yahoo Finance", "url": f"https://finance.yahoo.com/quote/{symbol}"},
    }


def _statement_rows(df: pd.DataFrame) -> dict[str, dict[str, float | None]]:
    """{fiscal_year_label: {line_item: value}} for an annual yfinance statement."""
    out = {}
    if df is None or df.empty:
        return out
    for col in df.columns:
        label = f"FY{str(col.year)[2:]}" if col.month <= 6 else f"FY{str(col.year + 1)[2:]}"
        out[label] = {"period_end": col.date().isoformat(), **{k: _clean(v) for k, v in df[col].items()}}
    return out


NON_MONETARY = ("Shares", "Share Issued", "Tax Rate")


def _fx_to_inr(currency: str) -> pd.Series:
    """Daily closing rate for 1 unit of `currency` in rupees."""
    hist = yf.Ticker(f"{currency}INR=X").history(period="10y", interval="1d")["Close"]
    hist.index = hist.index.tz_localize(None).normalize()
    return hist


def _convert(rows: dict, fx: pd.Series) -> dict:
    for row in rows.values():
        rate = fx.asof(pd.Timestamp(row["period_end"]))
        for k, v in row.items():
            if isinstance(v, float) and not any(tag in k for tag in NON_MONETARY):
                row[k] = v * rate
        row["fx_rate_to_inr"] = float(rate)
    return rows


def _statements_in_foreign_currency(income: dict, fx: pd.Series, trailing_eps: float | None) -> bool:
    """Yahoo's financialCurrency label is unreliable (Infosys statements really are USD; HCLTech's are
    INR despite a USD label). Decide from the numbers: rupee trailing EPS should be close to the latest
    statement EPS either as-is or after conversion."""
    latest = income[max(income)] if income else {}
    eps = latest.get("Diluted EPS") or latest.get("Basic EPS")
    if not eps or not trailing_eps or eps <= 0 or trailing_eps <= 0:
        return False
    rate = fx.asof(pd.Timestamp(latest["period_end"]))
    return abs(math.log(trailing_eps / (eps * rate))) < abs(math.log(trailing_eps / eps))


@ttl_cache(seconds=6 * 3600)
def annual_statements(symbol: str) -> dict:
    """Annual statements in rupees. A few Indian companies (e.g. Infosys) are stored by Yahoo in USD;
    those are converted at the exchange rate on each fiscal year-end date."""
    t = yf.Ticker(symbol)
    out = {
        "income": _statement_rows(t.income_stmt),
        "balance": _statement_rows(t.balance_sheet),
        "cashflow": _statement_rows(t.cashflow),
        "converted_from": None,
    }
    p = profile(symbol)
    currency = p["financial_currency"]
    if currency != "INR":
        fx = _fx_to_inr(currency)
        if _statements_in_foreign_currency(out["income"], fx, p["trailing_eps"]):
            for key in ("income", "balance", "cashflow"):
                _convert(out[key], fx)
            out["converted_from"] = currency
    return out


@ttl_cache(seconds=900)
def price_history(symbol: str, period: str = "5y") -> list[dict]:
    hist = yf.Ticker(symbol).history(period=period, interval="1d", auto_adjust=True)
    return [
        {"date": idx.date().isoformat(), "close": round(float(row["Close"]), 2), "volume": int(row["Volume"])}
        for idx, row in hist.iterrows()
        if not math.isnan(row["Close"])
    ]


FOREIGN_TICKER = re.compile(r"\((?:NYSE|NASDAQ|XTRA|LSE|TSX|ASX|NasdaqGS|NasdaqGM|NasdaqCM):", re.IGNORECASE)
_SUFFIXES = {"limited", "ltd", "ltd.", "india", "(india)", "company", "co", "corporation", "industries", "the"}


def _name_keys(symbol: str) -> list[str]:
    """Ways an article might name the company: its NSE symbol and the distinctive part of its name."""
    keys = {symbol.split(".")[0].lower()}
    try:
        words = [w for w in profile(symbol)["name"].lower().split() if w not in _SUFFIXES]
        if len(words) >= 2:
            keys.add(" ".join(words[:2]))  # "tata consultancy", not "tata" (which matches the whole group)
        elif words and len(words[0]) > 3:
            keys.add(words[0])
    except LookupError:
        pass
    return sorted(keys)


@ttl_cache(seconds=900)
def news(symbol: str) -> list[dict]:
    """Recent articles that actually mention the company. Yahoo's feed for Indian tickers mixes in unrelated
    stories, so anything that doesn't name the company or its symbol is dropped."""
    keys = _name_keys(symbol)
    items = []
    for n in yf.Ticker(symbol).news or []:
        c = n.get("content", n)
        url = (c.get("canonicalUrl") or {}).get("url") or (c.get("clickThroughUrl") or {}).get("url")
        if not c.get("title") or not url:
            continue
        text = f"{c['title']} {c.get('summary') or c.get('description') or ''}".lower()
        if not any(re.search(rf"\b{re.escape(k)}\b", text) for k in keys):
            continue
        if FOREIGN_TICKER.search(c["title"]):
            continue  # e.g. "Reliance (NYSE:RS)" is Reliance Steel, not Reliance Industries
        items.append({
            "title": c["title"],
            "summary": c.get("summary") or c.get("description") or "",
            "published": c.get("pubDate"),
            "publisher": (c.get("provider") or {}).get("displayName"),
            "url": url,
        })
    return items
