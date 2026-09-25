import os
import threading
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")  # before app.ai reads its settings

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app import gmp, loader, research, screener
from app.ai import assistant, filings, llm, report, screen_nl
from app.providers import nse, yahoo

app = FastAPI(title="FinSight API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"], allow_methods=["*"], allow_headers=["*"])


_loader_stop = threading.Event()


@app.on_event("startup")
def start_background_loader():
    """Keep the database filling up and fresh while the API runs. Disable with FINSIGHT_BACKGROUND_LOADER=0."""
    if os.environ.get("FINSIGHT_BACKGROUND_LOADER", "1") != "0":
        threading.Thread(target=loader.run_forever, args=(_loader_stop,), daemon=True).start()


@app.on_event("shutdown")
def stop_background_loader():
    _loader_stop.set()


@app.get("/api/loader/status")
def loader_status():
    return loader.status()


@app.get("/api/search")
def search(q: str = Query(min_length=1)):
    return yahoo.search(q)


@app.get("/api/company/{symbol}")
def company(symbol: str):
    try:
        return research.company_report(symbol)
    except LookupError:
        raise HTTPException(404, f"No listed company found for {yahoo.normalize_symbol(symbol)}")


@app.get("/api/company/{symbol}/news")
def company_news(symbol: str):
    return yahoo.news(yahoo.normalize_symbol(symbol))


@app.get("/api/company/{symbol}/announcements")
def company_announcements(symbol: str, limit: int = Query(30, le=100)):
    try:
        rows = nse.announcements(symbol, limit)
    except Exception as e:
        raise HTTPException(502, f"NSE announcements unavailable: {e}")
    return [{**a, "summary": filings.cached(a["id"])} for a in rows]


@app.post("/api/company/{symbol}/announcements/{announcement_id}/summary")
def summarize_announcement(symbol: str, announcement_id: str):
    try:
        return filings.summarize(symbol, announcement_id)
    except llm.AIUnavailable as e:
        raise HTTPException(503, str(e))
    except llm.AIRefused as e:
        raise HTTPException(422, str(e))
    except LookupError as e:
        raise HTTPException(404, str(e))


@app.get("/api/ipos")
def ipos():
    try:
        rows = nse.current_ipos()
    except Exception as e:
        raise HTTPException(502, f"NSE IPO data unavailable: {e}")
    gmp.sync(rows)
    for r in rows:
        r["gmp"] = gmp.summary(r["symbol"], r["price_high"])
    return rows


@app.get("/api/ipos/{symbol}")
def ipo(symbol: str):
    match = next((r for r in ipos() if r["symbol"] == symbol.upper()), None)
    if not match:
        raise HTTPException(404, f"{symbol} is not in the current NSE IPO list")
    return match


class GmpEntry(BaseModel):
    gmp: float = Field(description="Grey-market premium in ₹ per share")
    source: str = Field(min_length=2)
    source_url: str | None = None
    observed_at: str | None = None


@app.post("/api/ipos/{symbol}/gmp")
def add_gmp(symbol: str, entry: GmpEntry):
    return gmp.add(symbol, entry.gmp, entry.source, entry.source_url, entry.observed_at)


class Filter(BaseModel):
    field: Literal[tuple(screener.FIELDS)]  # type: ignore[valid-type]
    op: Literal[">", ">=", "<", "<="]
    value: float


class ScreenRequest(BaseModel):
    filters: list[Filter] = []
    sectors: list[Literal[tuple(screener.SECTORS)]] = []  # type: ignore[valid-type]
    sort: str | None = "market_cap_cr"
    descending: bool = True


@app.get("/api/screener/fields")
def screener_fields():
    return screener.FIELDS


@app.get("/api/screener/sectors")
def screener_sectors():
    return screener.SECTORS


class NLScreenRequest(BaseModel):
    query: str = Field(min_length=3, max_length=500)


@app.post("/api/screener/parse")
def parse_screen(req: NLScreenRequest):
    try:
        return screen_nl.parse(req.query)
    except llm.AIUnavailable as e:
        raise HTTPException(503, str(e))
    except llm.AIRefused as e:
        raise HTTPException(422, str(e))


@app.post("/api/screener")
def run_screen(req: ScreenRequest):
    return screener.run([f.model_dump() for f in req.filters], req.sort, req.descending, req.sectors)


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=20000)


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    symbol: str | None = None
    history: list[ChatTurn] = []


@app.get("/api/ai/status")
def ai_status():
    tasks = llm.status()
    return {"configured": tasks["assistant"]["configured"], "model": tasks["assistant"]["model"], "tasks": tasks}


@app.post("/api/ask")
def ask(req: AskRequest):
    try:
        return assistant.ask(req.question, req.symbol, [t.model_dump() for t in req.history])
    except llm.AIUnavailable as e:
        raise HTTPException(503, str(e))


@app.post("/api/company/{symbol}/report")
def start_report(symbol: str):
    try:
        profile = yahoo.profile(yahoo.normalize_symbol(symbol))
        return {"job_id": report.start_job(profile["symbol"], profile["name"])}
    except LookupError:
        raise HTTPException(404, f"No listed company found for {symbol}")
    except llm.AIUnavailable as e:
        raise HTTPException(503, str(e))


@app.get("/api/reports/jobs/{job_id}")
def report_job(job_id: str):
    job = report.get_job(job_id)
    if not job:
        raise HTTPException(404, "Unknown or expired report job (jobs are lost when the API restarts)")
    return job


@app.get("/api/company/{symbol}/report")
def latest_report(symbol: str):
    saved = report.latest(yahoo.normalize_symbol(symbol))
    if not saved:
        raise HTTPException(404, "No report generated yet")
    return saved
