"""Data-accuracy check: FinSight's figures versus the results each company officially filed with NSE (XBRL).

The assistant eval (run_eval.py) tests whether the AI repeats FinSight's data faithfully. This tests the
data itself: revenue, net profit and EPS from our provider (Yahoo) against the audited, consolidated
annual results in the company's own XBRL filing.

Run:  cd backend && ../.venv/bin/python -m eval.check_data
"""
import json
import re
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

from app import research
from app.providers import nse
from eval.build_questions import COMPANIES

CACHE = Path(__file__).resolve().parent.parent / "data" / "xbrl"
OUT = Path(__file__).resolve().parent / "data_check.json"
TOLERANCE_PCT = 2.0
TAGS = {
    "revenue": ["RevenueFromOperations", "Income"],
    "net_profit": ["ProfitOrLossAttributableToOwnersOfParent", "ProfitLossForPeriod", "ProfitLossForThePeriod"],
    "eps": ["BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations", "BasicEarningsLossPerShareFromContinuingOperations"],
}


def _xbrl(url: str) -> str:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / url.rsplit("/", 1)[-1]
    if not path.exists():
        r = requests.get(url, headers={"User-Agent": nse.HEADERS["User-Agent"]}, timeout=30)
        r.raise_for_status()
        path.write_text(r.text)
    return path.read_text()


def _headline_contexts(xml: str) -> list[str]:
    """Context ids without a segment/dimension, i.e. the headline columns of the results table."""
    return [m.group(1) for m in re.finditer(r'<xbrli:context id="([^"]+)">(.*?)</xbrli:context>', xml, re.S)
            if "segment" not in m.group(2)]


def _full_year_context(xml: str) -> str | None:
    """The annual column. NSE's annual XBRL often mislabels its period dates (the full-year column can be
    dated as the last quarter), so pick the headline column with the largest revenue: a full year always
    exceeds any quarter within it."""
    best, best_rev = None, -1.0
    headline = set(_headline_contexts(xml))
    for tag in TAGS["revenue"]:
        for m in re.finditer(rf'<[\w-]+:{tag}\b[^>]*contextRef="([^"]+)"[^>]*>([^<]+)<', xml):
            if m.group(1) in headline and float(m.group(2)) > best_rev:
                best, best_rev = m.group(1), float(m.group(2))
        if best:
            return best
    return None


def _value(xml: str, tags: list[str], context: str) -> float | None:
    for tag in tags:
        m = re.search(rf'<[\w-]+:{tag}\b[^>]*contextRef="{re.escape(context)}"[^>]*>([^<]+)<', xml)
        if m:
            return float(m.group(1))
    return None


def filed_results(symbol: str) -> dict[str, dict]:
    """{period_end_iso: {revenue, net_profit, eps, url}} from audited consolidated annual filings."""
    rows = nse._get(f"/api/corporates-financial-results?index=equities&symbol={symbol}&period=Annual")
    out = {}
    for r in rows:
        if r.get("consolidated") != "Consolidated" or r.get("audited") != "Audited" \
                or not str(r.get("xbrl", "")).endswith(".xml"):
            continue  # older filings often have no XBRL ("-")
        end = datetime.strptime(r["toDate"], "%d-%b-%Y").date().isoformat()
        if end in out:
            continue  # newest filing first; keep it (later revisions supersede)
        try:
            xml = _xbrl(r["xbrl"])
        except requests.RequestException:
            continue
        ctx = _full_year_context(xml)
        if not ctx:
            continue
        vals = {k: _value(xml, tags, ctx) for k, tags in TAGS.items()}
        out[end] = {"revenue": vals["revenue"] / 1e7 if vals["revenue"] else None,
                    "net_profit": vals["net_profit"] / 1e7 if vals["net_profit"] else None,
                    "eps": vals["eps"], "url": r["xbrl"]}
    return out


CLEAN_RATIOS = (1.5, 2, 3, 4, 5, 6, 8, 10, 20)


def _split_factor_after(symbol: str, period_end: str) -> float:
    """Filed EPS is as originally reported; FinSight restates it for later splits and bonus issues.
    Returns the product of recorded splits after the period (1.0 if none)."""
    splits = yf.Ticker(symbol).splits
    if splits.empty:
        return 1.0
    after = splits[splits.index.tz_localize(None) > pd.Timestamp(period_end)]
    return float(after.prod()) if not after.empty else 1.0


def _clean_ratio(ratio: float) -> float | None:
    return next((c for c in CLEAN_RATIOS if abs(ratio / c - 1) < 0.02), None)


def check(base: str) -> list[dict]:
    r = research.company_report(base)
    symbol = r["profile"]["symbol"]
    bank = r["profile"]["sector"] == "Financial Services"
    filed = filed_results(base)
    rows = []
    for y in r["financials"]["years"]:
        f = filed.get(y["period_end"])
        if not f:
            continue
        for metric in ("revenue", "net_profit", "eps"):
            if metric == "revenue" and bank:
                continue  # lenders' "revenue" differs by definition (interest income vs total income)
            ours, theirs = y.get(metric), f.get(metric)
            if ours is None or theirs is None or theirs == 0:
                continue
            note = ""
            if metric == "eps":
                factor = _split_factor_after(symbol, y["period_end"])
                adjusted = theirs / factor
                ratio = _clean_ratio(theirs / ours) if ours > 0 and theirs > 0 else None
                if abs(ours / adjusted - 1) * 100 > TOLERANCE_PCT and factor > 1 and ratio:
                    # The provider's split history can be incomplete (e.g. a bonus recorded as a plain split);
                    # a clean ratio after a recorded corporate action is a restatement, not an error.
                    adjusted, note = theirs / ratio, f"restated for corporate actions (÷{ratio:g})"
                elif factor > 1:
                    note = f"restated for recorded splits (÷{factor:g})"
                theirs = adjusted
            diff = (ours - theirs) / abs(theirs) * 100
            ok = bool(abs(diff) <= TOLERANCE_PCT)
            if not ok and metric == "eps" and ours > 0 and _clean_ratio(abs(theirs / ours)):
                note = "clean multiple with no corporate action on record: check the XBRL filing"
            rows.append({"symbol": base, "year": y["year"], "metric": metric, "finsight": round(float(ours), 2),
                         "filed": round(float(theirs), 2), "diff_pct": round(float(diff), 2),
                         "ok": ok, "note": note, "filing": f["url"]})
    return rows


def main():
    results, errors = [], {}
    for base in COMPANIES:
        try:
            rows = check(base)
            results.extend(rows)
            bad = [f"{x['year']} {x['metric']} {x['diff_pct']:+.1f}%" + (f" ({x['note']})" if x["note"] else "")
                   for x in rows if not x["ok"]]
            print(f"{base:<11} {len(rows):>2} checks  {'all within ' + str(TOLERANCE_PCT) + '%' if not bad else 'MISMATCH: ' + ', '.join(bad)}")
        except Exception as e:
            errors[base] = str(e)
            print(f"{base:<11} error: {e}")
    by_metric = {m: {"checks": sum(r["metric"] == m for r in results),
                     "within_tolerance": sum(r["metric"] == m and r["ok"] for r in results)} for m in TAGS}
    summary = {"run_at": datetime.now().isoformat(timespec="seconds"), "tolerance_pct": TOLERANCE_PCT,
               "checks": len(results), "within_tolerance": sum(r["ok"] for r in results), "by_metric": by_metric,
               "errors": errors}
    OUT.write_text(json.dumps({"summary": summary, "rows": results}, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
