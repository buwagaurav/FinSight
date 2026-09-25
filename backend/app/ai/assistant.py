"""FinSight research assistant: Claude plans and explains, the analytics engine calculates.

Flow per question:
  1. Claude calls tools (company data, statements, valuation, news, screener, calculator).
  2. Claude writes a structured answer citing source ids like [S3].
  3. verify.unverified_numbers() checks every figure against the tool outputs. If any figure cannot be
     traced, Claude gets one chance to fix it; whatever remains is reported to the user, never hidden.
"""
from app.ai import llm
from app.ai import tools as T


SYSTEM = """You are FinSight's research assistant for Indian retail investors (NSE/BSE stocks and IPOs).
Rules:
- Every figure must come from data in this conversation or a tool result; never from memory. Use the calculate
  tool for any arithmetic the data doesn't already contain.
- Cite the source id right after each fact, e.g. "net profit ₹49,210 Cr [S2]".
- If data is already provided in the message, use it; call tools only for what is missing, and request everything
  you need in ONE turn (several tool calls at once), not one tool per turn.
- Say plainly when data is missing. Round sensibly (48.72 -> 48.7%). Amounts are ₹ crore; "L Cr" = lakh crore.
- Plain language; briefly define jargon. No buy/sell advice or price targets; for the future, describe scenarios
  and what to monitor. GMP is unofficial. Mention data_checks warnings when relevant.
Answer in Markdown, 80-200 words: **Short answer** (2-3 sentences), then key figures as short bullets, then
**Risks** (1-2 bullets). Add **What to watch** only if useful. No sources list. Write the whole answer in your final
message, after all tool calls."""

PREFETCH = [("get_company_snapshot", {}), ("get_financials", {})]


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
    if symbol:
        data, preloaded = _context_for(symbol, sources)
        content = (f"The user is viewing {symbol}; assume the question is about it unless it says otherwise.\n"
                   f"Data already loaded:\n{data}\n\nQuestion: {question}")
    messages.append({"role": "user", "content": content})
    try:
        run = llm.run_agent(SYSTEM, messages, None, sources, question, task="assistant", preloaded=preloaded)
    except llm.AIRefused:
        run = {"answer": "I can't help with that request. Try asking about a company's financials, valuation or news.",
               "calls": [], "unverified": [], "misattributed": [], "model": llm.model_spec("assistant"), "usage": {}}
    return {**_result(run["answer"], sources, run["calls"], run["unverified"], run["model"], run["misattributed"]),
            "usage": run["usage"]}


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
