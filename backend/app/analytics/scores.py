"""Rule-based FinSight scores. Every point added or removed is recorded as a reason the user can read.

Scores are research aids, not recommendations. GMP and other unofficial data are never used here.
"""
import statistics

FINANCIAL_SECTORS = {"Financial Services"}
RISK_FREE_YIELD_PCT = 7.0  # approx. India 10-year G-sec yield; used as an earnings-yield hurdle


class Card:
    def __init__(self, name: str):
        self.name = name
        self.points = 50.0
        self.reasons: list[dict] = []
        self.inputs = 0

    def add(self, points: float, text: str):
        self.points += points
        self.reasons.append({"text": text, "points": points})

    def result(self, improving: bool = False) -> dict:
        score = round(max(0.0, min(100.0, self.points)))
        return {
            "name": self.name,
            "score": score if self.inputs else None,
            "label": label(score, improving) if self.inputs else "Not enough data",
            "reasons": sorted(self.reasons, key=lambda r: -abs(r["points"])),
        }


def label(score: float, improving: bool = False) -> str:
    if score >= 72:
        return "Strong"
    if score >= 55:
        return "Improving" if improving else "Stable"
    if score >= 40:
        return "Watchlist"
    return "Weak"


def _latest(table, key):
    for r in reversed(table):
        if r.get(key) is not None:
            return r[key]
    return None


def _tiered(card: Card, value, tiers, fmt):
    """tiers: [(threshold, points)] checked top-down with value >= threshold; last entry is the fallback."""
    if value is None:
        return
    card.inputs += 1
    for threshold, pts in tiers:
        if threshold is None or value >= threshold:
            card.add(pts, fmt(value))
            return


