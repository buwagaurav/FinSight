"""Mutual fund NAVs from AMFI (Association of Mutual Funds in India): the official daily file of every scheme's
latest net asset value, about 14,000 schemes from all fund houses. Free, no key; updated each evening.

File layout (semicolon-separated rows between section headers):

    Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Plan;Option;Net Asset Value;Date
    Open Ended Schemes(Equity Scheme - Flexi Cap Fund)        <- category header
    PPFAS Mutual Fund                                         <- fund house header
    122639;INF879O01027;-;Parag Parikh Flexi Cap Fund;Direct Plan;Growth;88.2569;01-Oct-2026

Older schemes leave Plan and Option empty and put them in the name ("... - Direct Plan - Growth").
"""
import re
from datetime import datetime

import requests

from app.cache import ttl_cache

URL = "https://portal.amfiindia.com/spages/NAVAll.txt"
SOURCE = {"name": "AMFI daily NAV", "url": URL}
HEADERS = {"User-Agent": "Mozilla/5.0 (FinSight; +https://github.com/buwagaurav/FinSight)"}
CATEGORY = re.compile(r"^(Open Ended|Close Ended|Interval Fund) Schemes\((.+)\)$")


def clean_category(raw: str) -> tuple[str, str]:
    """(group, category). AMFI spells the same category several ways ("Equity Scheme - ELSS",
    "Equity Schemes - ELSS- Tax Saver Fund"); these collapse to one name."""
    text = re.sub(r"\s+", " ", raw.replace("**", "")).strip()
    text = re.sub(r"\bSchemes\b", "Scheme", text)
    text = re.sub(r"ELSS- Tax Saver Fund", "ELSS", text)
    group, _, sub = text.partition(" - ")
    return group.strip(), (sub.strip() or group.strip())


def _plan_option(name: str, plan: str, option: str) -> tuple[str, str]:
    """Direct/Regular, and Growth/IDCW/Other, from the columns when given, else from the scheme name. AMFI spells
    IDCW dozens of ways ("Income Distribution Cum Capital Withdrawal", "Idwc Option", "Monthly Dividend"...)."""
    text = f"{plan} {option} {name}".lower()
    plan = "Direct" if re.search(r"\bdirect\b", text) else "Regular"
    if re.search(r"unclaimed|redemption", text):
        option = "Other"   # holding plans for unclaimed redemptions, not investable
    elif re.search(r"growth|cumulative", text):
        option = "Growth"
    elif re.search(r"idcw|idwc|income distribution|dividend|bonus|payout|reinvest", text):
        option = "IDCW"
    else:
        option = "Other" if option else "Growth"
    return plan, option


def base_name(name: str) -> str:
    """The fund's name without plan and option ("X Fund - Direct Plan - Growth" -> "X Fund"), so all of a fund's
    variants group together."""
    # "Direct"/"Regular" only count when they name the plan ("- Regular Plan", "- Direct - Growth"), not a fund
    # called "UTI - Regular Saving Fund"
    plan_word = r"(?:direct|regular)(?=\s*(?:plan\b|option\b|[-–(]|$|growth\b|idcw\b|dividend\b))"
    cut = re.split(rf"\s*[-–(]\s*(?:{plan_word}|growth\b|idcw\b|dividend\b|bonus\b|(?:retail|institutional)\s+(?:plan|option)\b)",
                   name, maxsplit=1, flags=re.IGNORECASE)[0]
    return re.sub(r"\s+", " ", cut).strip(" -–")


def parse(text: str) -> list[dict]:
    rows, kind, group, category, house = [], None, None, None, None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("Scheme Code;"):
            continue
        if ";" not in line:
            m = CATEGORY.match(line)
            if m:
                kind = m.group(1)
                group, category = clean_category(m.group(2))
            else:
                house = line
            continue
        parts = [p.strip() for p in line.split(";")]
        if len(parts) < 8 or not parts[0].isdigit():
            continue
        code, isin_growth, isin_reinvest, name, plan, option, nav, date = parts[:8]
        try:
            value = float(nav)
            when = datetime.strptime(date, "%d-%b-%Y").date().isoformat()
        except ValueError:
            continue   # "N.A." NAVs: nothing to show
        detail = option   # AMFI's own wording, e.g. "Monthly IDCW (Payout/Reinvestment)"
        plan, option = _plan_option(name, plan, option)
        name = re.sub(r"\s+", " ", name)
        rows.append({
            "code": int(code), "name": name, "fund": base_name(name), "house": house, "option_detail": detail or None,
            "type": kind, "group": group, "category": category, "plan": plan, "option": option,
            "nav": value, "nav_date": when,
            "isins": [i for i in (isin_growth, isin_reinvest) if i and i != "-"],
        })
    return rows


@ttl_cache(seconds=3600)
def schemes() -> list[dict]:
    """Every scheme with its latest NAV. Raises on a network failure (callers show an error)."""
    r = requests.get(URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    r.encoding = "utf-8"   # the server doesn't say, and the default guess (Latin-1) garbles names like "Children’s"
    rows = parse(r.text)
    if len(rows) < 1000:
        raise RuntimeError("AMFI's NAV file looks incomplete")
    return rows
