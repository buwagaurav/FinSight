"""Official IPO data (dates, price band, issue size, live subscription) from NSE's public endpoints.

NSE requires a browser-like session: hit the homepage first to receive cookies, then call /api.
"""
import re
import threading
from datetime import datetime

import requests

from app.cache import ttl_cache

BASE = "https://www.nseindia.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": f"{BASE}/market-data/all-upcoming-issues-ipo",
}

_session: requests.Session | None = None
_session_lock = threading.Lock()


def _get(path: str, retry: bool = True):
    global _session
    with _session_lock:
        if _session is None:
            _session = requests.Session()
            _session.get(BASE, headers=HEADERS, timeout=15)
        session = _session
    r = session.get(f"{BASE}{path}", headers=HEADERS, timeout=15)
    if r.status_code in (401, 403) and retry:  # cookies expired: start a fresh session once
        with _session_lock:
            _session = None
        return _get(path, retry=False)
    r.raise_for_status()
    return r.json()


def _date(s: str | None) -> str | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%d-%b-%Y").date().isoformat()
    except ValueError:
        return None


def _num(s) -> float | None:
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _price_band(s: str | None) -> tuple[float | None, float | None]:
    nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", s or "")]
    if not nums:
        return None, None
    return min(nums), max(nums)


@ttl_cache(seconds=300)
def current_ipos() -> list[dict]:
    """Open and upcoming issues, including total subscription (times) for open mainboard issues."""
    rows = _get("/api/ipo-current-issue")
    out = []
    for r in rows:
        low, high = _price_band(r.get("issuePrice"))
        out.append({
            "symbol": r["symbol"],
            "name": r["companyName"],
            "segment": "SME" if r.get("series") == "SME" else "Mainboard",
            "status": r.get("status"),
            "open_date": _date(r.get("issueStartDate")),
            "close_date": _date(r.get("issueEndDate")),
            "price_low": low,
            "price_high": high,
            "shares_offered": _num(r.get("noOfSharesOffered")),
            "shares_bid": _num(r.get("noOfsharesBid")),
            "subscription_times": _num(r.get("noOfTime")),
            "issue_size_cr": (_num(r.get("noOfSharesOffered")) or 0) * high / 1e7 if high and r.get("noOfSharesOffered") else None,
            "source": {"name": "NSE India", "url": f"{BASE}/market-data/all-upcoming-issues-ipo"},
        })
    return out


# Routine filings that rarely move a thesis. They are listed but not sent to the AI by default.
ROUTINE = ("newspaper", "trading window", "closure of trading", "loss of share certificate", "duplicate share",
           "copy of newspaper", "certificate under sebi", "reg. 74", "regulation 74", "esop", "esos",
           "compliance certificate", "shareholding pattern", "investor complaints")


def _datetime(s: str | None) -> str | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%d-%b-%Y %H:%M:%S").isoformat()
    except ValueError:
        return None


@ttl_cache(seconds=900)
def announcements(symbol: str, limit: int = 30) -> list[dict]:
    """Latest corporate announcements filed on NSE, newest first, each with its original PDF."""
    base = symbol.split(".")[0].upper()
    rows = _get(f"/api/corporate-announcements?index=equities&symbol={requests.utils.quote(base)}")
    out = []
    for r in rows[:limit]:
        text = (r.get("attchmntText") or "").strip()
        category = (r.get("desc") or "").strip()
        out.append({
            "id": r["seq_id"],
            "symbol": base,
            "company": r.get("sm_name"),
            "category": category,
            "text": text,
            "published": _datetime(r.get("an_dt")),
            "pdf_url": r.get("attchmntFile") or None,
            "pdf_size": r.get("attFileSize"),
            "routine": any(k in f"{category} {text}".lower() for k in ROUTINE),
            "source": {"name": "NSE corporate announcement", "url": r.get("attchmntFile") or f"{BASE}/companies-listing/corporate-filings-announcements"},
        })
    return out


def download_pdf(url: str, max_bytes: int = 15_000_000) -> bytes:
    if not url.startswith("https://nsearchives.nseindia.com/"):
        raise ValueError("Only NSE archive attachments are fetched")
    r = requests.get(url, headers={"User-Agent": HEADERS["User-Agent"]}, timeout=30)
    r.raise_for_status()
    if len(r.content) > max_bytes:
        raise ValueError("Attachment too large to summarise")
    return r.content
