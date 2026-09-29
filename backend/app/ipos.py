"""The IPO list: every IPO InvestorGain tracks (upcoming, open, closed, allotted and recently listed; mainboard and
SME; NSE and BSE), with NSE's official figures merged in for issues NSE currently lists.

NSE's feed only covers issues open or about to open on NSE, and drops them once bidding closes, so it can't be the
list on its own. Each IPO keeps one stable key for its whole life (InvestorGain's id, e.g. "IG-2370"), so its GMP
history doesn't vanish when NSE stops listing it.
"""
from app.providers import investorgain, nse

ORDER = {"Open": 0, "Upcoming": 1, "Closed": 2, "Allotted": 3, "Listed": 4}
NSE_STATUS = {"Active": "Open", "Forthcoming": "Upcoming"}


def _from_nse(n: dict) -> dict:
    return {"symbol": n["symbol"], "nse_symbol": n["symbol"], "name": n["name"], "segment": n["segment"],
            "exchange": "NSE", "status": NSE_STATUS.get(n.get("status"), n.get("status")), "open_date": n["open_date"],
            "close_date": n["close_date"], "allotment_date": None, "listing_date": None, "price_low": n["price_low"],
            "price_high": n["price_high"], "lot": None, "issue_size_cr": n["issue_size_cr"],
            "shares_offered": n["shares_offered"], "shares_bid": n["shares_bid"],
            "subscription_times": n["subscription_times"], "listing_gain_pct": None, "source": n["source"],
            "investorgain": None}


def current() -> list[dict]:
    """All tracked IPOs, open first, then upcoming, closed, allotted and listed. Raises if both sources fail."""
    errors = []
    try:
        tracked = investorgain.live_ipos()
    except Exception as e:
        tracked, _ = [], errors.append(f"InvestorGain: {e}")
    try:
        on_nse = nse.current_ipos()
    except Exception as e:
        on_nse, _ = [], errors.append(f"NSE: {e}")
    if not tracked and not on_nse:
        raise RuntimeError("; ".join(errors) or "no IPO data")

    rows, used = [], set()
    for g in tracked:
        n = next((n for n in on_nse if n["symbol"] not in used and investorgain.match(n["name"], [g])), None)
        if n:
            used.add(n["symbol"])
        row = _from_nse(n) if n else {"nse_symbol": None, "shares_offered": None, "shares_bid": None}
        row.update({
            "symbol": f"IG-{g['id']}",
            "name": n["name"] if n else g["name"],
            "segment": g["segment"],
            "exchange": g["exchange"],
            "status": g["status"] or row.get("status"),
            "open_date": g["open_date"] or row.get("open_date"),
            "close_date": g["close_date"] or row.get("close_date"),
            "allotment_date": g["allotment_date"],
            "listing_date": g["listing_date"],
            # NSE's figures are official: prefer them where NSE has the issue
            "price_low": row.get("price_low") or g["price_low"],
            "price_high": row.get("price_high") or g["price_high"],
            "lot": g["lot"],
            "issue_size_cr": g["issue_size_cr"] or row.get("issue_size_cr"),
            "subscription_times": row.get("subscription_times") if n and row.get("subscription_times") is not None else g["subscription_times"],
            "listing_gain_pct": g["listing_gain_pct"],
            "source": row.get("source") or {"name": "InvestorGain", "url": g["url"]},
            "investorgain": {"url": g["url"], "gmp": g["gmp"], "updated": g["gmp_updated"]},
        })
        rows.append(row)
    rows += [_from_nse(n) for n in on_nse if n["symbol"] not in used]
    live = sorted((r for r in rows if r["status"] in ("Open", "Upcoming")),
                  key=lambda r: (ORDER[r["status"]], r["close_date"] or "9999"))      # closing soonest first
    done = [r for r in rows if r["status"] not in ("Open", "Upcoming")]
    done.sort(key=lambda r: r["listing_date"] or r["close_date"] or "", reverse=True)  # most recent first...
    done.sort(key=lambda r: ORDER.get(r["status"], 5))                                  # ...within each status
    return live + done
