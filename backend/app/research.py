"""Assembles a full company analysis from the providers and the deterministic analytics engine.

Shared by the REST API and the AI assistant's tools, so both always see identical numbers.
"""
from app.analytics import fundamentals, scores, technicals, valuation
from app.providers import yahoo


def company_report(symbol: str) -> dict:
    """Raises LookupError when the symbol is not a listed company."""
    symbol = yahoo.normalize_symbol(symbol)
    profile = dict(yahoo.profile(symbol))  # copy: we override some multiples below, the cached original stays intact
    statements = yahoo.annual_statements(symbol)
    table = fundamentals.build_table(statements)
    growth = fundamentals.growth_summary(table)
    history = yahoo.price_history(symbol)
    technical = technicals.summarize(history)
    pe_history = valuation.historical_pe(table, history)
    checks = fundamentals.data_checks(table, profile, statements["converted_from"])
    _own_multiples(profile, table)
    company_scores = scores.compute(profile, table, growth, technical, pe_history)
    if checks and company_scores["confidence"] == "High":
        company_scores["confidence"] = "Medium"

    return {
        "profile": profile,
        "financials": {"unit": "₹ Cr (EPS in ₹)", "years": table, "growth": growth, "data_checks": checks,
                       "source": {"name": "Company filings via Yahoo Finance", "url": profile["source"]["url"] + "/financials"}},
        "scores": company_scores,
        "technical": technical,
        "valuation": {
            "pe_history": pe_history,
            "scenarios": valuation.scenarios(profile["price"], profile["trailing_eps"], growth.get("eps_cagr_pct"),
                                             pe_history, profile["pe"]),
        },
        # Weekly closes keep the payload small; the chart does not need daily points over 5 years.
        "prices": history[::5] + ([history[-1]] if history and len(history) % 5 != 1 else []),
    }


def _own_multiples(profile: dict, table: list[dict]) -> None:
    """Recompute P/S and EV/EBITDA from our rupee statements. The provider's versions mix currencies
    for companies that report in USD."""
    last = table[-1] if table else {}
    mcap = profile.get("market_cap_cr")
    if not mcap:
        return
    if last.get("revenue"):
        profile["ps"] = mcap / last["revenue"]
    if last.get("ebitda") and last["ebitda"] > 0 and profile.get("sector") != "Financial Services":
        profile["ev_ebitda"] = (mcap + (last.get("total_debt") or 0) - (last.get("cash") or 0)) / last["ebitda"]
    elif profile.get("sector") == "Financial Services":
        profile["ev_ebitda"] = None  # enterprise value is not meaningful for lenders
