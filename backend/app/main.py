import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")  # before app.ai reads its settings

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app import auth, gmp, loader, research, screener, watchlist
from app.ai import assistant, filings, llm, report, screen_nl
from app.providers import nse, sec, yahoo

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Keep the database filling up and fresh while the API runs. Disable with FINSIGHT_BACKGROUND_LOADER=0."""
    stop = threading.Event()
    if os.environ.get("FINSIGHT_BACKGROUND_LOADER", "1") != "0":
        threading.Thread(target=loader.run_forever, args=(stop,), daemon=True).start()
    yield
    stop.set()


app = FastAPI(title="FinSight API", version="0.1.0", lifespan=lifespan)
# Websites allowed to call this API: comma-separated FINSIGHT_CORS_ORIGINS, e.g. "https://finsight.netlify.app".
# FINSIGHT_CORS_ORIGIN_REGEX can also allow Netlify deploy previews, e.g. "https://.*--finsight\.netlify\.app".
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", *filter(None, os.environ.get("FINSIGHT_CORS_ORIGINS", "").split(","))],
    allow_origin_regex=os.environ.get("FINSIGHT_CORS_ORIGIN_REGEX") or None,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/health/sources")
def health_sources():
    """Which external data sources this server can reach (cloud hosts are sometimes blocked)."""
    import time as _t
    from app.providers import investorgain

    def check(fn):
        started = _t.time()
        try:
            fn()
            return {"ok": True, "ms": round((_t.time() - started) * 1000)}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    return {
        "yahoo_quote": check(lambda: yahoo.profile.__wrapped__("RELIANCE.NS")),
        "yahoo_prices": check(lambda: yahoo.price_history.__wrapped__("RELIANCE.NS", "1mo") or (_ for _ in ()).throw(ValueError("empty"))),
        "nse": check(lambda: nse.current_ipos.__wrapped__()),
        "sec_edgar": check(lambda: sec.company_facts.__wrapped__(320193)),
        "investorgain": check(lambda: investorgain.live_list.__wrapped__()),
        "database": check(lambda: screener.coverage()),
    }



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
    us = sec.is_us(symbol)
    try:
        rows = sec.filings(symbol, limit) if us else nse.announcements(symbol, limit)
    except LookupError:
        raise HTTPException(404, f"No listed company found for {symbol}")
    except Exception as e:
        raise HTTPException(502, f"{'SEC filings' if us else 'NSE announcements'} unavailable: {e}")
    return [{**a, "summary": filings.cached(a["id"])} for a in rows]


@app.post("/api/company/{symbol}/announcements/{announcement_id}/summary")
def summarize_announcement(symbol: str, announcement_id: str, user: dict = Depends(auth.require_user)):
    if not filings.cached(announcement_id):
        if not llm.is_configured("summary"):
            raise HTTPException(503, f"No credentials for {llm.model_spec('summary')}.")
        auth.consume(user, "summary")  # stored summaries are free to reopen
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
def parse_screen(req: NLScreenRequest, user: dict = Depends(auth.require_user)):
    if not llm.is_configured("screen"):
        raise HTTPException(503, f"No credentials for {llm.model_spec('screen')}.")
    auth.consume(user, "screen")
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
    return {"configured": tasks["assistant"]["configured"], "model": tasks["assistant"]["model"], "tasks": tasks,
            "sign_in_required": auth.enabled()}


@app.get("/api/me")
def me(user: dict = Depends(auth.require_user)):
    return {"user": user, "ai_usage": auth.usage(user), "costs": auth.COST}


@app.post("/api/ask")
def ask(req: AskRequest, user: dict = Depends(auth.require_user)):
    if not llm.is_configured("assistant"):
        raise HTTPException(503, f"No credentials for {llm.model_spec('assistant')}.")
    auth.consume(user, "ask")
    try:
        return assistant.ask(req.question, req.symbol, [t.model_dump() for t in req.history])
    except llm.AIUnavailable as e:
        raise HTTPException(503, str(e))


@app.post("/api/company/{symbol}/report")
def start_report(symbol: str, user: dict = Depends(auth.require_user)):
    if not llm.is_configured("report"):
        raise HTTPException(503, f"No credentials for {llm.model_spec('report')}.")
    auth.consume(user, "report")
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


class WatchRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=40)
    note: str | None = Field(default=None, max_length=200)


class NoteRequest(BaseModel):
    note: str = Field(max_length=200)


@app.get("/api/watchlist")
def get_watchlist(user: dict = Depends(auth.require_user)):
    return watchlist.listing(user)


@app.get("/api/watchlist/symbols")
def watchlist_symbols(user: dict = Depends(auth.require_user)):
    return watchlist.symbols(user)


@app.post("/api/watchlist")
def add_to_watchlist(req: WatchRequest, user: dict = Depends(auth.require_user)):
    return watchlist.add(user, req.symbol, req.note)


@app.delete("/api/watchlist/{symbol}")
def remove_from_watchlist(symbol: str, user: dict = Depends(auth.require_user)):
    return watchlist.remove(user, symbol)


@app.patch("/api/watchlist/{symbol}")
def update_watchlist_note(symbol: str, req: NoteRequest, user: dict = Depends(auth.require_user)):
    return watchlist.set_note(user, symbol, req.note)


@app.get("/api/watchlist/{symbol}/details")
def watchlist_details(symbol: str, since: str | None = None, user: dict = Depends(auth.require_user)):
    return watchlist.details(user, symbol, since)
