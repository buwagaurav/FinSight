"""Numeric grounding check: every figure in an answer must be traceable to a tool result.

This is FinSight's guard against a language model inventing or mis-copying financial numbers.
A figure passes if some tool-returned value rounds to it at the precision the answer used.
"""
import json
import re

# ₹1,23,456.78 | 48.7% | 2.67 L Cr | 15.1x | -38% | $416.2 B | $4.9 trillion  (a number after "/" is a scale, as in 40/100)
NUMBER = re.compile(
    r"(?<![\w./])(?P<sign>[-−])?[₹$]?\s?(?P<num>\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?P<unit>\s?(?:%|x\b|L\s?Cr\b|lakh crore|Cr\b|crore|trillion\b|billion\b|million\b|bn\b|[MBT]\b))?",
    re.IGNORECASE,
)
# Tool amounts are in ₹ crore (Indian companies) or $ millions (US); larger units written in answers scale to those
UNIT_SCALE = [(("l", "lakh"), 1e5), (("trillion", "t"), 1e6), (("billion", "bn", "b"), 1e3)]


def _unit_scale(unit: str | None) -> float:
    u = (unit or "").strip().lower().replace(" ", "")
    for prefixes, scale in UNIT_SCALE:
        if u in prefixes or (prefixes[0] == "l" and u.startswith(("lcr", "lakh"))):
            return scale
    return 1.0
CITATION = re.compile(r"\[S\d+(?:\s*,\s*S\d+)*\]")
FISCAL_YEAR = re.compile(r"\bFY\s?\d{2,4}\b", re.IGNORECASE)


def _parse(match: re.Match) -> tuple[float, float]:
    """(value, tolerance) in base units. Tolerance is half a unit of the last digit the answer shows."""
    text = match.group("num").replace(",", "")
    decimals = len(text.split(".")[1]) if "." in text else 0
    scale = _unit_scale(match.group("unit"))
    value = float(text) * scale
    tolerance = 0.5 * 10 ** -decimals * scale
    return value, tolerance


def _numbers_in(text: str):
    for m in NUMBER.finditer(text):
        yield m


def tool_values(tool_outputs: list[str]) -> list[float]:
    """Every number that appeared in any tool result, including numbers inside strings (e.g. score reasons)."""
    values: list[float] = []

    def walk(node):
        if isinstance(node, bool):
            return
        if isinstance(node, (int, float)):
            values.append(abs(float(node)))
        elif isinstance(node, str):
            for m in _numbers_in(node):
                values.append(_parse(m)[0])
        elif isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    for out in tool_outputs:
        try:
            walk(json.loads(out))
        except json.JSONDecodeError:
            continue
    return values


def unverified_numbers(answer: str, tool_outputs: list[str], question: str = "") -> list[str]:
    """Figures in `answer` that no tool result (or the user's own question) supports."""
    known = tool_values(tool_outputs) + [_parse(m)[0] for m in _numbers_in(question)]
    text = FISCAL_YEAR.sub(" ", CITATION.sub(" ", answer))
    missing = []
    for m in _numbers_in(text):
        value, tol = _parse(m)
        unit = (m.group("unit") or "").strip()
        is_year = not unit and "." not in m.group("num") and 1990 <= value <= 2100
        is_small_count = not unit and "." not in m.group("num") and value <= 12  # "3 years", "top 5 peers"
        if is_year or is_small_count:
            continue
        if not any(abs(abs(value) - k) <= tol + 1e-9 for k in known):
            missing.append(m.group(0).strip())
    return list(dict.fromkeys(missing))


def _values_by_source(tool_outputs: list[str]) -> dict[str, list[float]]:
    """Numbers grouped by the nearest enclosing "source" tag in each tool result.

    One result can carry several sources (a snapshot has quote, statements and scores), so each number
    belongs to the closest object above it that declares a source id."""
    by_id: dict[str, list[float]] = {}

    def walk(node, sid):
        if isinstance(node, dict):
            tag = node.get("source")
            if isinstance(tag, str) and re.fullmatch(r"S\d+", tag):
                sid = tag
            for k, v in node.items():
                if k != "source":
                    walk(v, sid)
        elif isinstance(node, list):
            for v in node:
                walk(v, sid)
        elif sid and not isinstance(node, bool):
            by_id.setdefault(sid, []).extend(tool_values([json.dumps(node)]))

    for out in tool_outputs:
        try:
            walk(json.loads(out), None)
        except json.JSONDecodeError:
            continue
    return by_id


