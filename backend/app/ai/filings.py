"""Structured AI summaries of NSE corporate announcements, grounded in the filed PDF.

Filings are immutable, so each summary is generated once and stored in PostgreSQL.
"""
import base64
import io
import json
import threading
from typing import Literal

from pydantic import BaseModel, Field
from pypdf import PdfReader

from app import db
from app.ai import llm
from app.ai.verify import unverified_numbers
from app.providers import nse

MAX_TEXT_CHARS = 15_000  # the substance of a filing is almost always up front; keeps each summary cheap
_locks: dict[str, threading.Lock] = {}


class KeyFigure(BaseModel):
    label: str = Field(description="What the number is, e.g. 'Q2 revenue' or 'Interim dividend per share'")
    value: str = Field(description="The figure exactly as written in the filing, with its unit")


class FilingSummary(BaseModel):
    headline: str = Field(description="One line, plain English, under 15 words")
    what_happened: str = Field(description="2-3 sentences stating the facts in the filing")
    why_it_matters: str = Field(description="2-3 sentences on the likely relevance to shareholders; say if it is routine")
    sentiment: Literal["positive", "negative", "neutral", "uncertain"]
    materiality: Literal["high", "medium", "low"]
    affected_metrics: list[str] = Field(description="Financial metrics this could affect, e.g. revenue, margins, debt, dividend")
    watch_next: list[str] = Field(description="Up to 3 concrete things an investor should monitor next")
    key_figures: list[KeyFigure] = Field(description="Up to 6 important numbers quoted from the filing; empty if none")


SYSTEM = """You summarise Indian stock-exchange filings for retail investors.
Rules:
- Use only what the filing says. Do not add facts, figures or context from memory.
- key_figures must be copied from the filing text exactly.
- Judge materiality honestly: most press releases and procedural notices are low materiality.
- sentiment is about the likely effect on the company's fundamentals, not the tone of the press release.
- Plain language; no investment advice."""


def _pdf_text(pdf: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(pdf))
        return "\n".join((page.extract_text() or "") for page in reader.pages[:40])[:MAX_TEXT_CHARS]
    except Exception:
        return ""


def _find(symbol: str, announcement_id: str) -> dict:
    for a in nse.announcements(symbol, 200):
        if a["id"] == announcement_id:
            return a
    raise LookupError(f"Announcement {announcement_id} not found for {symbol}")


def cached(announcement_id: str) -> dict | None:
    row = db.fetch_one("SELECT data FROM filing_summaries WHERE announcement_id = %s", (announcement_id,))
    return row["data"] if row else None


def summarize(symbol: str, announcement_id: str) -> dict:
    if hit := cached(announcement_id):
        return hit
    lock = _locks.setdefault(announcement_id, threading.Lock())
    with lock:  # two viewers clicking at once should cost one API call
        if hit := cached(announcement_id):
            return hit
        a = _find(symbol, announcement_id)
        header = f"Company: {a['company']}\nCategory: {a['category']}\nExchange note: {a['text']}\nFiled: {a['published']}"

        text, basis = "", "exchange note only"
        content: list[dict] | str
        if a["pdf_url"]:
            pdf = nse.download_pdf(a["pdf_url"])
            text = _pdf_text(pdf)
            if len(text.strip()) >= 200:
                basis = "filing text"
                content = f"{header}\n\n--- Filing text ---\n{text}"
            else:  # scanned PDF: send the pages themselves (needs a PDF-capable model)
                basis = "filing PDF (scanned, figures not machine-verifiable)"
                content = [
                    {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                    "data": base64.standard_b64encode(pdf).decode()}},
                    {"type": "text", "text": header},
                ]
        else:
            content = header

        summary = llm.structured(FilingSummary, SYSTEM, content, task="summary")
        prose = " ".join([summary.what_happened, summary.why_it_matters] + [f.value for f in summary.key_figures])
        checkable = basis != "filing PDF (scanned, figures not machine-verifiable)"
        missing = unverified_numbers(prose, [json.dumps(f"{header}\n{text}")]) if checkable else []

        result = {
            "announcement": a,
            "summary": summary.model_dump(),
            "basis": basis,
            "verification": {
                "checked": checkable,
                "passed": checkable and not missing,
                "unverified": missing,
            },
            "model": llm.model_spec("summary"),
        }
        db.execute("""INSERT INTO filing_summaries (announcement_id, symbol, data) VALUES (%s, %s, %s)
                      ON CONFLICT (announcement_id) DO NOTHING""", (announcement_id, a["symbol"], db.jsonb(result)))
        return result
