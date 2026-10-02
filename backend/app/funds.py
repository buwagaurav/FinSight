"""Mutual fund search and detail over AMFI's daily NAV file (providers/amfi.py).

A fund ("Parag Parikh Flexi Cap Fund") has several schemes, one per plan and option (Direct Growth, Regular IDCW...),
each with its own scheme code and NAV. Schemes whose last NAV is more than a week older than the latest NAV date
are treated as inactive (matured, merged or closed) and hidden unless asked for.
"""
from collections import Counter
from datetime import date, timedelta

from app.providers import amfi

STALE_AFTER = timedelta(days=7)
PAGE = 50


def latest_date(rows: list[dict]) -> str:
    """The day most schemes' NAVs are for. Not the newest date in the file: a few rows carry dates in the future,
    apparently typos at the fund house."""
    return Counter(r["nav_date"] for r in rows).most_common(1)[0][0]


def _active_cutoff(rows: list[dict]) -> str:
    return (date.fromisoformat(latest_date(rows)) - STALE_AFTER).isoformat()


def _with_status(row: dict, cutoff: str) -> dict:
    return {**row, "active": row["nav_date"] >= cutoff}


def search(q: str = "", group: str | None = None, category: str | None = None, house: str | None = None,
           plan: str | None = None, option: str | None = None, include_inactive: bool = False,
           offset: int = 0, limit: int = PAGE) -> dict:
    rows = amfi.schemes()
    cutoff = _active_cutoff(rows)
    words = [w for w in q.lower().split() if w]
    code = int(q) if q.strip().isdigit() else None

    def keep(r: dict) -> bool:
        if code is not None:
            return r["code"] == code
        if not include_inactive and r["nav_date"] < cutoff:
            return False
        if words and not all(w in f"{r['name']} {r['house']}".lower() for w in words):
            return False
        return ((not group or r["group"] == group) and (not category or r["category"] == category)
                and (not house or r["house"] == house) and (not plan or r["plan"] == plan)
                and (not option or r["option"] == option))

    found = sorted((r for r in rows if keep(r)), key=lambda r: (r["fund"].lower(), r["plan"], r["option"]))
    active = [r for r in rows if r["nav_date"] >= cutoff]
    groups: dict[str, set] = {}
    for r in active:
        groups.setdefault(r["group"], set()).add(r["category"])
    return {
        "total": len(found),
        "rows": [_with_status(r, cutoff) for r in found[offset:offset + limit]],
        "offset": offset,
        "nav_date": latest_date(rows),
        "facets": {
            "groups": {g: sorted(c) for g, c in sorted(groups.items())},
            "houses": sorted({r["house"] for r in active if r["house"]}),
        },
        "source": amfi.SOURCE,
    }


def detail(code: int) -> dict:
    """A scheme and every other plan/option of the same fund. Raises LookupError for an unknown code."""
    rows = amfi.schemes()
    cutoff = _active_cutoff(rows)
    scheme = next((r for r in rows if r["code"] == code), None)
    if scheme is None:
        raise LookupError(code)
    variants = [r for r in rows if r["fund"] == scheme["fund"] and r["house"] == scheme["house"]]
    variants.sort(key=lambda r: (r["plan"] != "Direct", r["option"] != "Growth", r["name"]))
    direct = next((r for r in variants if r["plan"] == "Direct" and r["option"] == "Growth"), None)
    regular = next((r for r in variants if r["plan"] == "Regular" and r["option"] == "Growth"), None)
    gap = None
    if direct and regular and regular["nav"] and direct["nav_date"] == regular["nav_date"]:
        # Same fund, same day: the Direct plan's higher NAV is the cost of distributor commission, compounded
        gap = {"direct": direct["code"], "regular": regular["code"],
               "direct_ahead_pct": (direct["nav"] / regular["nav"] - 1) * 100}
    return {"scheme": _with_status(scheme, cutoff), "variants": [_with_status(r, cutoff) for r in variants],
            "direct_vs_regular": gap, "source": amfi.SOURCE}
