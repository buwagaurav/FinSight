"""Historical valuation bands and bear/base/bull scenarios.

FinSight never states a single "fair price". It shows a range and the assumptions that produce it.
"""
import bisect
import statistics

HORIZON_YEARS = 3


def _close_on(history: list[dict], iso_date: str) -> float | None:
    dates = [p["date"] for p in history]
    i = bisect.bisect_right(dates, iso_date) - 1
    return history[i]["close"] if i >= 0 else None


def historical_pe(table: list[dict], history: list[dict]) -> list[dict]:
    """P/E at each fiscal year end = close on the period-end date / that year's EPS."""
    out = []
    for r in table:
        if not r.get("period_end") or not r.get("eps") or r["eps"] <= 0:
            continue
        if history and r["period_end"] < history[0]["date"]:
            continue
        price = _close_on(history, r["period_end"])
        if price:
            out.append({"year": r["year"], "price": price, "eps": r["eps"], "pe": price / r["eps"]})
    return out


def scenarios(price: float | None, eps_ttm: float | None, eps_cagr_pct: float | None, pe_history: list[dict],
              current_pe: float | None) -> dict | None:
    if not price or not eps_ttm or eps_ttm <= 0:
        return None
    pes = [p["pe"] for p in pe_history if 0 < p["pe"] < 200]
    if current_pe and 0 < current_pe < 200:
        pes.append(current_pe)
    else:
        current_pe = None
    if len(pes) < 2:
        return None
    median_pe = statistics.median(pes)
    # Partial mean reversion: a full snap back to the historical median is too optimistic for a base case.
    base_pe = (current_pe + median_pe) / 2 if current_pe else median_pe

    base_g = max(-5.0, min(eps_cagr_pct if eps_cagr_pct is not None else 8.0, 25.0))
    cases = {
        "bear": {"growth_pct": max(base_g - 6, -10.0), "exit_pe": min(pes)},
        "base": {"growth_pct": base_g, "exit_pe": base_pe},
        "bull": {"growth_pct": base_g + 4, "exit_pe": max(pes)},
    }
    for name, c in cases.items():
        eps_future = eps_ttm * (1 + c["growth_pct"] / 100) ** HORIZON_YEARS
        value = eps_future * c["exit_pe"]
        c.update({
            "eps_in_3y": eps_future,
            "implied_price": value,
            "implied_return_pct": (value / price - 1) * 100,
            "implied_annual_return_pct": ((value / price) ** (1 / HORIZON_YEARS) - 1) * 100 if value > 0 else None,
        })
    return {
        "horizon_years": HORIZON_YEARS,
        "current_price": price,
        "eps_ttm": eps_ttm,
        "cases": cases,
        "assumptions": [
            f"Base-case EPS growth = historical EPS CAGR ({base_g:.1f}%), capped between -5% and 25%.",
            "Bear case: growth 6 points lower and exit P/E at the lowest P/E seen in the period.",
            "Bull case: growth 4 points higher and exit P/E at the highest P/E seen in the period.",
            f"Base-case exit P/E ({base_pe:.1f}) assumes today's P/E moves halfway toward its historical median ({median_pe:.1f}).",
            "Ignores dividends, dilution and changes in interest rates. These are scenarios, not predictions.",
        ],
    }
