"""Multi-agent research report (FinRobot-style) orchestrated with LangGraph.

    START ─┬─ fundamentals analyst ─┐
           ├─ valuation analyst ────┼─▶ risk reviewer ─▶ writer ─▶ checker ─▶ END
           └─ filings & news analyst┘                      ▲          │
                                                           └──────────┘ figures not traceable (max 2 rewrites)

Analysts run in parallel, each with only the tools its job needs. Every analyst's answer passes the
numeric grounding check on its own; the writer may only reuse figures the analysts retrieved, and the
checker verifies the final report against every tool output from the whole run.
"""
import operator
import re
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from app import db
from app.ai import llm
from app.ai import tools as T
from app.ai.verify import misattributed, unverified_numbers

MAX_REWRITES = 2

COMMON = """You are one analyst on FinSight's research team, covering {company} ({symbol}) for Indian retail investors.
Use tools for every figure and cite source ids like [S3] right after each fact. Use the calculate tool for any arithmetic.
Do not give buy/sell advice or price targets. Write Markdown under 250 words, no top-level heading."""

ANALYSTS = {
    "fundamentals": {
        "title": "Fundamentals analyst",
        "tools": ["get_company_snapshot", "get_financials", "calculate"],
        "brief": "Assess business quality: revenue and profit growth, margins, ROE/ROCE, balance sheet strength, and "
                 "whether profits convert to cash. Flag any data_checks warnings.",
    },
    "valuation": {
        "title": "Valuation analyst",
        "tools": ["get_valuation", "get_company_snapshot", "compare_companies", "search_company", "calculate"],
        "brief": "Assess valuation: current multiples versus the company's own history and 2-4 close listed peers "
                 "(find them with search_company if needed), plus FinSight's bear/base/bull scenarios and their "
                 "assumptions. Mention the price trend.",
    },
    "developments": {
        "title": "Filings & news analyst",
        "tools": ["get_announcements", "get_news"],
        "brief": "Summarise the material recent developments from official NSE filings first, then news. For each: "
                 "what happened, why it matters, and whether it is positive, negative or uncertain. Ignore routine items.",
    },
}

REVIEWER = """You are the risk reviewer on FinSight's research team for {company} ({symbol}). Three analysts wrote the
drafts below. Challenge them: find risks they missed, claims that look weakly supported, contradictions between
sections, and data limitations. You may use tools to check facts; cite source ids. Output a bullet list under 200 words.
Do not rewrite the drafts."""

WRITER = """You are the editor of FinSight's research report on {company} ({symbol}) for Indian retail investors.
Combine the analyst drafts and the risk review into one report. Rules:
- Use ONLY figures that appear in the drafts or review, with their source ids ([S1] etc.) kept next to them.
  Never introduce a new number or a new source id.
- No buy/sell advice and no price targets; describe scenarios and what to monitor.
- Plain language; define jargon briefly.
Structure (Markdown, 600-900 words):
## Summary  (3-4 sentences: the FinSight view in plain words)
## Business quality and growth
## Valuation
## Recent developments
## Key risks  (integrate the risk review)
## What to monitor
## Data limitations"""


@dataclass
class Ctx:
    sources: T.Sources
    on_progress: Callable[[str, str], None] = lambda node, status: None  # noqa: E731


def _merge(a: dict, b: dict) -> dict:
    return {**a, **b}


class ReportState(TypedDict, total=False):
    symbol: str
    company: str
    sections: Annotated[dict, _merge]
    outputs: Annotated[list, operator.add]
    calls: Annotated[list, operator.add]
    review: str
    report: str
    feedback: str
    unverified: list
    attempts: int


def _analyst(key: str):
    spec = ANALYSTS[key]

    def node(state: ReportState, runtime: Runtime[Ctx]):
        runtime.context.on_progress(key, "running")
        system = COMMON.format(company=state["company"], symbol=state["symbol"]) + "\n\nYour job: " + spec["brief"]
        run = llm.run_agent(system, [{"role": "user", "content": f"Write your section on {state['company']}."}],
                            spec["tools"], runtime.context.sources, max_rounds=4, task="report")
        runtime.context.on_progress(key, "done")
        return {"sections": {key: run["answer"]}, "outputs": run["outputs"],
                "calls": [{**c, "agent": spec["title"]} for c in run["calls"]]}

    return node


def _drafts(state: ReportState) -> str:
    return "\n\n".join(f"### {ANALYSTS[k]['title']}\n{v}" for k, v in state["sections"].items())


def reviewer(state: ReportState, runtime: Runtime[Ctx]):
    runtime.context.on_progress("review", "running")
    run = llm.run_agent(REVIEWER.format(company=state["company"], symbol=state["symbol"]),
                        [{"role": "user", "content": _drafts(state)}],
                        ["get_company_snapshot", "get_financials", "calculate"], runtime.context.sources, max_rounds=3,
                        task="report")
    runtime.context.on_progress("review", "done")
    return {"review": run["answer"], "outputs": run["outputs"],
            "calls": [{**c, "agent": "Risk reviewer"} for c in run["calls"]]}


