"""Per-user watchlists: the stocks someone follows, what changed since they last looked, and a note each.

The list itself loads instantly from stored data (metrics + profiles). Scores and the latest filing are computed
per stock by `details()`, which the page requests row by row, so a 50-stock watchlist never blocks on 50 live
calculations.
"""
import re
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from app import db, research
from app.providers import nse, yahoo

LIMIT = 50
LABEL_CHANGE_DAYS = 7   # how long a "label changed" badge stays visible
VISIT_GAP_MINUTES = 30  # reloads closer together than this belong to the same visit
IST = timezone(timedelta(hours=5, minutes=30))
# "Tata Consultancy Services Limited has informed the Exchange regarding ..." -> "..."
_BOILERPLATE = re.compile(r"^.{0,120}?\bhas informed (?:the )?(?:Exchange )?(?:about |regarding |that )?", re.I)

SCHEMA = """
CREATE TABLE IF NOT EXISTS watchlist (
    sub               text NOT NULL,            -- users.sub (Google account id)
    symbol            text NOT NULL,            -- NSE symbol, e.g. TCS
    note              text,
    added_at          timestamptz NOT NULL DEFAULT now(),
    score             int,                      -- last FinSight score seen for this row
    label             text,
    prev_label        text,                     -- label before the most recent change
    label_changed_at  timestamptz,
    PRIMARY KEY (sub, symbol)
);
ALTER TABLE users ADD COLUMN IF NOT EXISTS watchlist_seen_at timestamptz;
ALTER TABLE users ADD COLUMN IF NOT EXISTS watchlist_prev_seen_at timestamptz;
"""
_schema_ready = False


def _ensure_schema():
    global _schema_ready
    if not _schema_ready:
        from app import auth
        auth._ensure_schema()   # users table first
        db.execute(SCHEMA)
        _schema_ready = True


def _base(symbol: str) -> str:
    return symbol.split(".")[0].upper()


def symbols(user: dict) -> list[str]:
    _ensure_schema()
    return [r["symbol"] for r in db.fetch_all("SELECT symbol FROM watchlist WHERE sub = %s ORDER BY added_at", (user["sub"],))]


def add(user: dict, symbol: str, note: str | None = None) -> dict:
    _ensure_schema()
    base = _base(symbol)
    if not db.fetch_one("SELECT 1 FROM companies WHERE symbol = %s", (base,)):
        raise HTTPException(404, f"{base} isn't an NSE-listed company FinSight knows about.")
    count = db.fetch_one("SELECT count(*) AS n FROM watchlist WHERE sub = %s", (user["sub"],))["n"]
    if count >= LIMIT and not db.fetch_one("SELECT 1 FROM watchlist WHERE sub = %s AND symbol = %s", (user["sub"], base)):
        raise HTTPException(409, f"Your watchlist is full ({LIMIT} stocks). Remove one to add another.")
    db.execute("""INSERT INTO watchlist (sub, symbol, note) VALUES (%s, %s, %s)
                  ON CONFLICT (sub, symbol) DO UPDATE SET note = COALESCE(EXCLUDED.note, watchlist.note)""",
               (user["sub"], base, (note or "").strip()[:200] or None))
    return {"symbol": base, "watching": True}


def remove(user: dict, symbol: str) -> dict:
    _ensure_schema()
    db.execute("DELETE FROM watchlist WHERE sub = %s AND symbol = %s", (user["sub"], _base(symbol)))
    return {"symbol": _base(symbol), "watching": False}


def set_note(user: dict, symbol: str, note: str) -> dict:
    _ensure_schema()
    db.execute("UPDATE watchlist SET note = %s WHERE sub = %s AND symbol = %s",
               ((note or "").strip()[:200] or None, user["sub"], _base(symbol)))
    return {"symbol": _base(symbol), "note": (note or "").strip()[:200] or None}


