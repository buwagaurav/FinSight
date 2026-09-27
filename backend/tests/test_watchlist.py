from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app import research, watchlist
from app.providers import nse
from tests.conftest import add_company

USER = {"sub": "g-1", "email": "u@example.com", "name": "U", "picture": None}


@pytest.fixture
def db(clean_db):
    clean_db.execute("INSERT INTO users (sub, email) VALUES (%s, %s)", (USER["sub"], USER["email"]))
    add_company(clean_db, "TCS", "Tata Consultancy Services Limited", price=2082.0)
    add_company(clean_db, "INFY", "Infosys Limited", price=1000.0)
    add_company(clean_db, "HDFCBANK", "HDFC Bank Limited", sector="Financial Services")
    return clean_db


@pytest.fixture
def live(monkeypatch):
    """Stand-ins for the live score and NSE filings; tests change `state` to simulate new data."""
    state = {"label": "Strong", "score": 75, "filings": [], "report_error": None, "filings_error": None}

    def company_report(symbol):
        if state["report_error"]:
            raise state["report_error"]
        return {"scores": {"overall": {"score": state["score"], "label": state["label"]}},
                "profile": {"price": 2100.0, "change_pct": 0.9}}

    def announcements(symbol, limit):
        if state["filings_error"]:
            raise state["filings_error"]
        return state["filings"]

    monkeypatch.setattr(research, "company_report", company_report)
    monkeypatch.setattr(nse, "announcements", announcements)
    return state


def filing(published, text="Tata Consultancy Services Limited has informed the Exchange regarding 'Press Release - TCS wins deal'",
           routine=False):
    return {"category": "Updates", "text": text, "published": published, "pdf_url": "https://nse/x.pdf", "routine": routine}


def test_add_list_note_remove(db):
    watchlist.add(USER, "tcs.ns")
    watchlist.add(USER, "INFY", note="  core holding  ")
    assert watchlist.symbols(USER) == ["TCS", "INFY"]

    items = watchlist.listing(USER)["items"]
    tcs = items[0]
    assert tcs["symbol"] == "TCS.NS" and tcs["base"] == "TCS" and tcs["price"] == 2082.0
    assert tcs["change_pct"] == 1.5 and tcs["week52_low"] == 80.0 and tcs["week52_high"] == 120.0
    assert items[1]["note"] == "core holding"

    watchlist.set_note(USER, "TCS", "buy below 3000")
    watchlist.set_note(USER, "INFY", "   ")
    notes = {i["base"]: i["note"] for i in watchlist.listing(USER)["items"]}
    assert notes == {"TCS": "buy below 3000", "INFY": None}

    watchlist.remove(USER, "TCS.NS")
    assert watchlist.symbols(USER) == ["INFY"]


def test_adding_twice_keeps_one_row_and_its_note(db):
    watchlist.add(USER, "TCS", note="keep me")
    watchlist.add(USER, "TCS")
    assert watchlist.listing(USER)["items"][0]["note"] == "keep me"
    assert watchlist.symbols(USER) == ["TCS"]


def test_lists_are_private_to_each_user(db):
    watchlist.add(USER, "TCS")
    assert watchlist.symbols({"sub": "someone-else"}) == []


def test_unknown_company_is_rejected(db):
    with pytest.raises(HTTPException) as e:
        watchlist.add(USER, "NOPE")
    assert e.value.status_code == 404


def test_limit(db, monkeypatch):
    monkeypatch.setattr(watchlist, "LIMIT", 2)
    watchlist.add(USER, "TCS")
    watchlist.add(USER, "INFY")
    with pytest.raises(HTTPException) as e:
        watchlist.add(USER, "HDFCBANK")
    assert e.value.status_code == 409
    watchlist.add(USER, "TCS", note="re-adding an existing stock is fine when full")


def test_previous_visit_survives_reloads_within_a_visit(db):
    assert watchlist.listing(USER)["previous_visit"] is None          # first ever visit
    assert watchlist.listing(USER)["previous_visit"] is None          # reload after starring: same visit

    earlier = datetime.now(timezone.utc) - timedelta(hours=5)
    db.execute("UPDATE users SET watchlist_seen_at = %s WHERE sub = %s", (earlier, USER["sub"]))
    first = watchlist.listing(USER)["previous_visit"]                 # a new visit, 5 hours later
    assert datetime.fromisoformat(first) == earlier
    assert watchlist.listing(USER)["previous_visit"] == first         # reloads keep the same "since"


def test_label_change_is_tracked(db, live):
    watchlist.add(USER, "TCS")
    d = watchlist.details(USER, "TCS", None)
    assert (d["score"], d["label"], d["prev_label"]) == (75, "Strong", None)   # first sighting only records

    live.update(label="Stable", score=60)
    d = watchlist.details(USER, "TCS", None)
    assert (d["label"], d["prev_label"]) == ("Stable", "Strong")
    assert watchlist.details(USER, "TCS", None)["prev_label"] == "Strong"      # stays visible for a while

    db.execute("UPDATE watchlist SET label_changed_at = now() - interval '8 days'")
    assert watchlist.details(USER, "TCS", None)["prev_label"] is None           # then fades


def test_latest_material_filing_and_new_flag(db, live):
    watchlist.add(USER, "TCS")
    live["filings"] = [filing("2026-09-26T18:00:00", "Trading window closure", routine=True),
                       filing("2026-09-23T14:05:00")]
    f = watchlist.details(USER, "TCS", "2026-09-20T10:00:00+05:30")["filing"]
    assert f["published"] == "2026-09-23T14:05:00"                   # routine filing skipped
    assert f["text"] == "'Press Release - TCS wins deal'"             # boilerplate opening trimmed
    assert f["new"] is True
    assert watchlist.details(USER, "TCS", "2026-09-24T00:00:00+05:30")["filing"]["new"] is False
    # NSE times are Indian time: 14:05 IST is 08:35 UTC
    assert watchlist.details(USER, "TCS", "2026-09-23T08:30:00+00:00")["filing"]["new"] is True
    assert watchlist.details(USER, "TCS", "2026-09-23T08:40:00Z")["filing"]["new"] is False


@pytest.mark.parametrize("since", [None, "not-a-date", "2026-09-20T10:00:00"])
def test_odd_since_values_never_hide_the_filing(db, live, since):
    watchlist.add(USER, "TCS")
    live["filings"] = [filing("2026-09-23T14:05:00")]
    d = watchlist.details(USER, "TCS", since)
    assert "filing" in d and "filing_error" not in d


def test_source_failures_are_reported_per_part(db, live):
    watchlist.add(USER, "TCS")
    live.update(report_error=RuntimeError("Yahoo blocked"), filings=[filing("2026-09-23T14:05:00")])
    d = watchlist.details(USER, "TCS", None)
    assert d["score_error"] and "score" not in d and d["filing"]

    live.update(report_error=None, filings_error=RuntimeError("NSE down"))
    d = watchlist.details(USER, "TCS", None)
    assert d["score"] == 75 and d["filing_error"]


def test_details_only_for_watched_stocks(db, live):
    with pytest.raises(HTTPException) as e:
        watchlist.details(USER, "TCS", None)
    assert e.value.status_code == 404
