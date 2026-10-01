"""FinSight research assistant: Claude plans and explains, the analytics engine calculates.

Flow per question:
  0. guardrail: plainly off-topic questions are refused before any model call, and the model follows the scope
     rules in skills/finance-guardrail/SKILL.md for the rest.
  1. intent.classify() picks the question type (company research, screening, IPO, portfolio risk...), which decides
     the tools the model gets and the extra rules it follows.
  2. Claude calls tools (company data, statements, valuation, news, filings, IPOs, technicals, screener, calculator).
  3. Claude writes a structured answer citing source ids like [S3].
  4. verify.unverified_numbers() checks every figure against the tool outputs. If any figure cannot be
     traced, Claude gets one chance to fix it; whatever remains is reported to the user, never hidden.
  5. Deterministic warnings (stale data, mixed periods, unofficial sources, failed lookups) go with the answer.
"""
import json
import os
from datetime import datetime, timedelta, timezone

from app.ai import guardrail
from app.ai import intent as I
from app.ai import llm
from app.ai import tools as T

DISCLAIMER = "This is research assistance, not investment advice."
STALE_GMP = timedelta(days=3)
# Look-ups stop and the model must answer once less than 5 s of this budget remain; writing the answer takes another
# 3-5 s, so 8 s keeps most answers under 10 s (measured with deepseek-flash: 2.7 s for a concept, 5-11 s with data
# at a 10 s budget).
BUDGET_SECONDS = float(os.environ.get("FINSIGHT_ASSISTANT_SECONDS", "8"))
TOOL_ROUNDS = 2   # data look-ups before the model must answer; most questions need one

CONCEPT = """Explain the finance term or concept the user asked about, for a retail investor, in 60-150 words of
Markdown: a one-sentence definition, the formula if there is one, how to read it (what high or low means and why it
depends on the industry or context), and one common pitfall. Any example must be a hypothetical one with round
numbers, labelled "for example". Don't state any real company's or market's figures; if the user is on a company
page, end by saying the company's own figure is on its FinSight page. No buy/sell advice."""


SCOPE = guardrail.skill_text()
SYSTEM = """You are FinSight's research assistant for Indian retail investors (NSE/BSE stocks, IPOs and US-listed stocks).
Rules:
- Every figure must come from data in this conversation or a tool result; never from memory. Use the calculate
  tool for any arithmetic the data doesn't already contain.
- Cite the source id right after each fact, e.g. "net profit ₹49,210 Cr [S2]".
- If data is already provided in the message, use it; call tools only for what is missing, and request everything
  you need in ONE turn (several tool calls at once), not one tool per turn.
- For what the company or management said (strategy, reasons, guidance, risks), use search_documents and quote
  the exact words in "double quotes" followed by the citation, e.g. "attrition was 13.3%" [S4].
- Say plainly when data is missing. Round sensibly (48.72 -> 48.7%). Amounts are ₹ crore for Indian companies
  ("L Cr" = lakh crore) and $ million for US companies (see unit fields); keep each company in its own currency.
- Plain language; briefly define jargon. No buy/sell instructions, price targets or promised returns; for the
  future, describe scenarios and what to monitor. GMP is unofficial: always say so. Mention data_checks warnings
  when relevant.
- Say which period each key figure covers (FY25, trailing twelve months, as of a date). Don't combine or compare
  figures from different periods without saying so. If sources disagree, give both and say they differ.
Answer in Markdown, 80-200 words: **Short answer** (2-3 sentences), then key figures as short bullets, then
**Risks** (1-2 bullets). Add **What to watch** only if useful. No sources list. Write the whole answer in your final
message, after all tool calls."""

PREFETCH = [("get_company_snapshot", {}), ("get_financials", {})]
# Intents where the company in view is usually the subject, so its data is sent up front
PREFETCH_FOR = {"company_research", "company_comparison", "valuation", "filing_question", "technical_analysis"}


def _context_for(symbol: str, sources: T.Sources) -> tuple[str, list[str]]:
    """The company's key data, sent with the question so most answers need no extra tool round."""
    blocks, outputs = [], []
    for name, args in PREFETCH:
        out, err = T.run_tool(name, {**args, "symbol": symbol}, sources)
        if not err:
            blocks.append(f"{name}: {out}")
            outputs.append(out)
    return "\n".join(blocks), outputs


def _history(history: list[dict] | None) -> list[dict]:
    """Last two exchanges only, with long earlier answers shortened: each one is re-sent on every round."""
    turns = (history or [])[-4:]
    return [{"role": m["role"], "content": m["content"] if m["role"] == "user" or len(m["content"]) < 600
             else m["content"][:600] + " …"} for m in turns]