def _calculations(tool_outputs: list[str]) -> list[dict]:
    """Calculator results with their inputs, so a derived figure can be traced to the data it came from."""
    calcs = []
    for out in tool_outputs:
        try:
            d = json.loads(out)
        except json.JSONDecodeError:
            continue
        if isinstance(d, dict) and "operation" in d and "result" in d:
            inputs = d["inputs"][:2] if d["operation"] == "cagr" else d["inputs"]  # cagr's 3rd input is a year count
            calcs.append({"result": abs(float(d["result"])), "inputs": [abs(float(x)) for x in inputs]})
    return calcs


def misattributed(answer: str, tool_outputs: list[str]) -> list[str]:
    """Figures whose citation points at a source that does not contain them.

    A citation covers the figures written between the previous citation (or line start) and itself,
    e.g. in "profit ₹49,210 Cr [S2], ROE 48.7% [S1]" ₹49,210 Cr must be in S2's data and 48.7% in S1's."""
    by_id = _values_by_source(tool_outputs)
    calcs = _calculations(tool_outputs)
    problems = []
    for line in answer.splitlines():
        # Back-to-back citations ("... ₹48,553 Cr [S2][S4]") jointly cover the text before them.
        groups: list[list[re.Match]] = []
        for cite in CITATION.finditer(line):
            if groups and not line[groups[-1][-1].end():cite.start()].strip():
                groups[-1].append(cite)
            else:
                groups.append([cite])
        start = 0
        for group in groups:
            first, last = group[0], group[-1]
            span = FISCAL_YEAR.sub(" ", CITATION.sub(" ", line[start:first.start()]))
            start = last.end()
            label = "".join(c.group(0) for c in group)
            ids = [sid for c in group for sid in re.findall(r"S\d+", c.group(0))]
            known = [v for sid in ids for v in by_id.get(sid, [])]
            if not known:
                continue  # unknown id is reported by the caller's id check
            for m in _numbers_in(span):
                value, tol = _parse(m)
                unit = (m.group("unit") or "").strip()
                if not unit and "." not in m.group("num") and (value <= 12 or 1990 <= value <= 2100):
                    continue
                if any(abs(abs(value) - k) <= tol + 1e-9 for k in known):
                    continue
                # A figure the calculator derived from the cited source's own numbers is correctly attributed,
                # e.g. "profit grew 16% [S1]" where 16% = percent_change of two S1 figures.
                percent = unit == "%"
                derived = any((abs(abs(value) - c["result"]) <= tol + 1e-9
                               or (percent and abs(abs(value) - c["result"] * 100) <= tol + 1e-9))  # ratio 0.09 -> "9%"
                              and all(any(abs(x - k) <= max(1e-6, abs(x) * 1e-6) for k in known) for x in c["inputs"])
                              for c in calcs)
                if not derived:
                    problems.append(f"{m.group(0).strip()} {label}")
    return list(dict.fromkeys(problems))


# ---------------------------------------------------------------- quotes from documents

QUOTE = re.compile(r'[“"]([^”"]{20,600})[”"]\s*((?:\[S\d+(?:\s*,\s*S\d+)*\]\s*)*)')


def _norm(text: str) -> str:
    text = text.lower().replace("’", "'").replace("‘", "'").replace("‑", "-").replace("–", "-").replace("—", "-")
    return re.sub(r"[^a-z0-9%₹.,'-]+", " ", text).strip()


def _passages(tool_outputs: list[str]) -> dict[str, str]:
    """Document text by source id, from search_documents results."""
    out: dict[str, str] = {}

    def walk(node):
        if isinstance(node, dict):
            if isinstance(node.get("source"), str) and isinstance(node.get("text"), str) and "page" in node:
                out[node["source"]] = out.get(node["source"], "") + " " + node["text"]
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    for o in tool_outputs:
        try:
            walk(json.loads(o))
        except json.JSONDecodeError:
            continue
    return out


