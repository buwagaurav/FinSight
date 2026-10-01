"""Question intent for Ask FinSight: decides which tools the model gets and which extra rules it follows.

Keyword rules, not a model call: classification is free, instant and testable, and a wrong guess only narrows the
toolset (company questions keep the core company tools under every intent).
"""
import re

INTENTS = ("company_research", "stock_screening", "company_comparison", "valuation", "filing_question",
           "ipo_research", "technical_analysis", "portfolio_risk", "general_finance")

# Finance terms a "What is ...?" question can ask about (regex fragments)
TERMS = [
    r"p/?e", r"peg", r"p/?b", r"p/?s", r"ev/?ebitda", r"roe", r"roce", r"roa", r"ebitda", r"ebit", r"eps", r"ttm",
    r"cagr", r"xirr", r"irr", r"dcf", r"nav", r"aum", r"free cash flow", r"cash flow", r"operating cash flow",
    r"dividend(?: yield)?", r"ex[- ]dividend(?: date)?", r"record date", r"face value", r"book value",
    r"intrinsic value", r"enterprise value", r"market cap(?:italisation|italization)?", r"(?:small|mid|large)[- ]cap",
    r"blue[- ]chip", r"penny stock", r"free float", r"promoter(?: holding| pledge)?", r"pledg(?:e|ing)",
    r"(?:operating|net|gross|profit|ebitda) margin", r"current ratio", r"quick ratio", r"interest coverage",
    r"debt[- ]to[- ]equity", r"leverage", r"working capital", r"depreciation", r"amorti[sz]ation", r"goodwill",
    r"revenue", r"net profit", r"balance sheet", r"income statement", r"p&l", r"profit and loss", r"beta", r"alpha",
    r"sharpe ratio", r"volatility", r"drawdown", r"liquidity", r"stock split", r"bonus issue", r"buy ?back",
    r"rights issue", r"ipo", r"fpo", r"ofs", r"offer for sale", r"anchor investor", r"lot size", r"price band",
    r"gmp", r"grey market premium", r"listing gain", r"sip", r"swp", r"stp", r"etf", r"reit", r"invit",
    r"mutual fund", r"index fund", r"elss", r"expense ratio", r"sgb", r"sovereign gold bond", r"ppf", r"nps",
    r"ltcg", r"stcg", r"capital gains? tax", r"demat(?: account)?", r"f&o", r"futures?", r"options?",
    r"call option", r"put option", r"short selling", r"margin trading", r"circuit(?: breaker| limit)?",
    r"upper circuit", r"lower circuit", r"sensex", r"nifty(?: 50)?", r"index", r"bull market", r"bear market",
    r"inflation", r"repo rate", r"bond yield", r"yield", r"bond", r"coupon", r"credit rating", r"stop[- ]loss",
    r"moving average", r"rsi", r"macd", r"support and resistance", r"diversification", r"asset allocation",
    r"compounding", r"rupee cost averaging", r"portfolio", r"hedging", r"arbitrage", r"sebi", r"qip", r"fii", r"dii",
]
CONCEPT = (r"^\s*(?:what|how|why) (?:is|are|does|do) (?:a |an |the )?(?:" + "|".join(TERMS) + r")s?"
           r"(?: ratio| rate)?(?: work| mean| calculated| used)?\s*\??\s*$"
           r"|^\s*what does [\w/&. -]{1,30} mean\s*\??\s*$|^\s*define\b|^\s*explain (?:what|how) (?:a |an |the )?(?:"
           + "|".join(TERMS) + r")s?\b")

# First match wins, so the most specific intents come first.
RULES = [
    # Concept questions with nothing else in them: "What is a P/E ratio?", "How does an IPO work?"
    ("general_finance", CONCEPT),
    ("ipo_research", r"\bipos?\b|\bgmp\b|grey market|subscri(?:bed|ption)|allotment|listing gain|\bdrhp\b|\brhp\b|"
                     r"price band|anchor investor"),
    ("portfolio_risk", r"\bportfolio\b|my (?:holdings|stocks|investments)|\bholdings\b|diversif|concentrat|"
                       r"\ballocation\b|\bweights?\b"),
    ("stock_screening", r"\bscreen|\bfind (?:me )?(?:stocks|companies|shares)\b|\blist (?:of )?(?:stocks|companies)\b|"
                        r"\b(?:stocks|companies|shares) (?:with|having|where|that have|trading below|under)\b|"
                        r"\bwhich (?:stocks|companies|shares)\b|\btop \d+ (?:stocks|companies)\b"),
    ("technical_analysis", r"\btechnical|\bmoving average|\bsma\b|\bema\b|\brsi\b|\bmacd\b|\bmomentum\b|\btrend\b|"
                           r"\bsupport\b|\bresistance\b|\bvolatil|\bdrawdown|\bbeta\b|\bchart\b|52[- ]week|"
                           r"price action|breakout"),
    ("filing_question", r"\bfiling|\bannual report|\bannouncement|\bdisclos|\bmanagement (?:said|say|comment)|"
                        r"\bguidance\b|\bconcall|\bearnings call|\bboard meeting|\bauditor|\b10-?[kq]\b|\b8-?k\b|"
                        r"\bquarterly results?\b|\bcorporate action|\border win|\bacquisition"),
    ("valuation", r"\bvaluation|\bvalued\b|\bover ?valued|\bunder ?valued|\bcheap|\bexpensive|\bp/?e\b|\bp/?b\b|"
                  r"\bev/?ebitda|\bmultiple|\bfair value|\bintrinsic|\bscenario|\bdcf\b|\bupside\b|\bdownside\b"),
    ("company_comparison", r"\bcompar|\bvs\.?\b|\bversus\b|\bpeers?\b|\bbetter than\b|\brelative to\b|\bagainst its\b"),
]
_COMPILED = [(name, re.compile(pattern, re.IGNORECASE)) for name, pattern in RULES]