def compute(profile: dict, table: list[dict], growth: dict, technical: dict, pe_history: list[dict]) -> dict:
    financial = profile.get("sector") in FINANCIAL_SECTORS
    n = growth.get("years", 0)

    # --- Fundamentals: quality of returns and earnings ---
    f = Card("Fundamentals")
    _tiered(f, _latest(table, "roe_pct"), [(20, 20), (15, 12), (10, 4), (0, -10), (None, -25)],
            lambda v: f"Return on equity {v:.1f}% in {table[-1]['year']}")
    if not financial:
        _tiered(f, _latest(table, "roce_pct"), [(20, 12), (15, 8), (10, 0), (None, -8)],
                lambda v: f"Return on capital employed {v:.1f}%")
        margins = [r["operating_margin_pct"] for r in table if r.get("operating_margin_pct") is not None]
        if len(margins) >= 3:
            f.inputs += 1
            delta = margins[-1] - margins[0]
            if delta >= 3:
                f.add(8, f"Operating margin expanded {delta:.1f} pts over {n} years ({margins[0]:.1f}% → {margins[-1]:.1f}%)")
            elif delta <= -3:
                f.add(-8, f"Operating margin contracted {abs(delta):.1f} pts over {n} years ({margins[0]:.1f}% → {margins[-1]:.1f}%)")
        conv = [r["cash_conversion"] for r in table if r.get("cash_conversion") is not None]
        if conv:
            avg = statistics.mean(conv)
            _tiered(f, avg, [(0.9, 10), (0.6, 0), (None, -10)],
                    lambda v: f"Operating cash flow averaged {v:.2f}x net profit (cash conversion)")
    roes = [r["roe_pct"] for r in table if r.get("roe_pct") is not None]
    fundamentals_improving = len(roes) >= 3 and roes[-1] > roes[-3]

    # --- Growth ---
    g = Card("Growth")
    growth_tiers = [(15, 20), (10, 12), (5, 4), (0, -4), (None, -20)]
    _tiered(g, growth.get("revenue_cagr_pct"), growth_tiers, lambda v: f"Revenue grew {v:.1f}% a year over {n} years")
    _tiered(g, growth.get("profit_cagr_pct"), growth_tiers, lambda v: f"Net profit grew {v:.1f}% a year over {n} years")
    latest_growth = _latest(table, "profit_growth_pct")
    if latest_growth is not None:
        g.inputs += 1
        g.add(5 if latest_growth > 0 else -8, f"Net profit {'rose' if latest_growth > 0 else 'fell'} "
                                              f"{abs(latest_growth):.1f}% in the latest year")
    growth_improving = latest_growth is not None and growth.get("profit_cagr_pct") is not None \
        and latest_growth > growth["profit_cagr_pct"]

    # --- Valuation (higher score = cheaper relative to its own history and fundamentals) ---
    v = Card("Valuation")
    pe = profile.get("pe")
    if pe and pe > 0:
        pes = [p["pe"] for p in pe_history if 0 < p["pe"] < 200]
        if len(pes) >= 2:
            v.inputs += 1
            median = statistics.median(pes)
            gap = (pe / median - 1) * 100
            if gap <= -15:
                v.add(15, f"P/E {pe:.1f} is {abs(gap):.0f}% below its {len(pes)}-year median of {median:.1f}")
            elif gap >= 15:
                v.add(-15, f"P/E {pe:.1f} is {gap:.0f}% above its {len(pes)}-year median of {median:.1f}")
            else:
                v.add(0, f"P/E {pe:.1f} is close to its {len(pes)}-year median of {median:.1f}")
        _tiered(v, 100 / pe, [(RISK_FREE_YIELD_PCT, 10), (2.5, 0), (None, -10)],
                lambda ey: f"Earnings yield {ey:.1f}% vs ~{RISK_FREE_YIELD_PCT:.0f}% on 10-year government bonds")
        eps_g = growth.get("eps_cagr_pct")
        if eps_g and eps_g >= 3:  # PEG explodes and stops meaning anything when growth is near zero
            _tiered(v, pe / eps_g, [(2.5, -12), (1, 0), (None, 12)],
                    lambda peg: f"PEG {peg:.2f} (P/E ÷ {eps_g:.1f}% EPS growth)")
    elif pe is None and profile.get("trailing_eps") is not None and profile["trailing_eps"] <= 0:
        v.inputs += 1
        v.add(-20, "Company is loss-making on a trailing basis, so P/E is not meaningful")

    # --- Safety: balance sheet and price risk (higher = lower risk) ---
    s = Card("Safety")
    if financial:
        s.reasons.append({"text": "Debt ratios are not scored for banks and financials: borrowing is their raw material", "points": 0})
    else:
        _tiered(s, _latest(table, "debt_to_equity"), [(1.5, -15), (1.0, -5), (0.3, 5), (None, 15)],
                lambda d: f"Debt-to-equity {d:.2f}")
        _tiered(s, _latest(table, "interest_coverage"), [(8, 10), (3, 0), (None, -12)],
                lambda c: f"Interest coverage {c:.1f}x (EBIT ÷ interest)")
        fcf = [r["free_cash_flow"] for r in table if r.get("free_cash_flow") is not None]
        if fcf:
            s.inputs += 1
            negative = sum(1 for x in fcf if x < 0)
            if negative == 0:
                s.add(8, f"Free cash flow positive in all {len(fcf)} years")
            elif negative >= 2:
                s.add(-10, f"Free cash flow negative in {negative} of {len(fcf)} years")
    _tiered(s, technical.get("volatility_1y_pct"), [(40, -10), (25, 0), (None, 8)],
            lambda vol: f"1-year price volatility {vol:.0f}%")
    _tiered(s, technical.get("max_drawdown_1y_pct"), [(-20, 0), (-35, -5), (None, -10)],
            lambda dd: f"Largest fall from a peak in the last year: {dd:.0f}%")

    cards = {
        "fundamentals": f.result(fundamentals_improving),
        "growth": g.result(growth_improving),
        "valuation": v.result(),
        "safety": s.result(),
    }
    weights = {"fundamentals": 0.3, "growth": 0.25, "valuation": 0.2, "safety": 0.25}
    scored = {k: c["score"] for k, c in cards.items() if c["score"] is not None}
    overall = round(sum(scored[k] * weights[k] for k in scored) / sum(weights[k] for k in scored)) if scored else None

    all_reasons = [r for c in cards.values() for r in c["reasons"]]
    positives = [r["text"] for r in sorted(all_reasons, key=lambda r: -r["points"]) if r["points"] > 0][:3]
    risks = [r["text"] for r in sorted(all_reasons, key=lambda r: r["points"]) if r["points"] < 0][:3]
    filled = sum(c["score"] is not None for c in cards.values())
    confidence = "High" if n >= 4 and filled == 4 else "Medium" if n >= 2 and filled >= 3 else "Low"

    return {
        "overall": {"score": overall, "label": label(overall) if overall is not None else "Not enough data"},
        "view": _view_sentence(cards, technical),
        "cards": cards,
        "positives": positives,
        "risks": risks,
        "confidence": confidence,
        "confidence_basis": f"{n + 1 if n else 0} years of statements, {filled} of 4 score areas computed",
        "method": "Rule-based scores from reported financials and price history. Not investment advice.",
    }


def _view_sentence(cards: dict, technical: dict) -> str:
    def word(card, good, mid, bad):
        s = card["score"]
        if s is None:
            return None
        return good if s >= 65 else mid if s >= 45 else bad

    parts = [
        word(cards["fundamentals"], "strong fundamentals", "average fundamentals", "weak fundamentals"),
        word(cards["growth"], "healthy growth", "moderate growth", "slow growth"),
        word(cards["valuation"], "attractive valuation", "fair valuation", "expensive valuation"),
        word(cards["safety"], "low balance-sheet risk", "moderate risk", "elevated risk"),
    ]
    parts = [p for p in parts if p]
    if not parts:
        return "Not enough data to form a view."
    sentence = ", ".join(parts)
    trend = technical.get("trend")
    if trend in ("Uptrend", "Downtrend"):
        sentence += f"; price in a {trend.lower()}"
    return sentence[0].upper() + sentence[1:] + "."
