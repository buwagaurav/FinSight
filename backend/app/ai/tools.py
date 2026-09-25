"""Tools the research assistant can call. Each wraps the deterministic engine; none of them let the
model invent data. Every result is tagged with source ids ("S1", "S2", ...) the answer must cite.
"""
import json
import math
import threading

from app import research, screener
from app.analytics import fundamentals
from app.providers import nse, yahoo

SYMBOL = {"type": "string", "description": "NSE symbol such as TCS or RELIANCE.NS (use search_company if unsure)."}

TOOLS = [
    {
        "name": "search_company",
        "description": "Find NSE/BSE listed companies by name. Returns symbols to use with the other tools.",
        "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    },
    {
        "name": "get_company_snapshot",
        "description": "Price, ratios, FinSight scores with reasons, trend, CAGR and data warnings for a company.",
        "input_schema": {"type": "object", "properties": {"symbol": SYMBOL}, "required": ["symbol"]},
    },
    {
        "name": "get_financials",
        "description": "Annual statements by fiscal year (₹ Cr; EPS ₹) with margins, ROE, ROCE, D/E, cash flow and YoY growth.",
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
        "description": "Latest official NSE filings by a company (results, dividends, orders, acquisitions...).",
        "input_schema": {"type": "object", "properties": {"symbol": SYMBOL}, "required": ["symbol"]},
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
        "description": "Screen all NSE stocks with numeric filters (percent fields in %, market cap in ₹ Cr).",
        "input_schema": {
            "type": "object",
            "properties": {
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


class Sources:
    """Registry of everything the assistant has looked at, so every claim can point to where it came from."""

    def __init__(self):
        self.items: list[dict] = []
        self._lock = threading.Lock()  # agents in the multi-agent report share one registry

    def add(self, name: str, url: str | None, detail: str) -> str:
        with self._lock:
            for s in self.items:
                if (s["name"], s["url"], s["detail"]) == (name, url, detail):
                    return s["id"]
            sid = f"S{len(self.items) + 1}"
            self.items.append({"id": sid, "name": name, "url": url, "detail": detail})
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


def _snapshot(args, sources: Sources):
    r = research.company_report(args["symbol"])
    p = r["profile"]
    name = _company_name(r)
    src_quote = sources.add("Yahoo Finance quote", p["source"]["url"], f"{name}: price and ratios")
    src_fin = sources.add(r["financials"]["source"]["name"], r["financials"]["source"]["url"], f"{name}: annual statements")
    src_engine = sources.add("FinSight scoring engine", None, f"{name}: rule-based scores ({r['scores']['method']})")
    keep = ["symbol", "name", "sector", "industry", "price", "change_pct", "market_cap_cr", "week52_high", "week52_low",
            "pe", "pb", "roe_ttm_pct", "debt_to_equity_ttm", "dividend_yield_pct", "promoter_holding_pct",
            "institutional_holding_pct", "trailing_eps"]
    s = r["scores"]
    return {
        "profile": {"source": src_quote, **{k: p[k] for k in keep}},
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
    src = sources.add(r["financials"]["source"]["name"], r["financials"]["source"]["url"], f"{_company_name(r)}: annual statements")
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
    for a in nse.announcements(args["symbol"], 25):
        if a["routine"]:
            continue
        sid = sources.add("NSE filing", a["pdf_url"], f"{a['company']}: {a['category']} ({(a['published'] or '')[:10]})")
        items.append({"source": sid, "date": (a["published"] or "")[:10], "category": a["category"], "text": a["text"][:220]})
    return {"announcements": items[:8], "note": "Routine procedural filings are omitted."}


def _compare(args, sources: Sources):
    symbols = args["symbols"][:6]
    stored = screener.lookup(symbols)
    rows = []
    for sym in symbols:
        row = stored.get(sym.split(".")[0].upper())
        if row is None:  # not loaded yet: compute it live with the same engine
            try:
                r = research.company_report(sym)
                row = {"symbol": r["profile"]["symbol"],
                       **{k: v for k, v in screener.metrics_row(r["profile"], r["financials"]["years"]).items() if k != "yahoo_symbol"}}
            except LookupError:
                rows.append({"symbol": sym, "error": "not found"})
                continue
        sid = sources.add("Company filings via Yahoo Finance", f"https://finance.yahoo.com/quote/{row['symbol']}",
                          f"{row['name']} ({row['symbol']}): metrics")
        rows.append({"source": sid, **row})
    return {"companies": rows, "note": "ROCE and debt/equity are not computed for banks and financials."}


def _screen(args, sources: Sources):
    result = screener.run(args["filters"], args.get("sort") or "market_cap_cr", True, args.get("sectors"))
    sid = sources.add("FinSight screener", None, f"{result['universe']}: {result['query']}")
    keep = ("symbol", "name", "market_cap_cr", "pe", "roe_pct", "debt_to_equity", "profit_cagr_pct")
    rows = [{k: r[k] for k in keep} for r in result["rows"][:10]]
    return {"source": sid, "query": result["query"], "count": result["count"], "top_10": rows}


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
    "compare_companies": _compare,
    "run_screen": _screen,
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