COMPANY = ["search_company", "get_company_snapshot", "get_financials", "calculate"]
TOOLS = {
    "company_research": COMPANY + ["get_valuation", "get_news", "get_announcements", "search_documents",
                                   "compare_companies"],
    "stock_screening": ["run_screen", "compare_companies", "search_company", "calculate"],
    "company_comparison": COMPANY + ["compare_companies", "get_valuation"],
    "valuation": COMPANY + ["get_valuation", "compare_companies"],
    "filing_question": COMPANY + ["get_announcements", "search_documents"],
    "ipo_research": ["get_ipo_data", "search_company", "calculate"],
    "technical_analysis": COMPANY + ["get_technicals"],
    "portfolio_risk": ["portfolio_risk", "search_company", "get_company_snapshot", "calculate"],
    "general_finance": COMPANY,   # in case the question turns out to need a company's data
}

# Extra system-prompt rules per intent, appended to the assistant's base rules.
GUIDANCE = {
    "company_research": "Cover business quality, growth, profitability, balance sheet and the main risks.",
    "stock_screening": "Translate the request into run_screen filters, state each filter you applied and how many "
                       "companies matched. A screen result is a starting list for research, not a recommendation.",
    "company_comparison": "Compare like with like: same metrics, same fiscal year. If the companies' latest years "
                          "differ, or they report in different currencies, say so before comparing.",
    "valuation": "Give a range from the bear/base/bull scenarios with their assumptions, never a single target "
                 "price, and compare current multiples with the company's own history and peers.",
    "filing_question": "Answer from the filings and annual report: quote exact words with their page citation. "
                       "If the documents don't cover it, say so instead of answering from memory.",
    "ipo_research": "Keep official issue data (price band, dates, issue size, subscription) separate from GMP. "
                    "GMP is unofficial grey-market data: label it so every time, give its observed time, and never "
                    "present it as a listing-price forecast.",
    "technical_analysis": "Describe trend, moving averages, returns, volatility and drawdown as history, not "
                          "a prediction. No entry, exit or stop-loss levels.",
    "portfolio_risk": "Use portfolio_risk with the holdings and weights the user gave; if they gave none, ask for "
                      "them. Explain concentration, sector mix, volatility, drawdown and correlation. Describe "
                      "risks and what would reduce them in general terms; no instructions to buy or sell specific "
                      "holdings.",
    "general_finance": "For a concept, explain it in plain language; a made-up illustration must be labelled "
                       "hypothetical and use round numbers. If the question is about a specific company, find it "
                       "with search_company and answer from the company tools. Use no market figures from memory.",
}


def classify(question: str, symbol: str | None = None) -> str:
    """The question's intent. With a company in view, an unmatched question is company research."""
    for name, pattern in _COMPILED:
        if pattern.search(question):
            # "What is ROE?" is a concept question on any page; "What is the ROE?" on a stock page means its ROE
            if name == "general_finance" and symbol and re.search(r"\b(?:is|are|does|do) the ", question, re.IGNORECASE):
                return "company_research"
            return name
    return "company_research" if symbol else "general_finance"


def is_concept(question: str, symbol: str | None = None) -> bool:
    """A question about what a finance term means, which needs no company data: answered in one quick model call."""
    return classify(question, symbol) == "general_finance" and bool(_COMPILED[0][1].search(question))


def tools_for(intent: str, symbol: str | None = None) -> list[str]:
    names = list(TOOLS[intent])
    if symbol and intent in ("stock_screening", "ipo_research", "portfolio_risk"):
        names += [n for n in COMPANY if n not in names]   # the company in view stays reachable
    return names
