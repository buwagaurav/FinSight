"""Conversation memory for Ask FinSight (the idea from ConvFinQA: follow-ups refer back to earlier turns).

After each answer the server returns a small state: the companies, metric and period being discussed, the last
calculation, and the data the answer cited (with its source records). The browser sends it back with the next
question, so "What about FY24?" and "What was the percentage change?" resolve against the earlier turn, and figures
carried over from it still pass the source checks. The server stays stateless.

The carried data is signed: data the server didn't produce is dropped, so a client can't make its own figures look
verified. Topic hints (company, metric, period) are unsigned; they only steer the model, never the checks.
"""
import hashlib
import hmac
import json
import os
import re
import secrets

EVIDENCE_CHARS = 12000      # carried tool data per turn: enough for statements + a snapshot, small enough to resend
MAX_SOURCES = 40
_SECRET = (os.environ.get("FINSIGHT_API_JWT_SECRET") or secrets.token_hex(32)).encode()

METRICS = {
    "revenue": r"revenue|sales|top ?line|turnover",
    "net profit": r"net profit|profit after tax|\bpat\b|net income|earnings|bottom ?line",
    "operating profit": r"operating profit|\bebit\b",
    "EBITDA": r"\bebitda\b",
    "operating margin": r"operating margin|ebit margin|ebitda margin",
    "net margin": r"net margin|profit margin",
    "EPS": r"\beps\b|earnings per share",
    "ROE": r"\broe\b|return on equity",
    "ROCE": r"\broce\b|return on capital",
    "debt to equity": r"debt[- ]to[- ]equity|\bd/?e\b|leverage",
    "debt": r"\bdebt\b|borrowings",
    "free cash flow": r"free cash ?flow|\bfcf\b",
    "operating cash flow": r"operating cash ?flow|cash from operations",
    "P/E": r"\bp/?e\b|price[- ]to[- ]earnings",
    "P/B": r"\bp/?b\b|price[- ]to[- ]book",
    "dividend": r"dividend",
    "share price": r"share price|stock price|\bprice\b",
    "market cap": r"market cap",
}
_METRICS = [(label, re.compile(p, re.IGNORECASE)) for label, p in METRICS.items()]
PERIOD = re.compile(r"\b(?:(Q[1-4])\s*)?FY\s?'?(\d{4}|\d{2})\b|\b(?:fiscal|financial) (?:year )?(\d{4})\b", re.IGNORECASE)
COMPANY_DETAIL = re.compile(r"^(.+) \(([A-Z0-9&.\-]+)\): ")   # "Infosys Limited (INFY.NS): annual statements"
SOURCE_REF = re.compile(r'"(?:prices_)?source":\s*"(S\d+)"')


def _sign(evidence: list[str], sources: list[dict]) -> str:
    body = json.dumps([evidence, sources], sort_keys=True, ensure_ascii=False).encode()
    return hmac.new(_SECRET, body, hashlib.sha256).hexdigest()


def empty() -> dict:
    return {"companies": [], "metric": None, "period": None, "last_calculation": None, "evidence": [], "sources": [],
            "signature": None}


def load(state: dict | None) -> dict:
    """The state sent by the browser, trimmed to its known fields; carried data is kept only if its signature holds."""
    out = empty()
    if not isinstance(state, dict):
        return out
    out["companies"] = [c for c in state.get("companies") or [] if isinstance(c, dict) and isinstance(c.get("symbol"), str)][:6]
    out["companies"] = [{"symbol": c["symbol"][:20], "name": str(c.get("name") or c["symbol"])[:80]} for c in out["companies"]]
    for key in ("metric", "period"):
        out[key] = state[key][:40] if isinstance(state.get(key), str) else None
    evidence, sources = state.get("evidence") or [], state.get("sources") or []
    if (isinstance(evidence, list) and isinstance(sources, list) and isinstance(state.get("signature"), str)
            and hmac.compare_digest(state["signature"], _sign(evidence, sources))):
        out.update(evidence=evidence, sources=sources, signature=state["signature"],
                   last_calculation=state.get("last_calculation"))
    return out


def period_label(text: str) -> str | None:
    """The last fiscal period named in the text, as FinSight labels it: "FY2025" -> "FY25", "Q2 FY26" stays."""
    found = None
    for m in PERIOD.finditer(text):
        year = m.group(2) or m.group(3)
        found = (f"{m.group(1).upper()} " if m.group(1) else "") + f"FY{year[-2:]}"
    return found


def metric_label(text: str) -> str | None:
    hits = [(m.start(), label) for label, p in _METRICS if (m := p.search(text))]
    return min(hits)[1] if hits else None   # the first metric the question names