def writer(state: ReportState, runtime: Runtime[Ctx]):
    runtime.context.on_progress("write", "running")
    content = f"{_drafts(state)}\n\n### Risk review\n{state['review']}"
    if state.get("feedback"):
        content += f"\n\n### Fix required\n{state['feedback']}\n\nPrevious version:\n{state['report']}"
    text = llm.complete(WRITER.format(company=state["company"], symbol=state["symbol"]), content, task="report").text
    runtime.context.on_progress("write", "done")
    return {"report": text, "attempts": state.get("attempts", 0) + 1}


def checker(state: ReportState, runtime: Runtime[Ctx]):
    known_ids = {s["id"] for s in runtime.context.sources.items}
    cited = {s["id"] for s in llm.cited_sources(state["report"], runtime.context.sources)}
    bad_ids = sorted(set(re.findall(r"S\d+", " ".join(re.findall(r"\[(S\d+(?:\s*,\s*S\d+)*)\]", state["report"])))) - known_ids)
    runtime.context.on_progress("check", "running")
    missing = unverified_numbers(state["report"], state["outputs"])
    wrong = misattributed(state["report"], state["outputs"])
    problems = []
    if wrong:
        problems.append("These figures are cited to a source that does not contain them: " + ", ".join(wrong) + ". Fix the citation to match the drafts.")
    if missing:
        problems.append("These figures do not appear in any analyst's data: " + ", ".join(missing) + ". Remove them or use the drafts' figures.")
    if bad_ids:
        problems.append("These source ids do not exist: " + ", ".join(bad_ids) + ". Use only ids from the drafts.")
    if not cited:
        problems.append("The report cites no sources. Keep the drafts' [S#] citations next to each figure.")
    runtime.context.on_progress("check", "done" if not problems else "retry")
    return {"unverified": missing + wrong, "feedback": " ".join(problems)}


def _after_check(state: ReportState):
    return "writer" if state["feedback"] and state["attempts"] <= MAX_REWRITES else END


def build_graph():
    g = StateGraph(ReportState, context_schema=Ctx)
    for key in ANALYSTS:
        g.add_node(key, _analyst(key))
        g.add_edge(START, key)
    g.add_node("reviewer", reviewer)
    g.add_node("writer", writer)
    g.add_node("checker", checker)
    g.add_edge(list(ANALYSTS), "reviewer")
    g.add_edge("reviewer", "writer")
    g.add_edge("writer", "checker")
    g.add_conditional_edges("checker", _after_check, ["writer", END])
    return g.compile()


GRAPH = build_graph()


def generate(symbol: str, company: str, on_progress=lambda node, status: None) -> dict:
    started = time.time()
    ctx = Ctx(sources=T.Sources(), on_progress=on_progress)
    state = GRAPH.invoke({"symbol": symbol, "company": company, "attempts": 0}, context=ctx)
    return {
        "symbol": symbol,
        "company": company,
        "report": state["report"],
        "sections": state["sections"],
        "review": state["review"],
        "sources": llm.cited_sources(state["report"], ctx.sources),
        "all_sources": ctx.sources.items,
        "verification": {"passed": not state["unverified"] and not state.get("feedback"),
                         "unverified": state["unverified"], "problems": state.get("feedback") or "",
                         "rewrites": state["attempts"] - 1},
        "tool_calls": state["calls"],
        "model": llm.model_spec("report"),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "duration_s": round(time.time() - started),
    }


# --- background jobs: a report takes a few minutes, so the API starts it and the page polls ---

STEPS = [("fundamentals", "Fundamentals analyst"), ("valuation", "Valuation analyst"),
         ("developments", "Filings & news analyst"), ("review", "Risk reviewer"), ("write", "Writing the report"),
         ("check", "Checking every figure")]
_jobs: dict[str, dict] = {}


def start_job(symbol: str, company: str) -> str:
    llm.adapter("report")  # fail fast with a clear message if the report model has no credentials
    job_id = uuid.uuid4().hex[:12]
    job = {"id": job_id, "symbol": symbol, "status": "running", "error": None, "result": None,
           "steps": [{"key": k, "label": label, "status": "pending"} for k, label in STEPS]}
    _jobs[job_id] = job

    def progress(node: str, status: str):
        for s in job["steps"]:
            if s["key"] == node:
                s["status"] = status

    def run():
        try:
            result = generate(symbol, company, progress)
            db.execute("""INSERT INTO reports (symbol, data, created_at) VALUES (%s, %s, now())
                          ON CONFLICT (symbol) DO UPDATE SET data = EXCLUDED.data, created_at = now()""",
                       (symbol, db.jsonb(result)))
            job.update(status="done", result=result)
        except Exception as e:  # surfaced to the page, which shows it instead of spinning forever
            job.update(status="error", error=str(e))

    threading.Thread(target=run, daemon=True).start()
    return job_id


def get_job(job_id: str) -> dict | None:
    return _jobs.get(job_id)


def latest(symbol: str) -> dict | None:
    row = db.fetch_one("SELECT data FROM reports WHERE symbol = %s", (symbol,))
    return row["data"] if row else None
