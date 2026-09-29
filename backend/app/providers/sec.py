"""US-listed companies from SEC EDGAR: the ticker list, annual statements (XBRL "company facts") and filings.

EDGAR is official, free and needs no key. The SEC asks for a User-Agent naming the app and a contact email, and
at most 10 requests a second: https://www.sec.gov/os/accessing-edgar-data

Statements come back in the same shape as the Yahoo provider's (Yahoo line-item names, keyed by fiscal year), so
the fundamentals engine, scores and valuation work unchanged. Amounts are in US dollars; `scale` tells the engine
to show them in $ millions.
"""
import os
import re
import threading
import time
from datetime import date
from html import unescape
from html.parser import HTMLParser

import requests

from app.cache import ttl_cache

SUFFIX = ".US"          # FinSight's marker for a US listing: AAPL.US, BRK-B.US
MILLION = 1e6
USER_AGENT = os.environ.get("FINSIGHT_SEC_USER_AGENT") or "FinSight finsightapp.support@gmail.com"
YEARS = 5
EXCHANGES = {"Nasdaq": "NASDAQ", "NYSE": "NYSE", "CBOE": "Cboe"}   # OTC quotes are left out

_lock = threading.Lock()
_last_request = 0.0


def _get(url: str, **kw) -> requests.Response:
    """GET with the SEC's required User-Agent, spaced to stay under its 10-requests-a-second limit."""
    global _last_request
    with _lock:
        wait = 0.12 - (time.monotonic() - _last_request)
        if wait > 0:
            time.sleep(wait)
        _last_request = time.monotonic()
    r = requests.get(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"}, timeout=30, **kw)
    r.raise_for_status()
    return r


def is_us(symbol: str) -> bool:
    return symbol.strip().upper().endswith(SUFFIX)


def ticker(symbol: str) -> str:
    """AAPL.US -> AAPL (SEC and Yahoo both write share classes with a hyphen: BRK-B)."""
    s = symbol.strip().upper()
    return s[: -len(SUFFIX)] if s.endswith(SUFFIX) else s


@ttl_cache(seconds=24 * 3600)
def tickers() -> dict[str, dict]:
    """Every exchange-listed US company: {ticker: {cik, name, exchange}}."""
    data = _get("https://www.sec.gov/files/company_tickers_exchange.json").json()
    fields = data["fields"]
    out = {}
    for row in data["data"]:
        r = dict(zip(fields, row))
        exchange = EXCHANGES.get(r["exchange"])
        if exchange and r["ticker"] and r["ticker"] not in out:
            out[r["ticker"].upper()] = {"cik": int(r["cik"]), "name": r["name"], "exchange": exchange}
    return out


def lookup(symbol: str) -> dict:
    """{ticker, cik, name, exchange} for a US symbol; LookupError if it isn't an exchange-listed US company."""
    t = ticker(symbol)
    row = tickers().get(t)
    if not row:
        raise LookupError(symbol)
    return {"ticker": t, **row}


def search(query: str, limit: int = 8) -> list[dict]:
    """Ticker matches first (exact, then prefix), then company names containing every word of the query."""
    q = query.strip().upper()
    if not q:
        return []
    words = q.split()
    exact, prefix, named = [], [], []
    for t, r in tickers().items():
        if t == q:
            exact.append((t, r))
        elif len(q) >= 2 and t.startswith(q):
            prefix.append((t, r))
        elif len(q) >= 3 and all(w in r["name"].upper() for w in words):
            named.append((t, r))
    prefix.sort(key=lambda x: len(x[0]))
    named.sort(key=lambda x: (not x[1]["name"].upper().startswith(words[0]), len(x[1]["name"])))
    return [{"symbol": t + SUFFIX, "name": _title(r["name"]), "exchange": r["exchange"], "sector": None}
            for t, r in (exact + prefix + named)[:limit]]


KEEP_UPPER = {"AI", "US", "USA", "N.V.", "NV", "PLC", "LLC", "LP", "L.P.", "ETF", "REIT", "SE", "SA", "AG", "II", "III",
              "IV", "ADR", "BDC", "LTD", "IBM", "AMD", "AT&T", "3M"}


def _title(name: str) -> str:
    """SEC names come with filing-state suffixes ("AMPHENOL CORP /DE/") and often in capitals ("ADOBE INC.");
    show them the way people write them."""
    name = re.sub(r"\s*/[A-Z]{2,3}/?\s*$", "", name.strip())
    if name != name.upper():
        return name

    def word(w: str) -> str:
        core = w.strip(".,")
        if core in KEEP_UPPER or w in KEEP_UPPER or not any(ch.isalpha() for ch in core):
            return w
        return w[0] + w[1:].lower() if w[0].isalpha() else w
    return " ".join(word(w) for w in name.split())


# ---------------------------------------------------------------- annual statements

# Yahoo line-item name -> us-gaap concepts to try, first found wins
CONCEPTS = {
    "income": {
        "Total Revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                          "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet", "RevenuesNetOfInterestExpense"],
        "Operating Income": ["OperatingIncomeLoss"],
        "Interest Expense": ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt"],
        "Net Income Common Stockholders": ["NetIncomeLossAvailableToCommonStockholdersBasic"],
        "Net Income": ["NetIncomeLoss", "ProfitLoss"],
        "Diluted EPS": ["EarningsPerShareDiluted"],
        "Basic EPS": ["EarningsPerShareBasic"],
        "Basic Average Shares": ["WeightedAverageNumberOfSharesOutstandingBasic"],
        "_depreciation": ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization",
                          "DepreciationAmortizationAndAccretionNet", "Depreciation"],
        "_pretax": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"],
    },
    "balance": {
        "Stockholders Equity": ["StockholdersEquity",
                                "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
        "Cash And Cash Equivalents": ["CashAndCashEquivalentsAtCarryingValue",
                                      "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", "Cash"],
        "Total Assets": ["Assets"],
        "_current_assets": ["AssetsCurrent"],
        "_current_liabilities": ["LiabilitiesCurrent"],
        "_long_term_debt": ["LongTermDebt", "LongTermDebtAndCapitalLeaseObligations"],   # includes current portion
        "_long_term_debt_noncurrent": ["LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligationsNoncurrent"],
        "_long_term_debt_current": ["LongTermDebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent", "DebtCurrent"],
        "_short_term_debt": ["ShortTermBorrowings", "CommercialPaper", "OtherShortTermBorrowings"],
    },
    "cashflow": {
        "Operating Cash Flow": ["NetCashProvidedByUsedInOperatingActivities",
                                "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
        "_capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
        "_dividends": ["PaymentsOfDividendsCommonStock", "PaymentsOfDividends", "PaymentsOfOrdinaryDividends",
                       "DividendsCommonStockCash", "DividendsCommonStock"],   # declared amounts as a last resort
    },
}
ANNUAL_FORMS = {"10-K", "10-K/A", "10-KT"}


@ttl_cache(seconds=6 * 3600)
def company_facts(cik: int) -> dict:
    return _get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json").json()


def _days(r: dict) -> int | None:
    if "start" not in r:
        return None
    return (date.fromisoformat(r["end"]) - date.fromisoformat(r["start"])).days


def _annual_values(gaap: dict, concept: str) -> dict[str, float]:
    """{period_end: value} from annual reports: full-year amounts for flows, year-end amounts for balances.
    A year restated in a later report takes the latest filed figure."""
    units = (gaap.get(concept) or {}).get("units") or {}
    rows = units.get("USD") or units.get("USD/shares") or units.get("shares") or []
    best: dict[str, tuple[str, float]] = {}
    for r in rows:
        if r.get("form") not in ANNUAL_FORMS:
            continue
        days = _days(r)
        if days is not None and not 340 <= days <= 380:
            continue   # quarterly or odd-length periods reported inside the annual filing
        if r["end"] not in best or r["filed"] >= best[r["end"]][0]:
            best[r["end"]] = (r["filed"], float(r["val"]))
    return {end: v for end, (_, v) in best.items()}


def _split_adjusted_shares(gaap: dict, ends: list[str]) -> dict[str, float]:
    """Average share counts on today's share basis. Reports filed before a stock split carry pre-split counts
    (NVIDIA's 10-for-1 in 2024 makes older years look like a tenth of the shares), but every annual report
    restates the prior years on its own basis, so ratios between neighbouring years taken from the same report
    are split-free. Chaining them back from the latest year puts every year on the latest basis."""
    concept = CONCEPTS["income"]["Basic Average Shares"][0]
    by_report: dict[str, dict[str, float]] = {}
    filed: dict[str, str] = {}
    for r in ((gaap.get(concept) or {}).get("units") or {}).get("shares") or []:
        if r.get("form") in ANNUAL_FORMS and (_days(r) or 0) >= 340 and (_days(r) or 0) <= 380:
            report = r.get("accn") or r["filed"]   # accession number identifies the report
            by_report.setdefault(report, {})[r["end"]] = float(r["val"])
            filed[report] = r["filed"]
    latest = _annual_values(gaap, concept)
    if not ends or ends[-1] not in latest:
        return latest
    out = {ends[-1]: latest[ends[-1]]}
    for older, newer in zip(reversed(ends[:-1]), reversed(ends[1:])):
        both = [a for a, vals in by_report.items() if older in vals and newer in vals and vals[newer]]
        if newer in out and both:
            a = max(both, key=lambda x: filed[x])
            out[older] = out[newer] * by_report[a][older] / by_report[a][newer]
        elif older in latest:
            out[older] = latest[older]
    return out


def _first(gaap: dict, concepts: list[str]) -> dict[str, float]:
    """Values of the first concept that has any, filled in from the next ones for years it lacks (companies
    switch concepts over time, e.g. SalesRevenueNet -> RevenueFromContractWithCustomer... in 2018)."""
    merged: dict[str, float] = {}
    for c in concepts:
        for end, v in _annual_values(gaap, c).items():
            merged.setdefault(end, v)
    return merged


def _fiscal_year_ends(gaap: dict) -> list[str]:
    """Year-end dates of the latest YEARS annual reports, from the net income series (every filer reports it)."""
    ends = set(_first(gaap, CONCEPTS["income"]["Net Income"])) | set(_first(gaap, CONCEPTS["income"]["Total Revenue"]))
    return sorted(ends)[-YEARS:]


def _label(end: str) -> str:
    """US companies name a fiscal year after the calendar year it ends in (Apple's FY25 ends Sept 2025,
    NVIDIA's FY26 ends Jan 2026)."""
    return f"FY{end[2:4]}"


def annual_statements(symbol: str) -> dict:
    """Annual statements for a US company in the Yahoo provider's shape. LookupError if EDGAR has no
    US-GAAP annual reports for it (e.g. foreign companies filing 20-F under IFRS)."""
    cik = lookup(symbol)["cik"]
    return statements_from_facts(company_facts(cik), cik, symbol)


def statements_from_facts(facts: dict, cik: int, symbol: str = "") -> dict:
    """Statements from one company's XBRL facts, as served by the API or stored in the bulk companyfacts.zip."""
    gaap = facts.get("facts", {}).get("us-gaap", {})
    ends = _fiscal_year_ends(gaap)
    if not ends:
        raise LookupError(f"No US-GAAP annual reports on EDGAR for {symbol or cik}")

    series = {stmt: {name: _first(gaap, concepts) for name, concepts in items.items()}
              for stmt, items in CONCEPTS.items()}
    series["income"]["Basic Average Shares"] = _split_adjusted_shares(gaap, ends)
    # reported EPS isn't restated for splits either; the engine derives EPS from profit and adjusted shares
    out: dict = {"income": {}, "balance": {}, "cashflow": {}, "converted_from": None, "scale": MILLION,
                 "source": {"name": "SEC EDGAR (10-K filings)",
                            "url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=10-K"}}
    for end in ends:
        label = _label(end)
        v = {stmt: {name: s.get(end) for name, s in items.items()} for stmt, items in series.items()}
        inc, bal, cf = v["income"], v["balance"], v["cashflow"]

        if inc["Operating Income"] is not None and inc["_depreciation"] is not None:
            inc["EBITDA"] = inc["Operating Income"] + inc["_depreciation"]
        # banks and insurers don't report operating income; pre-tax profit plus interest paid is the closest EBIT
        if inc["Operating Income"] is None and inc["_pretax"] is not None:
            inc["EBIT"] = inc["_pretax"] + (inc["Interest Expense"] or 0)
        else:
            inc["EBIT"] = inc["Operating Income"]

        if bal["_long_term_debt"] is not None:
            debt = bal["_long_term_debt"]
        elif bal["_long_term_debt_noncurrent"] is not None or bal["_long_term_debt_current"] is not None:
            debt = (bal["_long_term_debt_noncurrent"] or 0) + (bal["_long_term_debt_current"] or 0)
        else:
            debt = None
        if debt is not None or bal["_short_term_debt"] is not None:
            bal["Total Debt"] = (debt or 0) + (bal["_short_term_debt"] or 0)
        if bal["_current_assets"] is not None and bal["_current_liabilities"] is not None:
            bal["Working Capital"] = bal["_current_assets"] - bal["_current_liabilities"]

        ocf, capex = cf["Operating Cash Flow"], cf["_capex"]
        if capex is not None:
            cf["Capital Expenditure"] = -capex                 # Yahoo's sign convention: outflows negative
            if ocf is not None:
                cf["Free Cash Flow"] = ocf - capex
        if cf["_dividends"] is not None:
            cf["Cash Dividends Paid"] = -cf["_dividends"]

        for stmt, row in (("income", inc), ("balance", bal), ("cashflow", cf)):
            out[stmt][label] = {"period_end": end, **{k: x for k, x in row.items() if not k.startswith("_")}}
    return out


def shares_outstanding(symbol: str) -> float | None:
    """Latest share count from the cover page of the company's most recent report."""
    return shares_from_facts(company_facts(lookup(symbol)["cik"]))


def shares_from_facts(facts: dict) -> float | None:
    """Shares outstanding now, from the freshest reliable figure:
    1. the cover page of the latest report (all classes; companies with several share classes often report
       these per class only, which the facts API leaves out),
    2. shares outstanding on the latest balance sheet,
    3. the latest reported average share count.
    Figures more than 15 months older than the company's latest financial report are ignored, since they would
    miss later buybacks, issues and splits (Berkshire's only figures are from 2011 and 2015)."""
    f = facts.get("facts", {})
    gaap = f.get("us-gaap", {})
    latest_report = max((r["end"] for c in ("NetIncomeLoss", "ProfitLoss", "Revenues")
                         for r in ((gaap.get(c) or {}).get("units") or {}).get("USD") or []), default=None)
    if not latest_report:
        return None
    cutoff = date.fromisoformat(latest_report).toordinal() - 460

    def fresh(rows):
        rows = [r for r in rows if r.get("val") and date.fromisoformat(r["end"]).toordinal() >= cutoff]
        return rows

    cover = fresh(((f.get("dei", {}).get("EntityCommonStockSharesOutstanding") or {}).get("units") or {}).get("shares") or [])
    if cover:
        last = max(r["end"] for r in cover)
        return sum(float(r["val"]) for r in cover if r["end"] == last)   # one row per share class
    for concept in ("CommonStockSharesOutstanding", "WeightedAverageNumberOfSharesOutstandingBasic"):
        rows = fresh(((gaap.get(concept) or {}).get("units") or {}).get("shares") or [])
        if rows:
            return float(max(rows, key=lambda r: (r["end"], r["filed"]))["val"])
    return None


def latest_balance(facts: dict) -> dict:
    """Equity and total debt from the most recent balance sheet (latest 10-Q or 10-K), for ratios quoted
    "today" such as P/B and debt/equity. {} if not reported."""
    gaap = facts.get("facts", {}).get("us-gaap", {})

    def by_end(concepts):
        vals: dict[str, tuple[str, float]] = {}
        for c in concepts:
            for r in ((gaap.get(c) or {}).get("units") or {}).get("USD") or []:
                if r.get("form") in ANNUAL_FORMS | {"10-Q", "10-Q/A"} and "start" not in r:
                    if r["end"] not in vals or r["filed"] > vals[r["end"]][0]:
                        vals[r["end"]] = (r["filed"], float(r["val"]))
            if vals:
                break   # first concept the company uses
        return {end: v for end, (_, v) in vals.items()}

    b = CONCEPTS["balance"]
    equity = by_end(b["Stockholders Equity"])
    if not equity:
        return {}
    end = max(equity)
    lt, ltn, ltc, st = (by_end(b[k]).get(end) for k in
                        ("_long_term_debt", "_long_term_debt_noncurrent", "_long_term_debt_current", "_short_term_debt"))
    debt = lt if lt is not None else ((ltn or 0) + (ltc or 0) if ltn is not None or ltc is not None else None)
    total_debt = (debt or 0) + (st or 0) if debt is not None or st is not None else None
    return {"as_of": end, "equity": equity[end], "total_debt": total_debt}


def ttm_net_income(facts: dict) -> tuple[float, str] | None:
    """Net income for the last twelve months and the date it runs to: the latest fiscal year, rolled forward
    with the latest 10-Q (this year's year-to-date minus the same period last year, both from that 10-Q)."""
    gaap = facts.get("facts", {}).get("us-gaap", {})
    concept = next((c for c in CONCEPTS["income"]["Net Income"] if c in gaap), None)
    if not concept:
        return None
    annual = _annual_values(gaap, concept)
    if not annual:
        return None
    fy_end = max(annual)
    rows = (gaap[concept].get("units") or {}).get("USD") or []
    quarterly = [r for r in rows if r.get("form") in ("10-Q", "10-Q/A") and "start" in r and r["end"] > fy_end
                 and r["start"] > fy_end]
    if not quarterly:
        return annual[fy_end], fy_end
    latest = max(quarterly, key=lambda r: (r["end"], _days(r) or 0, r["filed"]))   # longest year-to-date span
    ytd = latest["val"]
    prior_end = f"{int(latest['end'][:4]) - 1}{latest['end'][4:]}"
    prior = [r for r in rows if r.get("accn") == latest.get("accn") and "start" in r
             and abs((date.fromisoformat(r["end"]) - date.fromisoformat(prior_end)).days) <= 7
             and abs((_days(r) or 0) - (_days(latest) or 0)) <= 7]
    if not prior:
        return annual[fy_end], fy_end
    return annual[fy_end] + ytd - prior[0]["val"], latest["end"]


# ---------------------------------------------------------------- company details and filings

@ttl_cache(seconds=6 * 3600)
def submissions(cik: int) -> dict:
    return _get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json").json()


def industry(symbol: str) -> dict:
    """SEC's industry classification, mapped to the sector names used elsewhere in FinSight."""
    s = submissions(lookup(symbol)["cik"])
    sic = int(s.get("sic") or 0)
    return {"sic": sic, "industry": (s.get("sicDescription") or "").title() or None, "sector": _sector(sic),
            "website": s.get("website") or None}


SIC_SECTORS = [   # (from, to, sector): broad ranges first, narrower ranges after them win
    (100, 999, "Consumer Defensive"), (1000, 1499, "Basic Materials"), (1300, 1399, "Energy"),
    (1500, 1799, "Industrials"), (2000, 2199, "Consumer Defensive"), (2200, 2399, "Consumer Cyclical"),
    (2400, 2499, "Basic Materials"), (2500, 2599, "Consumer Cyclical"), (2600, 2699, "Basic Materials"),
    (2700, 2799, "Communication Services"), (2800, 2899, "Basic Materials"), (2830, 2836, "Healthcare"),
    (2840, 2844, "Consumer Defensive"), (2900, 2999, "Energy"), (3000, 3099, "Industrials"),
    (3100, 3199, "Consumer Cyclical"), (3200, 3399, "Basic Materials"), (3400, 3599, "Industrials"),
    (3570, 3579, "Technology"), (3600, 3699, "Technology"), (3630, 3639, "Consumer Cyclical"),
    (3700, 3799, "Industrials"), (3710, 3716, "Consumer Cyclical"), (3800, 3899, "Technology"),
    (3840, 3851, "Healthcare"), (3900, 3999, "Consumer Cyclical"), (4000, 4799, "Industrials"),
    (4800, 4899, "Communication Services"), (4900, 4999, "Utilities"), (5000, 5199, "Industrials"),
    (5122, 5122, "Healthcare"), (5140, 5149, "Consumer Defensive"), (5200, 5999, "Consumer Cyclical"),
    (5400, 5499, "Consumer Defensive"), (5910, 5912, "Healthcare"), (6000, 6499, "Financial Services"),
    (6500, 6599, "Real Estate"), (6700, 6799, "Financial Services"), (6798, 6798, "Real Estate"),
    (7000, 7299, "Consumer Cyclical"), (7300, 7399, "Industrials"), (7370, 7379, "Technology"),
    (7800, 7899, "Communication Services"), (7900, 7999, "Consumer Cyclical"), (8000, 8099, "Healthcare"),
    (8200, 8299, "Consumer Defensive"), (8700, 8799, "Industrials"), (8730, 8734, "Healthcare"),
]
# Not operating businesses: blank-check shells (SPACs), funds, trusts
NON_OPERATING_SIC = {6770, 6221, 6722, 6726, 6792}


def _sector(sic: int) -> str | None:
    """SIC code -> the sector names used across FinSight (the screener's sector filter)."""
    matches = [name for lo, hi, name in SIC_SECTORS if lo <= sic <= hi]
    return matches[-1] if matches else None


# Forms investors care about; the rest (insider trades, share registrations, prospectus pages...) are routine
MATERIAL = {
    "10-K": "Annual report", "10-K/A": "Annual report (amended)", "10-Q": "Quarterly report",
    "8-K": "Current report", "8-K/A": "Current report (amended)", "DEF 14A": "Proxy statement",
    "20-F": "Annual report (foreign issuer)", "6-K": "Foreign issuer report", "40-F": "Annual report (Canadian issuer)",
    "S-1": "Registration statement", "SC 13D": "Activist / 5%+ stake", "SC TO-T": "Tender offer",
}
EIGHT_K_ITEMS = {
    "1.01": "material agreement", "1.02": "agreement terminated", "2.01": "acquisition or disposal",
    "2.02": "results", "2.03": "new debt", "2.05": "restructuring costs", "2.06": "impairment",
    "3.01": "listing notice", "4.01": "auditor change", "4.02": "restatement", "5.01": "change in control",
    "5.02": "leadership change", "5.03": "bylaw change", "5.07": "shareholder vote", "7.01": "regulation FD disclosure",
    "8.01": "other event",
}


def filings(symbol: str, limit: int = 30) -> list[dict]:
    """Latest filings, newest first, in the same shape as NSE announcements."""
    info = lookup(symbol)
    recent = submissions(info["cik"])["filings"]["recent"]
    out = []
    for i in range(min(len(recent["form"]), 400)):
        form = recent["form"][i]
        accession = recent["accessionNumber"][i]
        items = [EIGHT_K_ITEMS[x] for x in re.split(r"[,\s]+", recent.get("items", [""] * (i + 1))[i] or "")
                 if x in EIGHT_K_ITEMS and x != "9.01"]
        doc = recent["primaryDocument"][i]
        url = (f"https://www.sec.gov/Archives/edgar/data/{info['cik']}/{accession.replace('-', '')}/{doc}"
               if doc else f"https://www.sec.gov/Archives/edgar/data/{info['cik']}/{accession.replace('-', '')}/")
        description = recent.get("primaryDocDescription", [""] * (i + 1))[i] or ""
        text = "; ".join(items).capitalize() if items else (description if description.upper() != form else "")
        accepted = recent.get("acceptanceDateTime", [None] * (i + 1))[i]
        out.append({
            "id": accession,
            "symbol": info["ticker"] + SUFFIX,
            "company": _title(info["name"]),
            "category": f"{form}: {MATERIAL[form]}" if form in MATERIAL else form,
            "text": text or MATERIAL.get(form, form),
            "published": accepted[:19] + "+00:00" if accepted else recent["filingDate"][i],   # SEC gives UTC
            "pdf_url": url,
            "pdf_size": None,
            "routine": form not in MATERIAL,
            "source": {"name": f"SEC EDGAR {form}", "url": url},
        })
        if len(out) >= limit:
            break
    return out


def download_document(url: str, max_bytes: int = 15_000_000) -> tuple[bytes, str]:
    """A filing's primary document and its media type. Only sec.gov archive URLs are fetched."""
    if not url.startswith("https://www.sec.gov/Archives/"):
        raise ValueError("Only SEC EDGAR archive documents are fetched")
    r = _get(url)
    if len(r.content) > max_bytes:
        raise ValueError("Document too large to summarise")
    return r.content, r.headers.get("content-type", "text/html").split(";")[0]


class _Text(HTMLParser):
    """Visible text of an HTML filing (skips scripts, styles and inline-XBRL metadata)."""
    SKIP = {"script", "style", "ix:header", "head", "title"}
    BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "table", "section"}

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.skipping = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skipping += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skipping:
            self.skipping -= 1

    def handle_data(self, data):
        if not self.skipping:
            self.parts.append(data)


def html_text(content: bytes) -> str:
    parser = _Text()
    parser.feed(content.decode("utf-8", errors="replace"))
    text = unescape("".join(parser.parts)).replace("\xa0", " ")
    return re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t]+", " ", text)).strip()


def filing_text(filing: dict, max_chars: int) -> str:
    """Readable text of a filing: its main document plus, for 8-Ks, the press release or other exhibit 99
    that usually carries the substance (the 8-K itself is often a one-paragraph cover)."""
    content, media = download_document(filing["pdf_url"])
    text = html_text(content) if "html" in media or filing["pdf_url"].endswith((".htm", ".html")) else ""
    if filing["category"].startswith("8-K"):
        folder = filing["pdf_url"].rsplit("/", 1)[0]
        try:
            items = _get(f"{folder}/index.json").json()["directory"]["item"]
            exhibits = [i["name"] for i in items if re.search(r"ex[-_]?99", i["name"], re.I) and i["name"].endswith((".htm", ".html"))]
            for name in exhibits[:2]:
                ex, _ = download_document(f"{folder}/{name}")
                text += f"\n\n--- Exhibit {name} ---\n" + html_text(ex)
        except Exception:
            pass   # the cover document alone is still worth summarising
    return text[:max_chars]
