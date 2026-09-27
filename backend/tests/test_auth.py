import time

import jwt
import pytest
from fastapi import HTTPException

from app import auth

SECRET = "test-secret-at-least-32-bytes-long!!"


def token(secret=SECRET, **overrides):
    claims = {"sub": "g-123", "email": "a@example.com", "name": "Asha", "iss": "finsight-web", "aud": "finsight-api",
              "iat": int(time.time()), "exp": int(time.time()) + 3600, **overrides}
    return "Bearer " + jwt.encode(claims, secret, algorithm="HS256")


@pytest.fixture
def signed_in(clean_db, monkeypatch):
    monkeypatch.setenv("FINSIGHT_API_JWT_SECRET", SECRET)
    return clean_db


def test_local_mode_needs_no_token():
    assert auth.require_user(None) == auth.LOCAL_USER
    assert auth.consume(auth.LOCAL_USER, "report") == {"used": 0, "limit": None}


def test_valid_token_records_the_user(signed_in):
    user = auth.require_user(token())
    assert user["sub"] == "g-123" and user["email"] == "a@example.com"
    assert signed_in.fetch_one("SELECT name FROM users WHERE sub = 'g-123'")["name"] == "Asha"


@pytest.mark.parametrize("bad", [
    None,
    "Basic abc",
    token(secret="some-other-secret-also-32-bytes-long"),
    token(aud="someone-else"),
    token(iss="someone-else"),
    token(exp=int(time.time()) - 10),
])
def test_bad_tokens_are_rejected(signed_in, bad):
    with pytest.raises(HTTPException) as e:
        auth.require_user(bad)
    assert e.value.status_code == 401


def test_daily_allowance(signed_in, monkeypatch):
    monkeypatch.setenv("FINSIGHT_AI_DAILY_LIMIT", "12")
    user = auth.require_user(token())
    assert auth.consume(user, "report")["used"] == 10
    assert auth.consume(user, "ask")["used"] == 11
    with pytest.raises(HTTPException) as e:
        auth.consume(user, "report")               # 21 > 12: refused and not charged
    assert e.value.status_code == 429
    assert auth.usage(user) == {"used": 11, "limit": 12}
    assert auth.consume(user, "ask")["used"] == 12


def test_earlier_random_ids_of_the_same_account_are_merged(signed_in):
    from app import watchlist
    from tests.conftest import add_company

    add_company(signed_in, "TCS", "TCS")
    add_company(signed_in, "INFY", "Infosys")
    # rows left by two earlier sign-ins that each got a random id (saved before merging existed)
    for sub in ("random-1", "random-2"):
        signed_in.execute("INSERT INTO users (sub, email) VALUES (%s, 'a@example.com')", (sub,))
    for sub, symbol in [("random-1", "TCS"), ("random-2", "INFY"), ("random-2", "TCS")]:
        watchlist.add({"sub": sub}, symbol)
    signed_in.execute("INSERT INTO ai_usage (sub, day, units) VALUES ('random-1', %s, 3)", (auth.datetime.now(auth.IST).date(),))
    auth.require_user(token(sub="stranger", email="someone@else.com"))
    watchlist.add({"sub": "stranger"}, "TCS")

    user = auth.require_user(token(sub="google-stable-id"))
    assert sorted(watchlist.symbols(user)) == ["INFY", "TCS"]
    assert auth.usage(user)["used"] == 3
    assert signed_in.fetch_one("SELECT count(*) AS n FROM users WHERE email = 'a@example.com'")["n"] == 1
    assert watchlist.symbols({"sub": "stranger"}) == ["TCS"]          # other people's lists are untouched

    auth.require_user(token(sub="google-stable-id"))                  # later requests: nothing left to merge
    assert sorted(watchlist.symbols(user)) == ["INFY", "TCS"]
