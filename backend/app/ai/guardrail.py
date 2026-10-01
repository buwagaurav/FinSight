"""Keeps Ask FinSight to finance. Two layers:

1. precheck(): free keyword rules that refuse plainly off-topic questions and prompt-injection attempts before any
   model call (so they cost nothing and don't use the user's AI allowance).
2. skills/finance-guardrail/SKILL.md: the scope rules the model follows for everything else. When it decides a
   question is out of scope it replies OUT_OF_SCOPE, which is_refusal() spots and replaces with REFUSAL.
"""
import re
from pathlib import Path

SKILL_PATH = Path(__file__).parent / "skills" / "finance-guardrail" / "SKILL.md"
SENTINEL = "OUT_OF_SCOPE"
REFUSAL = ("I can only help with stocks, markets and finance: companies, financials, valuation, filings, IPOs, "
           "screening, portfolio risk and investing concepts. Try asking about a company or a finance topic.")


def skill_text() -> str:
    """The SKILL.md body (without its front matter), as sent to the model."""
    text = SKILL_PATH.read_text(encoding="utf-8")
    return re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S).strip()


FINANCE = re.compile(
    r"\b(stocks?|shares?|growth|equit|market|nifty|sensex|nse|bse|sebi|sec\b|ipo|gmp|invest|portfolio|fund|etf|sip\b|"
    r"bonds?|dividend|earnings|revenue|sales|profit|loss|margin|ebitda|eps\b|p/?e\b|p/?b\b|roe|roce|cagr|debt|"
    r"valuation|valued|price|returns?|risk|volatil|trading|trader|broker|demat|tax|inflation|interest rate|"
    r"repo rate|rbi\b|fed\b|economy|gdp|rupee|dollar|currency|forex|gold|commodit|crypto|bitcoin|bank|loan|"
    r"finance|financial|balance sheet|cash ?flow|annual report|filing|quarter|results?|company|companies|sector|"
    r"industry|business|ticker|bull|bear|hedge|option|futures|derivative|capital|asset|wealth|money|salary|"
    r"saving|budget|insurance|pension|retire)",
    re.IGNORECASE)

OFF_TOPIC = re.compile(
    r"\b(recipes?|cook(?:ing)?|bake|weather|forecast for (?:today|tomorrow)|lyrics|poems?|poetry|jokes?|"
    r"short stor(?:y|ies)|bedtime stor(?:y|ies)|songs?|essays?|cover letter|homework|translat\w*|symptoms?|diagnos\w*|medicines?|"
    r"workout|diet|girlfriend|boyfriend|dating|movies?|tv shows?|netflix|video games?|anime|horoscope|"
    r"(?:write|debug|fix|refactor) (?:me )?(?:a |the |this |my )?(?:code|program|script|function|app|website)|"
    r"python|javascript|typescript|java\b|c\+\+|html|css|sql query|regex)\b",
    re.IGNORECASE)

INJECTION = re.compile(
    r"ignore (?:all |any |the |your )?(?:previous|prior|above|earlier) (?:instructions|rules|prompts?)|"
    r"(?:reveal|show|print|repeat) (?:me )?(?:your|the) (?:system )?(?:prompt|instructions|rules)|"
    r"\bsystem prompt\b|\bjailbreak|you are now (?:a|an|my)\b|pretend (?:to be|you are)|"
    r"from now on,? you (?:are|will)",
    re.IGNORECASE)


def precheck(question: str, symbol: str | None = None) -> bool:
    """True when the question should be refused without asking the model: an attempt to change the assistant's
    rules, or a request for something plainly unrelated to finance with nothing financial in it. With a company in
    view, short questions often don't name anything financial ("how are the movies doing?" on PVR), so only
    injection attempts are refused here and the model judges the rest."""
    if INJECTION.search(question):
        return True
    return not symbol and bool(OFF_TOPIC.search(question)) and not FINANCE.search(question)


def is_refusal(answer: str) -> bool:
    """The model's out-of-scope reply, allowing for stray formatting around the sentinel."""
    return answer.strip().strip("`*_.\"' \n").upper().startswith(SENTINEL)
