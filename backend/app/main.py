import json
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import anyio
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")  # before app.ai reads its settings

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel, Field, field_validator

from app import auth, candles, funds, gmp, ipos, loader, research, screener, watchlist
from app.ai import assistant, filings, guardrail, llm, report, screen_nl
from app.providers import nse, sec, yahoo

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Keep the database filling up and fresh while the API runs. Disable with FINSIGHT_BACKGROUND_LOADER=0."""
    # Endpoints are plain functions run in a thread pool. They mostly wait on Yahoo, SEC, NSE or the database,
    # so more threads than anyio's default 40 let more visitors be served at once for little memory.
    anyio.to_thread.current_default_thread_limiter().total_tokens = int(os.environ.get("FINSIGHT_THREADS", "100"))
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
# JSON compresses 5-8x: the IPO list goes from ~90 KB to ~12 KB, which matters most on phones
app.add_middleware(GZipMiddleware, minimum_size=1000)


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


@app.get("/api/company/{symbol}/candles")
def company_candles(symbol: str, range: Literal[tuple(candles.RANGES)] = "1d"):  # type: ignore[valid-type]
    try:
        return candles.candles(symbol, range)
    except LookupError:
        raise HTTPException(404, f"No price data for {symbol}")


@app.get("/api/health/storage")
def health_storage():
    """How much of the database is used, and by what (sizes only; no data)."""
    from app import db
    total = db.fetch_one("SELECT pg_database_size(current_database()) AS bytes")["bytes"]
    tables = db.fetch_all("""SELECT relname AS table, pg_total_relation_size(relid) AS bytes, n_live_tup AS rows
                             FROM pg_stat_user_tables ORDER BY 2 DESC LIMIT 15""")
    return {"database_mb": round(total / 1e6, 1),
            "tables": [{"table": t["table"], "mb": round(t["bytes"] / 1e6, 1), "rows": t["rows"]} for t in tables]}


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
    try:
        if filings.cached(announcement_id):   # stored summaries are free to reopen and need no AI slot
            return filings.summarize(symbol, announcement_id)
        if not llm.is_configured("summary"):
            raise HTTPException(503, f"No credentials for {llm.model_spec('summary')}.")
        with llm.slot():   # charged only once a slot is free
            auth.consume(user, "summary")
            return filings.summarize(symbol, announcement_id)
    except llm.AIUnavailable as e:
        raise HTTPException(503, str(e))
    except llm.AIRefused as e:
        raise HTTPException(422, str(e))
    except LookupError as e:
        raise HTTPException(404, str(e))


@app.get("/api/ipos")
def ipos_list():
    try:
        rows = ipos.current()
    except Exception as e:
        raise HTTPException(502, f"IPO data unavailable: {e}")
    gmp.sync(rows)
    gmps = gmp.summaries(rows)
    for r in rows:
        r["gmp"] = gmps[r["symbol"]]
    return rows


@app.get("/api/ipos/{symbol}")
def ipo(symbol: str):
    key = symbol.upper()
    match = next((r for r in ipos_list() if key in (r["symbol"], r["nse_symbol"])), None)
    if not match:
        raise HTTPException(404, f"{symbol} is not among the IPOs FinSight tracks")
    return match


@app.get("/api/funds")
def funds_search(q: str = Query("", max_length=100), group: str | None = None, category: str | None = None,
                 house: str | None = None, plan: Literal["Direct", "Regular"] | None = None,
                 option: Literal["Growth", "IDCW", "Other"] | None = None, include_inactive: bool = False,
                 offset: int = Query(0, ge=0), limit: int = Query(funds.PAGE, ge=1, le=200)):
    try:
        return funds.search(q, group, category, house, plan, option, include_inactive, offset, limit)
    except Exception as e:
        raise HTTPException(502, f"Mutual fund data from AMFI is unavailable right now: {e}")


@app.get("/api/funds/{code}")
def fund_detail(code: int):
    try:
        return funds.detail(code)
    except LookupError:
        raise HTTPException(404, f"No mutual fund scheme with code {code} in AMFI's list")
    except Exception as e:
        raise HTTPException(502, f"Mutual fund data from AMFI is unavailable right now: {e}")


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
    market: Literal["IN", "US"] = "IN"
    filters: list[Filter] = []
    sectors: list[Literal[tuple(screener.SECTORS)]] = []  # type: ignore[valid-type]
    sort: str | None = "market_cap_cr"
    descending: bool = True


@app.get("/api/screener/fields")
def screener_fields(market: Literal["IN", "US"] = "IN"):
    return screener.fields(market)


@app.get("/api/screener/sectors")
def screener_sectors():
    return screener.SECTORS


class NLScreenRequest(BaseModel):
    query: str = Field(min_length=3, max_length=500)
    market: Literal["IN", "US"] = "IN"


@app.post("/api/screener/parse")
def parse_screen(req: NLScreenRequest, user: dict = Depends(auth.require_user)):
    if not llm.is_configured("screen"):
        raise HTTPException(503, f"No credentials for {llm.model_spec('screen')}.")
    try:
        with llm.slot():
            auth.consume(user, "screen")
            return screen_nl.parse(req.query, req.market)
    except llm.AIUnavailable as e:
        raise HTTPException(503, str(e))
    except llm.AIRefused as e:
        raise HTTPException(422, str(e))


@app.post("/api/screener")
def run_screen(req: ScreenRequest):
    try:
        return screener.run([f.model_dump() for f in req.filters], req.sort, req.descending, req.sectors, req.market)
    except ValueError as e:
        raise HTTPException(422, str(e))


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=20000)


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    symbol: str | None = None
    history: list[ChatTurn] = []
    state: dict | None = None   # returned with the previous answer; see app/ai/conversation.py

    @field_validator("state")
    @classmethod
    def _small_state(cls, v):
        if v is not None and len(json.dumps(v)) > 60000:
            raise ValueError("conversation state is too large; start a new conversation")
        return v


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
    if guardrail.precheck(req.question, req.symbol):
        return assistant.out_of_scope(req.state)   # no model call, nothing charged
    if not llm.is_configured("assistant"):
        raise HTTPException(503, f"No credentials for {llm.model_spec('assistant')}.")
    try:
        with llm.slot():
            auth.consume(user, "ask")
            return assistant.ask(req.question, req.symbol, [t.model_dump() for t in req.history], req.state)
    except llm.AIUnavailable as e:
        raise HTTPException(503, str(e))


@app.post("/api/company/{symbol}/report")
def start_report(symbol: str, user: dict = Depends(auth.require_user)):
    if not llm.is_configured("report"):
        raise HTTPException(503, f"No credentials for {llm.model_spec('report')}.")
    try:
        # the company data has fallbacks (stored data, SEC) for when Yahoo's quote endpoint refuses the server
        profile = research.company_report(symbol)["profile"]
        auth.consume(user, "report")
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
    # null, not 404, when none exists yet: that's the normal state of most companies, and a 404 would log an error
    # in every visitor's browser console
    return report.latest(yahoo.normalize_symbol(symbol))


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
