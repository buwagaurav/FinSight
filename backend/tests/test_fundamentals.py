import pytest

from app.analytics import fundamentals as f

CR = 1e7  # one crore


def statements(years: dict) -> dict:
    """Yahoo-shaped statements from {fy: (revenue, operating_income, net_income, equity, debt, ocf)} in crore."""
    out = {"income": {}, "balance": {}, "cashflow": {}}
    for fy, (rev, op, ni, eq, debt, ocf) in years.items():
        out["income"][fy] = {"period_end": f"20{fy[-2:]}-03-31", "Total Revenue": rev * CR, "Operating Income": op * CR,
                             "Net Income": ni * CR, "Basic Average Shares": 1e8, "Interest Expense": 10 * CR}
        out["balance"][fy] = {"Stockholders Equity": None if eq is None else eq * CR, "Total Debt": debt * CR}
        out["cashflow"][fy] = {"Operating Cash Flow": ocf * CR}
    return out


def test_cagr():
    assert f.cagr(100, 200, 1) == pytest.approx(100)
    assert f.cagr(100, 121, 2) == pytest.approx(10)
    for bad in [(0, 100, 3), (-5, 100, 3), (100, -5, 3), (100, 200, 0), (None, 100, 3)]:
        assert f.cagr(*bad) is None


def test_build_table_converts_to_crore_and_derives_ratios():
    table = f.build_table(statements({"FY24": (1000, 200, 150, 1000, 200, 180),
                                      "FY25": (1100, 240, 165, 1200, 100, 170)}))
    assert [r["year"] for r in table] == ["FY24", "FY25"]
    last = table[-1]
    assert last["revenue"] == pytest.approx(1100)
    assert last["operating_margin_pct"] == pytest.approx(240 / 1100 * 100)
    assert last["roe_pct"] == pytest.approx(165 / 1100 * 100)          # on average equity (1000 + 1200) / 2
    assert last["debt_to_equity"] == pytest.approx(100 / 1200)
    assert last["interest_coverage"] == pytest.approx(24)
    assert last["revenue_growth_pct"] == pytest.approx(10)
    assert last["eps"] == pytest.approx(165 * CR / 1e8)                 # derived from profit ÷ shares
    assert table[0]["revenue_growth_pct"] is None


def test_negative_equity_blanks_meaningless_ratios():
    table = f.build_table(statements({"FY24": (500, -50, -80, -200, 900, 10)}))
    row = table[0]
    assert row["roe_pct"] is None and row["roce_pct"] is None and row["debt_to_equity"] is None
    checks = f.data_checks(table, {})
    assert any("zero or negative in FY24" in c for c in checks)


def test_empty_oldest_year_is_dropped():
    s = statements({"FY25": (100, 10, 8, 50, 0, 9)})
    s["income"]["FY21"] = {"period_end": "2021-03-31"}
    assert [r["year"] for r in f.build_table(s)] == ["FY25"]


def test_growth_summary():
    table = f.build_table(statements({"FY23": (100, 10, 10, 50, 0, 9), "FY24": (110, 11, 11, 55, 0, 9),
                                      "FY25": (121, 12, 12.1, 60, 0, 9)}))
    g = f.growth_summary(table)
    assert g["years"] == 2 and g["from"] == "FY23" and g["to"] == "FY25"
    assert g["revenue_cagr_pct"] == pytest.approx(10)
    assert f.growth_summary(table[:1]) == {}


def test_data_checks_flags_equity_jump_roe_disagreement_and_short_history():
    table = f.build_table(statements({"FY24": (100, 10, 10, 100, 0, 9), "FY25": (100, 10, 10, 300, 0, 9)}))
    checks = " ".join(f.data_checks(table, {"roe_ttm_pct": 40.0}, converted_from="USD"))
    assert "Equity rose 3.0x in FY25" in checks
    assert "Sources disagree on ROE" in checks
    assert "converted to ₹" in checks
    assert "Only 2 years" in checks


def test_equity_growth_from_retained_profit_is_not_flagged():
    # equity doubles each year, fully explained by that year's profit: a fast grower, not a merger
    table = f.build_table(statements({"FY24": (1000, 600, 500, 500, 0, 500), "FY25": (2000, 1200, 1000, 1400, 0, 900)}))
    assert not any("Equity rose" in c for c in f.data_checks(table, {}))


def test_technicals_use_the_listing_currency():
    from app.analytics import technicals
    history = [{"date": f"2025-{1 + i // 28:02d}-{1 + i % 28:02d}", "close": 100.0 + i} for i in range(250)]
    assert "($" in technicals.summarize(history, "$")["reasons"][0]
    assert "(₹" in technicals.summarize(history)["reasons"][0]
