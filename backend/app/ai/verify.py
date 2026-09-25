"""Numeric grounding check: every figure in an answer must be traceable to a tool result.

This is FinSight's guard against a language model inventing or mis-copying financial numbers.
A figure passes if some tool-returned value rounds to it at the precision the answer used.
"""
import json
import re

# ₹1,23,456.78 | 48.7% | 2.67 L Cr | 15.1x | -38%
NUMBER = re.compile(
    r"(?<![\w.])(?P<sign>[-−])?₹?\s?(?P<num>\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?P<unit>\s?(?:%|x\b|L\s?Cr\b|lakh crore|Cr\b|crore))?",
    re.IGNORECASE,
)
CITATION = re.compile(r"\[S\d+(?:\s*,\s*S\d+)*\]")
FISCAL_YEAR = re.compile(r"\bFY\s?\d{2,4}\b", re.IGNORECASE)


def _parse(match: re.Match) -> tuple[float, float]:
    """(value, tolerance) in base units. Tolerance is half a unit of the last digit the answer shows."""
    text = match.group("num").replace(",", "")
    decimals = len(text.split(".")[1]) if "." in text else 0
    scale = 1e5 if (match.group("unit") or "").strip().lower().startswith(("l", "lakh")) else 1.0
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