def ask(question: str, symbol: str | None = None, history: list[dict] | None = None) -> dict:
    sources = T.Sources()
    messages = _history(history)
    preloaded: list[str] = []
    content = question
    kind = I.classify(question, symbol)
    if I.is_concept(question, symbol):
        return _concept(question, messages, sources)
    if symbol:
        content = f"The user is viewing {symbol}; assume the question is about it unless it says otherwise.\n"
        if kind in PREFETCH_FOR:
            data, preloaded = _context_for(symbol, sources)
            content += f"Data already loaded:\n{data}\n"
        content += f"\nQuestion: {question}"
    messages.append({"role": "user", "content": content})
    system = f"{SCOPE}\n\n{SYSTEM}\nThis is a {kind.replace('_', ' ')} question. {I.GUIDANCE[kind]}"
    try:
        run = llm.run_agent(system, messages, I.tools_for(kind, symbol), sources, question, task="assistant",
                            preloaded=preloaded, max_rounds=TOOL_ROUNDS, budget=BUDGET_SECONDS)
    except llm.AIRefused:
        run = {"answer": "I can't help with that request. Try asking about a company's financials, valuation or news.",
               "calls": [], "unverified": [], "misattributed": [], "model": llm.model_spec("assistant"), "usage": {}}
    if guardrail.is_refusal(run["answer"]):
        return {**out_of_scope(), "model": run["model"], "usage": run["usage"]}
    result = _result(run["answer"], sources, run["calls"], run["unverified"], run["model"], run["misattributed"])
    v = result["verification"]
    v["unsupported_quotes"], v["arithmetic"] = run.get("unsupported_quotes", []), run.get("arithmetic", [])
    if v["unsupported_quotes"] or v["arithmetic"]:
        v["passed"] = False
        v["note"] = "Some quotes or calculations could not be confirmed against their sources. Treat them with caution."
    return {**result, "intent": kind, "warnings": warnings(run.get("outputs", preloaded), result["sources"], run["calls"]),
            "data_timestamp": max((s["retrieved_at"] for s in sources.items), default=None),
            "disclaimer": DISCLAIMER, "usage": run["usage"]}


def _concept(question: str, messages: list[dict], sources: T.Sources) -> dict:
    """"What is ROE?": one quick model call with no tools or company data, so nothing to fetch or check."""
    messages.append({"role": "user", "content": question})
    try:
        run = llm.run_agent(f"{SCOPE}\n\n{CONCEPT}", messages, [], sources, question, task="assistant",
                            max_rounds=0, budget=BUDGET_SECONDS, verify=False)
    except llm.AIRefused:
        return out_of_scope()
    if guardrail.is_refusal(run["answer"]):
        return {**out_of_scope(), "model": run["model"], "usage": run["usage"]}
    return {"answer": run["answer"], "sources": [], "tool_calls": [], "intent": "general_finance", "warnings": [],
            "verification": {"passed": True, "applicable": False, "unverified": [], "misattributed": [],
                             "note": "A general explanation: no company data was used, so there are no figures to check."},
            "data_timestamp": None, "disclaimer": DISCLAIMER, "model": run["model"], "usage": run["usage"]}


def out_of_scope() -> dict:
    """The standard reply to a question outside finance, in the same shape as an answer."""
    return {"answer": guardrail.REFUSAL, "sources": [], "tool_calls": [], "intent": "out_of_scope", "warnings": [],
            "verification": {"passed": True, "unverified": [], "misattributed": [], "note": ""},
            "data_timestamp": None, "disclaimer": DISCLAIMER, "model": "guardrail", "usage": {}}


def _walk(node, key: str):
    """Every value stored under `key` anywhere in a parsed tool result."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key:
                yield v
            yield from _walk(v, key)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v, key)


def warnings(outputs: list[str], cited: list[dict], calls: list[dict], now: datetime | None = None) -> list[str]:
    """What the reader should know about the data behind the answer, worked out from the tool results themselves
    (not from the model): data-quality checks, stale or mixed-period data, unofficial sources, failed lookups."""
    now = now or datetime.now(timezone.utc)
    out: list[str] = []
    for text in outputs:
        try:
            data = json.loads(text)
        except ValueError:
            continue
        for checks in _walk(data, "data_checks"):
            out += checks
        for note in _walk(data, "note"):
            if isinstance(note, str) and "different fiscal years" in note:
                out.append(next(s for s in note.split(". ") if "different fiscal years" in s).rstrip(".") + ".")
        for ipos in _walk(data, "ipos"):
            for ipo in ipos:   # an old reading only matters while the IPO is still to list
                observed = (ipo.get("gmp_unofficial") or {}).get("observed_at")
                if ipo.get("status") not in ("Open", "Upcoming") or not observed:
                    continue
                age = now - datetime.fromisoformat(observed)
                if age > STALE_GMP:
                    out.append(f"The latest GMP reading for {ipo['name']} is {age.days} days old ({observed[:10]}); "
                               "grey-market prices move quickly.")
    if any(s["source_type"] == "unofficial" for s in cited):
        out.append("This answer uses grey-market premium (GMP) data, which is unofficial and unregulated.")
    failed = sorted({c["tool"].replace("_", " ") for c in calls if c["error"]})
    if failed:
        out.append(f"Some data could not be retrieved ({', '.join(failed)}); the answer may be incomplete.")
    return list(dict.fromkeys(out))   # drop repeats, keep order


def _result(answer: str, sources: T.Sources, calls: list[dict], missing: list[str], model: str,
            wrong: list[str] | None = None) -> dict:
    wrong = wrong or []
    return {
        "answer": answer,
        "sources": llm.cited_sources(answer, sources),
        "tool_calls": calls,
        "verification": {
            "passed": not missing and not wrong,
            "unverified": missing,
            "misattributed": wrong,
            "note": "Every figure was matched to the source it cites." if not (missing or wrong) else
                    "Some figures could not be matched to their cited FinSight data. Treat them with caution.",
        },
        "model": model,
    }