def context_note(state: dict, page_symbol: str | None) -> str:
    """What earlier turns established, written for the model."""
    parts = []
    if state["companies"]:
        names = ", ".join(f"{c['name']} ({c['symbol']})" for c in state["companies"])
        parts.append(f"company: {names}" if len(state["companies"]) == 1 else f"companies: {names}")
    if state["metric"]:
        parts.append(f"metric: {state['metric']}")
    if state["period"]:
        parts.append(f"period: {state['period']}")
    if state["last_calculation"]:
        c = state["last_calculation"]
        parts.append(f"last calculation: {c.get('label')} = {c.get('result')} [{c.get('source')}]")
    if not parts:
        return ""
    note = ("Earlier in this conversation (" + "; ".join(parts) + "). Resolve follow-ups such as \"what about FY24?\", "
            "\"and its margin?\" or \"the percentage change\" against this, unless the new question names something else.")
    if page_symbol and state["companies"] and page_symbol not in {c["symbol"] for c in state["companies"]}:
        note += f" The user is now viewing {page_symbol}; if the question is ambiguous, say which company you mean."
    if state["evidence"]:
        note += ("\nData from earlier turns (cite it with these source ids):\n" + "\n".join(state["evidence"]))
    return note


def update(state: dict, question: str, answer: str, page_symbol: str | None, outputs: list[str],
           sources: list[dict], calls: list[dict]) -> dict:
    """The state after this answer: topic from the question (falling back to the earlier turn), and the data the
    answer cited, so the next turn can use it."""
    cited = {sid for group in re.findall(r"\[(S\d+(?:\s*,\s*S\d+)*)\]", answer) for sid in re.findall(r"S\d+", group)}
    companies: list[dict] = []
    for s in sources:
        m = COMPANY_DETAIL.match(s.get("detail") or "")
        if s["id"] in cited and m and m.group(2) not in {c["symbol"] for c in companies}:
            companies.append({"symbol": m.group(2), "name": m.group(1)})
    if not companies:
        asked = [c["input"].get("symbol") for c in calls if c["input"].get("symbol")]
        companies = [{"symbol": s, "name": s} for s in dict.fromkeys(asked)] or \
            ([{"symbol": page_symbol, "name": page_symbol}] if page_symbol else state["companies"])

    kept, size = [], 0
    for out in dict.fromkeys(outputs):           # same data loaded twice counts once
        refs = set(SOURCE_REF.findall(out))
        if refs & cited and size + len(out) <= EVIDENCE_CHARS:
            kept.append(out)
            size += len(out)
    used = {sid for out in kept for sid in SOURCE_REF.findall(out)} | cited
    carried = [s for s in sources if s["id"] in used][:MAX_SOURCES]

    calculation = state["last_calculation"]
    for out in outputs:
        try:
            data = json.loads(out)
        except ValueError:
            continue
        if isinstance(data, dict) and "operation" in data and "result" in data:
            calculation = {k: data.get(k) for k in ("source", "label", "operation", "inputs", "result")}

    return {"companies": companies[:6], "metric": metric_label(question) or state["metric"],
            "period": period_label(question) or state["period"], "last_calculation": calculation,
            "evidence": kept, "sources": carried, "signature": _sign(kept, carried)}


FOLLOW_UPS = {
    "company_research": ["How have revenue and profit grown over the last 4 years?",
                         "Is {c} expensive compared with its own history?", "Compare {c} with its closest peers"],
    "valuation": ["What would make the bear case come true?", "Compare {c}'s P/E with its peers",
                  "What are the biggest risks right now?"],
    "company_comparison": ["Which has the stronger balance sheet?", "Which has grown faster over 4 years?",
                           "Which is cheaper on P/E, and why?"],
    "filing_question": ["What did the latest results announcement say?", "What risks does the annual report mention?"],
    "ipo_research": ["What are the price band, lot size and minimum investment?",
                     "What does the GMP suggest, and why is it unofficial?"],
    "technical_analysis": ["How volatile has {c} been over the last year?", "How far is it from its 52-week high?"],
    "portfolio_risk": ["Which holding adds the most risk?", "How would adding a bank stock change the risk?"],
    "stock_screening": ["Compare the top 3 results", "Which of these has the lowest debt?"],
}


def follow_ups(intent: str, state: dict) -> list[str]:
    """Next questions to offer, worded for what was just discussed."""
    company = state["companies"][0]["name"] if len(state["companies"]) == 1 else None
    if intent == "general_finance" and state["metric"]:
        m = state["metric"]
        return ([f"What is {company}'s {m}?"] if company else []) + \
            [f"Which large companies have a strong {m}?", f"How does {m} differ across industries?"]
    options = FOLLOW_UPS.get(intent, [])
    if company:
        return [q.format(c=company.split(" Limited")[0]) for q in options][:3]
    return [q for q in options if "{c}" not in q][:3]
