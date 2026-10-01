"""Tools the research assistant can call. Each wraps the deterministic engine; none of them let the
model invent data. Every result is tagged with source ids ("S1", "S2", ...) the answer must cite.
"""
import json
import math
import re
import statistics
import threading
from datetime import datetime, timezone

from app import gmp, ipos, research, screener
from app.analytics import fundamentals, portfolio, technicals
from app.providers import investorgain, nse, sec, yahoo

SYMBOL = {"type": "string", "description": "NSE symbol such as TCS or RELIANCE.NS, or a US listing ending in .US such as "
                                           "AAPL.US (use search_company if unsure)."}

TOOLS = [
    {
        "name": "search_company",
        "description": "Find NSE/BSE and US-listed companies by name or ticker. Returns symbols to use with the other tools.",
        "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    },
    {
        "name": "get_company_snapshot",
        "description": "Price, ratios, FinSight scores with reasons, trend, CAGR and data warnings for a company.",
        "input_schema": {"type": "object", "properties": {"symbol": SYMBOL}, "required": ["symbol"]},
    },
    {
        "name": "get_financials",
        "description": "Annual statements by fiscal year with margins, ROE, ROCE, D/E, cash flow and YoY growth. Amounts are "
                       "₹ Cr (EPS ₹) for Indian companies and $ M (EPS $) for US companies; see `unit`.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": SYMBOL,
                "metrics": {"type": "array", "items": {"type": "string"},
                            "description": "Field names to return. Omit for the core set (revenue, profits, EPS, margins, ROE, ROCE, D/E, cash flows, growth). Others: ebitda, ebit, interest_expense, equity, total_debt, cash, working_capital, total_assets, capex, dividends_paid, interest_coverage, cash_conversion."},
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "get_valuation",
        "description": "Valuation ratios, P/E at each year end, and 3-year bear/base/bull scenarios with assumptions.",
        "input_schema": {"type": "object", "properties": {"symbol": SYMBOL}, "required": ["symbol"]},
    },
    {
        "name": "get_news",
        "description": "Recent news about a company.",
        "input_schema": {"type": "object", "properties": {"symbol": SYMBOL}, "required": ["symbol"]},
    },
    {
        "name": "get_announcements",
        "description": "Latest official filings: NSE announcements (results, dividends, orders, acquisitions...) or, "
                       "for US companies, SEC filings (8-K current reports, 10-Q, 10-K, proxy statements).",
        "input_schema": {"type": "object", "properties": {"symbol": SYMBOL}, "required": ["symbol"]},
    },
    {
        "name": "search_documents",
        "description": "NSE-listed companies only. Search the company's latest annual report and recent NSE filings for what the company or "
                       "management said: strategy, reasons behind results, guidance, risks, orders, deals. Returns "
                       "passages with page numbers. Quote exact words from them.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": SYMBOL,
                "query": {"type": "string", "description": "Specific search words, e.g. 'attrition rate' or 'generative AI revenue'"},
                "kind": {"type": "string", "enum": ["any", "annual_report", "filing"]},
            },
            "required": ["symbol", "query"],
        },
    },
    {
        "name": "compare_companies",
        "description": "Key metrics side by side for 2-6 companies (peer comparison).",
        "input_schema": {
            "type": "object",
            "properties": {"symbols": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 6}},
            "required": ["symbols"],
        },
    },
    {
        "name": "run_screen",
        "description": "Screen all NSE stocks (market IN, market cap in ₹ Cr) or US-listed stocks (market US, market cap "
                       "in $ M) with numeric filters (percent fields in %).",
        "input_schema": {
            "type": "object",
            "properties": {
                "market": {"type": "string", "enum": ["IN", "US"], "description": "Default IN"},
                "filters": {"type": "array", "items": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string", "enum": list(screener.FIELDS)},
                        "op": {"type": "string", "enum": [">", ">=", "<", "<="]},
                        "value": {"type": "number"},
                    },
                    "required": ["field", "op", "value"],
                }},
                "sort": {"type": "string", "enum": list(screener.FIELDS)},
                "sectors": {"type": "array", "items": {"type": "string", "enum": screener.SECTORS}},
            },
            "required": ["filters"],
        },
    },
    {
        "name": "get_ipo_data",
        "description": "IPOs tracked from NSE (official issue data) and InvestorGain: status, dates, price band, lot, issue "
                       "size, subscription, listing gain, and the unofficial grey-market premium (GMP) with when it was "
                       "observed. Omit query to list open and upcoming IPOs.",
        "input_schema": {"type": "object", "properties": {
            "query": {"type": "string", "description": "IPO company name or symbol, e.g. 'Tata Capital'"}}},
    },
    {
        "name": "get_technicals",
        "description": "Price trend: 50/200-day moving averages, returns over 1m/3m/6m/1y, 1-year volatility, maximum "
                       "drawdown, 52-week range and beta against the Nifty 50 (S&P 500 for US stocks).",
        "input_schema": {"type": "object", "properties": {"symbol": SYMBOL}, "required": ["symbol"]},
    },
    {
        "name": "portfolio_risk",
        "description": "Risk of a portfolio of 1-15 listed stocks: concentration, sector weights, 1-year volatility, "
                       "maximum drawdown, beta, correlation and diversification. Weights may be percentages or amounts.",
        "input_schema": {
            "type": "object",
            "properties": {"holdings": {"type": "array", "minItems": 1, "maxItems": 15, "items": {
                "type": "object",
                "properties": {"symbol": SYMBOL, "weight": {"type": "number", "description": "% or amount invested"}},
                "required": ["symbol", "weight"],
            }}},
            "required": ["holdings"],
        },
    },
    {
        "name": "calculate",
        "description": "Calculator for all arithmetic. cagr [first,last,years] -> %/yr; percent_change [from,to] -> %; "
                       "ratio [a,b]; difference [a,b]; sum; average.",
        "input_schema": {
            "type": "object",
            "properties": {
                "operation": {"type": "string", "enum": ["cagr", "percent_change", "ratio", "difference", "sum", "average"]},
                "values": {"type": "array", "items": {"type": "number"}},
                "label": {"type": "string", "description": "What is calculated"},
            },
            "required": ["operation", "values", "label"],
        },
    },
]


