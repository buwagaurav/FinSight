from app.analytics import scores


def test_label_thresholds():
    assert scores.label(72) == "Strong"
    assert scores.label(60) == "Stable"
    assert scores.label(60, improving=True) == "Improving"
    assert scores.label(40) == "Watchlist"
    assert scores.label(39) == "Weak"


def row(year, **kw):
    base = {"year": year, "roe_pct": None, "roce_pct": None, "operating_margin_pct": None, "cash_conversion": None,
            "profit_growth_pct": None, "debt_to_equity": None, "interest_coverage": None}
    return {**base, **kw}


def test_strong_company_scores_high_and_explains_itself():
    table = [row(f"FY{y}", roe_pct=25, roce_pct=28, operating_margin_pct=20 + i * 2, cash_conversion=1.1,
                 profit_growth_pct=18, debt_to_equity=0.1, interest_coverage=30)
             for i, y in enumerate(range(21, 26))]
    growth = {"years": 4, "revenue_cagr_pct": 16, "profit_cagr_pct": 17}
    out = scores.compute({"sector": "Technology", "pe": 22}, table, growth,
                         {"trend": "Uptrend", "volatility_1y_pct": 20, "max_drawdown_1y_pct": -10}, [])
    assert out["overall"]["score"] >= 60
    assert out["cards"]["fundamentals"]["label"] == "Strong"
    assert any("Return on equity 25.0% in FY25" == p for p in out["positives"])
    assert out["confidence"] in {"High", "Medium"}


def test_no_data_means_no_score():
    out = scores.compute({"sector": "Technology"}, [], {}, {}, [])
    assert out["overall"] == {"score": None, "label": "Not enough data"}
    assert out["confidence"] == "Low"


def test_roe_label_uses_the_year_the_value_came_from():
    table = [row("FY24", roe_pct=18), row("FY25")]   # latest year has no ROE
    out = scores.compute({"sector": "Technology"}, table, {"years": 1}, {}, [])
    reasons = [r["text"] for r in out["cards"]["fundamentals"]["reasons"]]
    assert "Return on equity 18.0% in FY24" in reasons
