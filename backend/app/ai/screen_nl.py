"""Natural-language screening: a sentence becomes the screener's own filter list, never a hidden query.

The model can only emit fields and operators the screener supports (enforced by the output schema), and it
must spell out how it turned vague words into numbers so the user can see and edit every assumption."""
from typing import Literal

from pydantic import BaseModel, Field

from app import screener
from app.ai import llm

FieldName = Literal[tuple(screener.FIELDS)]  # type: ignore[valid-type]


class NLFilter(BaseModel):
    field: FieldName
    op: Literal[">", ">=", "<", "<="]
    value: float


class ScreenSpec(BaseModel):
    sectors: list[Literal[tuple(screener.SECTORS)]] = Field(  # type: ignore[valid-type]
        description="Restrict to these sectors; empty for all. IT/software -> Technology; banks/NBFCs/insurers -> Financial Services")
    filters: list[NLFilter]
    sort: FieldName | None = Field(description="Field to rank results by, if the request implies an order")
    descending: bool = True
    interpretations: list[str] = Field(
        description="One line per vague term you converted to a number, e.g. \"'low debt' -> Debt / Equity < 0.5\"")
    unsupported: list[str] = Field(
        description="Parts of the request that cannot be expressed with the available fields (e.g. sector, 'improving')")


SYSTEM = f"""You convert an investor's plain-English stock screen into filters for FinSight's screener.

Available fields (all percentages are in percent, e.g. 15 means 15%; market cap is in ₹ crore):
{chr(10).join(f"- {k}: {v}" for k, v in screener.FIELDS.items())}

Sectors you can filter on: {", ".join(screener.SECTORS)}.

Conventions for vague terms (state each one you use in `interpretations`):
- high/good ROE or ROCE: > 15. Excellent: > 20.   - low debt: debt_to_equity < 0.5. Debt-free: < 0.1.
- growing / growth: CAGR > 10. Fast growth: > 15. - cheap / reasonable valuation: pe < 25 (and pe > 0).
- large cap: market_cap_cr > 100000. Mid cap: 20000-100000.  - high dividend: dividend_yield_pct > 2.
Never invent fields. Anything you cannot express goes in `unsupported` instead of being approximated silently."""


def parse(query: str) -> dict:
    spec = llm.structured(ScreenSpec, SYSTEM, query, task="screen")
    return spec.model_dump()