def unsupported_quotes(answer: str, tool_outputs: list[str]) -> list[str]:
    """Quoted passages that don't appear word for word in the document page they cite (or, uncited, in any
    retrieved passage). Only checked when document passages were retrieved."""
    passages = _passages(tool_outputs)
    if not passages:
        return []
    problems = []
    for m in QUOTE.finditer(answer):
        ids = re.findall(r"S\d+", m.group(2) or "")
        pool = " ".join(passages.get(i, "") for i in ids) if ids else " ".join(passages.values())
        if ids and not any(i in passages for i in ids):
            continue  # quote cites non-document sources (e.g. a data table); the numbers checks cover those
        haystack = _norm(pool)
        parts = [p for p in re.split(r"\.\.\.|…", m.group(1)) if len(p.strip()) > 8]  # allow elisions
        if not all(_norm(p) in haystack for p in parts):
            problems.append(f'"{m.group(1)[:80]}"{(" " + m.group(2).strip()) if m.group(2) else ""}')
    return problems


# ---------------------------------------------------------------- arithmetic re-check (FinGround-style)

_AMOUNT = r"(-?[₹$]?\s?\d[\d,]*(?:\.\d+)?)\s*(L\s?Cr|lakh crore|Cr|crore|trillion|billion|million|bn|[MBT]\b)?"
FROM_TO = re.compile(rf"from\s+{_AMOUNT}(?:\s+(?:in\s+)?FY\s?\d{{2,4}})?\s+to\s+{_AMOUNT}", re.IGNORECASE)
ARROW = re.compile(rf"{_AMOUNT}\s*(?:→|->)\s*{_AMOUNT}")
PERCENT = re.compile(r"(-?\d+(?:\.\d+)?)\s?%")
YEARS = re.compile(r"(?:over|in)\s+(\d{1,2})\s+years|FY\s?(\d{2,4})\s*(?:to|-|–|→)\s*FY\s?(\d{2,4})", re.IGNORECASE)


def _amount(num: str, unit: str | None) -> float:
    value = float(num.replace("₹", "").replace("$", "").replace(",", "").strip())
    return value * _unit_scale(unit)


def arithmetic_errors(answer: str) -> list[str]:
    """Growth claims whose stated percentage doesn't match the figures in the same sentence, e.g.
    "profit rose 16% from ₹42,147 Cr to ₹49,210 Cr" (actual change 16.8% -> ok; "25%" -> flagged).
    Conservative: one from/to pair per sentence, amounts only (not percentage-point moves)."""
    problems = []
    for sentence in re.split(r"(?<=[.;])\s+|\n", answer):
        pairs = FROM_TO.findall(sentence) + ARROW.findall(sentence)
        if len(pairs) != 1:
            continue
        a_num, a_unit, b_num, b_unit = pairs[0]
        if "%" in sentence[sentence.find(a_num):sentence.find(a_num) + len(a_num) + 2]:
            continue  # from 11% to 9%: a percentage-point move, not a growth rate
        a, b = _amount(a_num, a_unit), _amount(b_num, b_unit)
        if a <= 0:
            continue
        stated = [abs(float(p)) for p in PERCENT.findall(sentence)]
        if not stated:
            continue
        change = abs((b - a) / a * 100)
        candidates = [change]
        y = YEARS.search(sentence)
        fys = [int(f[-2:]) for f in re.findall(r"FY\s?(\d{2,4})", sentence, re.IGNORECASE)]
        n = 0
        if y and y.group(1):
            n = int(y.group(1))
        elif len(fys) >= 2:
            n = max(fys) - min(fys)   # "from ₹X in FY23 to ₹Y in FY26" -> 3 years
        if n > 0:
            if b > 0:
                candidates.append(abs(((b / a) ** (1 / n) - 1) * 100))
        if not any(abs(s - c) <= max(0.6, 0.03 * c) for s in stated for c in candidates):
            problems.append(f"{sentence.strip()[:140]} (the figures imply {change:.1f}%"
                            + (f", or {candidates[1]:.1f}% a year" if len(candidates) > 1 else "") + ")")
    return problems
