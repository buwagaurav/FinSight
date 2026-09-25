"""Grey market premium (GMP) from investorgain.com.

GMP is unofficial and unverified: it's a price quoted in an unregulated grey market, not exchange data.
Every value keeps InvestorGain as its source, a link to the page, and InvestorGain's own timestamp.
(investorgain.com's robots.txt allows automated access; it only blocks AI-training crawlers.)
"""
import html
import re
from datetime import datetime, timedelta, timezone

import requests

from app.cache import ttl_cache

BASE = "https://www.investorgain.com"
LIVE_LIST = f"{BASE}/report/live-ipo-gmp/331/"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"}
IST = timezone(timedelta(hours=5, minutes=30))
_NOISE = {"limited", "ltd", "india", "ipo", "the", "and", "pvt", "private", "co", "company"}


def _get(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.text


def _cells(row: str) -> list[str]:
    return [html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c))).strip()
            for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.S)]


def _tables(page: str) -> list[list[list[str]]]:
    return [[_cells(r) for r in re.findall(r"<tr[^>]*>(.*?)</tr>", t, re.S)] for t in re.findall(r"<table.*?</table>", page, re.S)]


def _when(text: str, now: datetime) -> datetime | None:
    """InvestorGain omits the year ("25 Sept, 08:02 pm", "25-Sep 20:02"); take the year that isn't in the future."""
    text = text.replace("Sept", "Sep")
    for fmt in ("%d %b, %I:%M %p", "%d-%b %H:%M"):
        try:
            dt = datetime.strptime(text, fmt).replace(year=now.year, tzinfo=IST)
        except ValueError:
            continue
        return dt.replace(year=now.year - 1) if dt > now + timedelta(days=2) else dt
    return None


def _money(text: str) -> float | None:
    m = re.search(r"₹\s*(-?[\d,]+(?:\.\d+)?)", text)
    return float(m.group(1).replace(",", "")) if m else None


def normalize(name: str) -> list[str]:
    return [w for w in re.sub(r"[^a-z0-9 ]+", " ", name.lower()).split() if w not in _NOISE]


@ttl_cache(seconds=1800)
def live_list() -> list[dict]:
    """Every IPO on InvestorGain's live GMP page, with the link to its detail page."""
    page = _get(LIVE_LIST)
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S):
        link = re.search(r'<a href="(/gmp/[^"]+)"[^>]*title="([^"]+)"', row)
        if link:
            out.append({"name": html.unescape(link.group(2)), "url": BASE + link.group(1)})
    return out


def match(company: str, candidates: list[dict]) -> dict | None:
    """InvestorGain uses short names ("Orient Cables" for "Orient Cables (India) Limited")."""
    target = normalize(company)
    for c in candidates:
        words = normalize(c["name"])
        if words and target and words[0] == target[0] and set(words) <= set(target):
            return c
        if words and "".join(target).startswith("".join(words)):  # "Core Integra" vs "Coreintegra"
            return c
    return None


@ttl_cache(seconds=1800)
def history(url: str) -> list[dict]:
    """GMP readings for one IPO, oldest first: the intraday log if present, else the day-wise table."""
    now = datetime.now(IST)
    tables = _tables(_get(url))
    points: dict[datetime, float] = {}
    for t in tables:
        header = t[0] if t else []
        if header[:3] == ["#", "GMP", "Time"]:                       # intraday log
            for row in t[1:]:
                when, value = _when(row[2], now), _money(row[1])
                if when and value is not None:
                    points[when] = value
    if not points:
        for t in tables:
            if t and t[0] and t[0][0] == "GMP Date":                 # day-wise table
                for row in t[1:]:
                    when = _when(" ".join(row[0].split()[:2]), now)
                    value = _money(row[1])
                    if when and value is not None:
                        points[when] = value
    return [{"observed_at": k, "gmp": v} for k, v in sorted(points.items())]