OFFICIAL = re.compile(r"^(NSE|SEC|BSE)\b")


def source_type(name: str) -> str:
    """official: the exchange or regulator's own record; unofficial: grey-market data; secondary: everything else
    (data vendors, news, and FinSight's own calculations over them)."""
    if "GMP" in name:
        return "unofficial"
    return "official" if OFFICIAL.match(name) else "secondary"


class Sources:
    """Registry of everything the assistant has looked at, so every claim can point to where it came from."""

    def __init__(self):
        self.items: list[dict] = []
        self._lock = threading.Lock()  # agents in the multi-agent report share one registry

    def add(self, name: str, url: str | None, detail: str, period: str | None = None) -> str:
        """`period` is what the data describes ("FY2021-FY2025", "as of 2026-09-30 15:30"), when known."""
        with self._lock:
            for s in self.items:
                if (s["name"], s["url"], s["detail"]) == (name, url, detail):
                    return s["id"]
            sid = f"S{len(self.items) + 1}"
            self.items.append({"id": sid, "name": name, "url": url, "detail": detail, "source_type": source_type(name),
                               "period": period, "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
            return sid


def _round(value):
    """Two decimals is plenty for the model and makes its quoted figures traceable to the tool output.
    Empty fields are dropped: every token sent to the model costs money."""
    if isinstance(value, float):
        return None if math.isnan(value) else round(value, 2)
    if isinstance(value, dict):
        return {k: _round(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_round(v) for v in value]
    return value


def _company_name(report: dict) -> str:
    return f"{report['profile']['name']} ({report['profile']['symbol']})"


def _years(report: dict) -> str | None:
    years = report["financials"]["years"]
    return f"{years[0]['year']}-{years[-1]['year']}" if years else None


def _snapshot(args, sources: Sources):
    r = research.company_report(args["symbol"])
    p = r["profile"]
    name = _company_name(r)
    src_quote = sources.add("Yahoo Finance quote", p["source"]["url"], f"{name}: price and ratios")
    src_fin = sources.add(r["financials"]["source"]["name"], r["financials"]["source"]["url"], f"{name}: annual statements",
                          _years(r))
    src_engine = sources.add("FinSight scoring engine", None, f"{name}: rule-based scores ({r['scores']['method']})")
    keep = ["symbol", "name", "sector", "industry", "price", "change_pct", "market_cap_cr", "week52_high", "week52_low",
            "pe", "pb", "roe_ttm_pct", "debt_to_equity_ttm", "dividend_yield_pct", "promoter_holding_pct",
            "institutional_holding_pct", "trailing_eps"]
    s = r["scores"]
    return {
        "profile": {"source": src_quote, **{k: p[k] for k in keep}, "currency": p.get("currency", "INR"),
                    "market_cap_unit": "$ M" if sec.is_us(p["symbol"]) else "₹ Cr"},
        "growth": {"source": src_fin, **r["financials"]["growth"]},
        "scores": {
            "source": src_engine,
            "overall": s["overall"], "view": s["view"], "confidence": s["confidence"],
            "confidence_basis": s["confidence_basis"], "positives": s["positives"], "risks": s["risks"],
            "cards": {k: {"score": c["score"], "label": c["label"], "reasons": c["reasons"]} for k, c in s["cards"].items()},
        },
        "technical": {"source": src_quote, **r["technical"]},
        "data_checks": r["financials"]["data_checks"],
    }


CORE_METRICS = ["revenue", "operating_profit", "net_profit", "eps", "operating_margin_pct", "net_margin_pct",
                "roe_pct", "roce_pct", "debt_to_equity", "operating_cash_flow", "free_cash_flow",
                "revenue_growth_pct", "profit_growth_pct"]


def _financials(args, sources: Sources):
    r = research.company_report(args["symbol"])
    src = sources.add(r["financials"]["source"]["name"], r["financials"]["source"]["url"], f"{_company_name(r)}: annual statements",
                      _years(r))
    years = r["financials"]["years"]
    wanted = args.get("metrics") or CORE_METRICS
    if wanted:
        years = [{k: v for k, v in y.items() if k in wanted or k in ("year", "period_end")} for y in years]
    return {"source": src, "unit": r["financials"]["unit"], "years": years, "data_checks": r["financials"]["data_checks"]}


def _valuation(args, sources: Sources):
    r = research.company_report(args["symbol"])
    p = r["profile"]
    name = _company_name(r)
    src_quote = sources.add("Yahoo Finance quote", p["source"]["url"], f"{name}: price and ratios")
    src_engine = sources.add("FinSight valuation engine", None, f"{name}: historical P/E and scenarios")
    return {
        "ratios": {"source": src_quote, **{k: p[k] for k in ["price", "pe", "forward_pe", "pb", "ev_ebitda", "peg", "ps", "dividend_yield_pct"]}},
        "pe_at_year_end": {"source": src_engine, "rows": r["valuation"]["pe_history"]},
        "scenarios": {"source": src_engine, **(r["valuation"]["scenarios"] or {"note": "Not enough data for scenarios."})},
    }


def _news(args, sources: Sources):
    symbol = yahoo.normalize_symbol(args["symbol"])
    items = []
    for n in yahoo.news(symbol)[:8]:
        sid = sources.add(n["publisher"] or "News", n["url"], n["title"])
        items.append({"source": sid, **n})
    return {"symbol": symbol, "articles": items} if items else {"symbol": symbol, "articles": [], "note": "No recent news found."}


def _announcements(args, sources: Sources):
    items = []
    us = sec.is_us(args["symbol"])
    for a in sec.filings(args["symbol"], 60) if us else nse.announcements(args["symbol"], 25):
        if a["routine"]:
            continue
        sid = sources.add("SEC filing" if us else "NSE filing", a["pdf_url"],
                          f"{a['company']}: {a['category']} ({(a['published'] or '')[:10]})", (a["published"] or "")[:10] or None)
        items.append({"source": sid, "date": (a["published"] or "")[:10], "category": a["category"], "text": a["text"][:220]})
    return {"announcements": items[:8], "note": "Routine procedural filings are omitted."}


def _search_documents(args, sources: Sources):
    from app import docs  # local import: keeps the tool list importable without the database
    symbol = yahoo.normalize_symbol(args["symbol"])
    if sec.is_us(symbol):
        return {"result": "Document search covers NSE-listed companies only. Use get_announcements for this "
                          "company's SEC filings."}
    try:
        docs.index_filings(symbol)  # small PDFs; indexed on first use, cheap afterwards
    except Exception:
        pass  # search whatever is already stored
    kind = None if args.get("kind") in (None, "any") else args["kind"]
    rows = docs.search(symbol, args["query"], kind, limit=5)
    have = docs.coverage(symbol)
    passages = []
    for r in rows:
        label = "annual report" if r["kind"] == "annual_report" else "filing"
        period = r.get("fiscal_year") or (str(r["published"])[:10] if r.get("published") else None)
        sid = sources.add(f"NSE {label}, page {r['page']}", f"{r['url']}#page={r['page']}",
                          f"{symbol}: {r['title'][:120]}", period)
        passages.append({"source": sid, "document": r["title"][:120], "page": r["page"], "text": r["text"][:1200],
                         **({"period": period} if period else {})})
    note = None if "annual_report" in have else "This company's annual report isn't indexed yet; only recent filings were searched."
    return {"passages": passages, **({"note": note} if note else {}),
            **({} if passages else {"result": "No matching passages found."})}


def _compare(args, sources: Sources):
    symbols = args["symbols"][:6]
    stored = screener.lookup(symbols)
    rows = []
    for sym in symbols:
        us = sec.is_us(sym)
        row = None if us else stored.get(sym.split(".")[0].upper())   # the screener stores NSE companies only
        if row is None:  # not loaded yet: compute it live with the same engine
            try:
                r = research.company_report(sym)
                row = {"symbol": r["profile"]["symbol"],
                       **{k: v for k, v in screener.metrics_row(r["profile"], r["financials"]["years"]).items() if k != "yahoo_symbol"},
                       "latest_fiscal_year": (r["financials"]["years"] or [{}])[-1].get("year")}
            except LookupError:
                rows.append({"symbol": sym, "error": "not found"})
                continue
        sid = sources.add("SEC filings and Yahoo Finance quote" if us else "Company filings via Yahoo Finance",
                          f"https://finance.yahoo.com/quote/{yahoo.yahoo_ticker(row['symbol'])}",
                          f"{row['name']} ({row['symbol']}): metrics", row.get("latest_fiscal_year"))
        rows.append({"source": sid, **row, "amount_unit": "$ M" if us else "₹ Cr"})
    found = [r for r in rows if "error" not in r]
    notes = ["ROCE and debt/equity are not computed for banks and financials.",
             "Amounts are in each company's own currency (see amount_unit)."]
    years = {r["latest_fiscal_year"] for r in found if r.get("latest_fiscal_year")}
    if len(years) > 1:
        notes.append(f"The latest annual figures cover different fiscal years ({', '.join(sorted(years))}); "
                     "say so when comparing them.")
    if len({r["amount_unit"] for r in found}) > 1:
        notes.append("These companies report in different currencies: compare ratios, not amounts.")
    out = {"companies": rows, "note": " ".join(notes)}
    if len(found) >= 2:
        sid = sources.add("FinSight calculator", None, "peer median and average of " + ", ".join(r["symbol"] for r in found))
        out["peer_stats"] = {"source": sid, **_peer_stats(found)}
    return out


PEER_FIELDS = ("pe", "pb", "roe_pct", "roce_pct", "debt_to_equity", "revenue_cagr_pct", "profit_cagr_pct",
               "operating_margin_pct", "dividend_yield_pct")


def _peer_stats(rows: list[dict]) -> dict:
    """Median and mean of each ratio over the companies that have it (ratios only: amounts mix currencies)."""
    out = {}
    for f in PEER_FIELDS:
        vals = [r[f] for r in rows if isinstance(r.get(f), (int, float)) and not math.isnan(r[f])]
        if len(vals) >= 2:
            out[f] = {"median": statistics.median(vals), "average": statistics.fmean(vals), "companies": len(vals)}
    return out


def _screen(args, sources: Sources):
    result = screener.run(args["filters"], args.get("sort") or "market_cap_cr", True, args.get("sectors"),
                          "US" if args.get("market") == "US" else "IN")
    sid = sources.add("FinSight screener", None, f"{result['universe']}: {result['query']}")
    keep = ("symbol", "name", "market_cap_cr", "pe", "roe_pct", "debt_to_equity", "profit_cagr_pct")
    rows = [{k: r[k] for k in keep} for r in result["rows"][:10]]
    return {"source": sid, "query": result["query"], "count": result["count"], "top_10": rows}


def _ipo_data(args, sources: Sources):
    rows = ipos.current()
    query = (args.get("query") or "").strip()
    words = set(investorgain.normalize(query))   # "Tata Capital Ltd IPO" -> {"tata", "capital"}
    if words:
        rows = [r for r in rows if query.upper() in (r["symbol"], r.get("nse_symbol"))] or \
            [r for r in rows if words <= set(investorgain.normalize(r["name"]))]
        if not rows:
            return {"ipos": [], "result": f"No tracked IPO matches '{query}'. FinSight tracks IPOs listed on "
                                          "InvestorGain and NSE's current issues."}
    else:
        rows = [r for r in rows if r["status"] in ("Open", "Upcoming")]
    rows = rows[:8]
    summaries = gmp.summaries(rows)
    out = []
    for r in rows:
        official = r["source"]["name"].startswith("NSE")
        sid = sources.add("NSE IPO data" if official else "InvestorGain IPO data", r["source"]["url"],
                          f"{r['name']}: issue details and subscription")
        item = {"source": sid, **{k: r[k] for k in ("name", "segment", "exchange", "status", "open_date", "close_date",
                                                     "allotment_date", "listing_date", "price_low", "price_high", "lot",
                                                     "issue_size_cr", "subscription_times", "listing_gain_pct")}}
        g = summaries[r["symbol"]]
        if g["latest"]:
            gid = sources.add("InvestorGain GMP (unofficial)", g["latest"]["source_url"], f"{r['name']}: grey-market premium",
                              g["latest"]["observed_at"][:16])
            item["gmp_unofficial"] = {"source": gid, "gmp_rs": g["latest"]["gmp"], "observed_at": g["latest"]["observed_at"],
                                      **({"estimated_premium_pct": g["estimate"]["estimated_premium_pct"]} if g["estimate"] else {}),
                                      "readings": len(g["history"]), "disclaimer": g["disclaimer"]}
        out.append(item)
    return {"ipos": out, "note": "Issue data from NSE is official; InvestorGain issue data is secondary. GMP is "
                                 "unofficial grey-market data, not a forecast of the listing price."}


def _benchmark(symbol: str) -> tuple[str, str]:
    return ("^GSPC", "S&P 500") if sec.is_us(symbol) else ("^NSEI", "Nifty 50")


def _technicals(args, sources: Sources):
    symbol = yahoo.normalize_symbol(args["symbol"])
    history = yahoo.price_history(symbol)
    if len(history) < 30:
        return {"symbol": symbol, "result": "Not enough price history for technical analysis."}
    index, index_name = _benchmark(symbol)
    try:
        market = yahoo.price_history(index)
    except Exception:
        market = []
    risk = portfolio.analyse([{"symbol": symbol, "weight": 1}], {symbol: history}, {}, market or None)
    year = [p["close"] for p in history[-252:]]
    src = sources.add("Yahoo Finance price history", f"https://finance.yahoo.com/quote/{yahoo.yahoo_ticker(symbol)}/history",
                      f"{symbol}: daily closes", f"{history[0]['date']} to {history[-1]['date']}")
    eng = sources.add("FinSight technicals engine", None, f"{symbol}: trend, returns, volatility and beta")
    return {
        "symbol": symbol,
        "last_close": {"source": src, "date": history[-1]["date"], "close": history[-1]["close"],
                       "high_52w": max(year), "low_52w": min(year)},
        "indicators": {"source": eng, **technicals.summarize(history, "$" if sec.is_us(symbol) else "₹"),
                       **technicals.period_returns(history),
                       "beta_1y": risk.get("beta"), "beta_against": index_name if risk.get("beta") is not None else None},
        "note": "Describes past price behaviour; it does not predict future prices.",
    }


def _portfolio_risk(args, sources: Sources):
    holdings = [{"symbol": yahoo.normalize_symbol(h["symbol"]), "weight": float(h["weight"])} for h in args["holdings"][:15]]
    merged: dict[str, float] = {}
    for h in holdings:                       # the same stock listed twice counts once, with both weights
        merged[h["symbol"]] = merged.get(h["symbol"], 0.0) + h["weight"]
    holdings = [{"symbol": s, "weight": w} for s, w in merged.items()]
    histories, sectors = {}, {}
    for h in holdings:
        try:
            histories[h["symbol"]] = yahoo.price_history(h["symbol"])
        except Exception:
            histories[h["symbol"]] = []
        try:
            sectors[h["symbol"]] = yahoo.profile(h["symbol"]).get("sector")
        except Exception:
            sectors[h["symbol"]] = None
    index, index_name = _benchmark(holdings[0]["symbol"])
    if any(sec.is_us(h["symbol"]) != sec.is_us(holdings[0]["symbol"]) for h in holdings):
        market = None   # Indian and US stocks: no single benchmark fits
    else:
        try:
            market = yahoo.price_history(index)
        except Exception:
            market = None
    result = portfolio.analyse(holdings, histories, sectors, market)
    period = result.get("period")
    src = sources.add("Yahoo Finance price history", None, "daily closes for " + ", ".join(merged),
                      f"{period['from']} to {period['to']}" if period else None)
    eng = sources.add("FinSight portfolio engine", None, "portfolio risk for " + ", ".join(merged))
    return {"source": eng, "prices_source": src, **result,
            "benchmark": index_name if result.get("beta") is not None else None}


def _calculate(args, sources: Sources):
    op, v = args["operation"], args["values"]
    need = {"cagr": 3, "percent_change": 2, "ratio": 2, "difference": 2}
    if op in need and len(v) != need[op]:
        raise ValueError(f"{op} needs exactly {need[op]} values")
    if not v:
        raise ValueError("values is empty")
    if op == "cagr":
        result = fundamentals.cagr(v[0], v[1], int(v[2]))
        if result is None:
            raise ValueError("CAGR is undefined when either value is zero or negative")
    elif op == "percent_change":
        if v[0] == 0:
            raise ValueError("percent change from zero is undefined")
        result = (v[1] - v[0]) / abs(v[0]) * 100
    elif op == "ratio":
        if v[1] == 0:
            raise ValueError("division by zero")
        result = v[0] / v[1]
    elif op == "difference":
        result = v[0] - v[1]
    elif op == "sum":
        result = sum(v)
    else:
        result = sum(v) / len(v)
    sid = sources.add("FinSight calculator", None, f"{args['label']}: {op}({', '.join(map(str, v))})")
    return {"source": sid, "label": args["label"], "operation": op, "inputs": v, "result": result}


HANDLERS = {
    "search_company": lambda args, sources: {"results": yahoo.search(args["query"])},
    "get_company_snapshot": _snapshot,
    "get_financials": _financials,
    "get_valuation": _valuation,
    "get_news": _news,
    "get_announcements": _announcements,
    "search_documents": _search_documents,
    "compare_companies": _compare,
    "run_screen": _screen,
    "get_ipo_data": _ipo_data,
    "get_technicals": _technicals,
    "portfolio_risk": _portfolio_risk,
    "calculate": _calculate,
}


def run_tool(name: str, args: dict, sources: Sources) -> tuple[str, bool]:
    """Returns (json_text, is_error). Errors go back to the model so it can recover or say data is missing."""
    try:
        return json.dumps(_round(HANDLERS[name](args, sources)), ensure_ascii=False, separators=(",", ":")), False
    except LookupError:
        return json.dumps({"error": f"No listed company found for {args.get('symbol')}. Try search_company."}), True
    except (KeyError, ValueError, TypeError) as e:
        return json.dumps({"error": f"Invalid input: {e}"}), True
    except Exception as e:  # data provider outage etc.
        return json.dumps({"error": f"Data unavailable: {e}"}), True