def listing(user: dict) -> dict:
    """The watchlist with stored market data, plus when the user last looked (for "new since your last visit")."""
    _ensure_schema()
    rows = db.fetch_all("""
        SELECT w.symbol, w.note, w.added_at, w.score, w.label, w.prev_label, w.label_changed_at,
               c.name AS listed_name, m.yahoo_symbol, m.name, m.sector, m.price, m.market_cap_cr, m.pe, m.roe_pct,
               p.data->>'change_pct' AS change_pct, p.data->>'week52_low' AS week52_low,
               p.data->>'week52_high' AS week52_high
        FROM watchlist w
        JOIN companies c ON c.symbol = w.symbol
        LEFT JOIN metrics m ON m.symbol = w.symbol
        LEFT JOIN profiles p ON p.symbol = w.symbol
        WHERE w.sub = %s ORDER BY w.added_at""", (user["sub"],))
    # The page reloads the list whenever a star changes, so "since your last visit" must survive reloads: a new
    # visit starts only after VISIT_GAP_MINUTES without one. (SET expressions see the row's old values.)
    seen = db.fetch_one(f"""UPDATE users SET
                               watchlist_prev_seen_at = CASE
                                   WHEN watchlist_seen_at IS NULL
                                     OR watchlist_seen_at < now() - interval '{VISIT_GAP_MINUTES} minutes'
                                   THEN watchlist_seen_at ELSE watchlist_prev_seen_at END,
                               watchlist_seen_at = now()
                           WHERE sub = %s RETURNING watchlist_prev_seen_at""", (user["sub"],))
    previous_visit = seen["watchlist_prev_seen_at"] if seen else None

    def num(v):
        return float(v) if v not in (None, "null") else None

    items = [{
        "symbol": r["yahoo_symbol"] or f"{r['symbol']}.NS",
        "base": r["symbol"],
        "name": r["name"] or r["listed_name"],
        "sector": r["sector"],
        "price": r["price"],
        "change_pct": num(r["change_pct"]),
        "week52_low": num(r["week52_low"]),
        "week52_high": num(r["week52_high"]),
        "market_cap_cr": r["market_cap_cr"],
        "pe": r["pe"],
        "roe_pct": r["roe_pct"],
        "note": r["note"],
        "added_at": r["added_at"].isoformat(),
        "score": r["score"], "label": r["label"], "prev_label": r["prev_label"],
        "label_changed_at": r["label_changed_at"].isoformat() if r["label_changed_at"] else None,
    } for r in rows]
    return {"items": items, "previous_visit": previous_visit.isoformat() if previous_visit else None, "limit": LIMIT}


def _aware(value: str) -> datetime:
    t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=IST)   # NSE times are Indian time without an offset


def _is_after(published: str | None, since: str | None) -> bool:
    """Whether a filing came out after the user's previous visit. Bad or missing dates never hide the filing."""
    if not published or not since:
        return False
    try:
        return _aware(published) > _aware(since)
    except ValueError:
        return False


def details(user: dict, symbol: str, since: str | None) -> dict:
    """Live FinSight score (tracking label changes) and the latest material NSE filing for one watched stock."""
    _ensure_schema()
    base = _base(symbol)
    row = db.fetch_one("SELECT label FROM watchlist WHERE sub = %s AND symbol = %s", (user["sub"], base))
    if not row:
        raise HTTPException(404, f"{base} isn't on your watchlist.")

    out: dict = {"symbol": base}
    try:
        report = research.company_report(yahoo.normalize_symbol(base))
        overall = report["scores"]["overall"]
        out.update(score=overall["score"], label=overall["label"], price=report["profile"]["price"],
                   change_pct=report["profile"]["change_pct"])
        if overall["label"] and overall["label"] != row["label"]:
            # first sighting just records the label; later differences are real changes
            db.execute("""UPDATE watchlist SET score = %s, label = %s,
                              prev_label = CASE WHEN label IS NULL THEN NULL ELSE label END,
                              label_changed_at = CASE WHEN label IS NULL THEN NULL ELSE now() END
                          WHERE sub = %s AND symbol = %s""", (overall["score"], overall["label"], user["sub"], base))
        else:
            db.execute("UPDATE watchlist SET score = %s WHERE sub = %s AND symbol = %s", (overall["score"], user["sub"], base))
        changed = db.fetch_one("SELECT prev_label, label_changed_at FROM watchlist WHERE sub = %s AND symbol = %s",
                               (user["sub"], base))
        recent = changed["label_changed_at"] and changed["label_changed_at"] > datetime.now(timezone.utc) - timedelta(days=LABEL_CHANGE_DAYS)
        out["prev_label"] = changed["prev_label"] if recent else None
    except Exception:
        out["score_error"] = "Score unavailable right now"

    try:
        latest = next((a for a in nse.announcements(base, 30) if not a["routine"]), None)
        if latest:
            out["filing"] = {"category": latest["category"], "text": _BOILERPLATE.sub("", latest["text"]).strip(" -:")[:160], "published": latest["published"],
                             "url": latest["pdf_url"]}
            out["filing"]["new"] = _is_after(latest["published"], since)
    except Exception:
        out["filing_error"] = "Filings unavailable right now"
    return out
