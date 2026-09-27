"""Who is calling the API, and how much AI they've used today.

Users sign in with Google on the website (Auth.js). For AI requests the website sends a short-lived token signed
with FINSIGHT_API_JWT_SECRET, a secret shared only between the website and this API. The API verifies it, records
the user, and enforces a daily AI allowance so no one can drain the AI budget.

When FINSIGHT_API_JWT_SECRET is not set (local development), sign-in is not required and everyone is "local".
"""
import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Header, HTTPException

from app import db

ISSUER, AUDIENCE = "finsight-web", "finsight-api"
IST = timezone(timedelta(hours=5, minutes=30))
LOCAL_USER = {"sub": "local", "email": None, "name": "Local developer"}

# Rough relative cost of each AI feature, in allowance units
COST = {"ask": 1, "screen": 1, "summary": 1, "report": 10}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    sub           text PRIMARY KEY,           -- Google account id
    email         text,
    name          text,
    picture       text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    last_seen_at  timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS ai_usage (
    sub    text NOT NULL,
    day    date NOT NULL,                     -- India date, so allowances reset at midnight IST
    units  int  NOT NULL DEFAULT 0,
    PRIMARY KEY (sub, day)
);
"""
_schema_ready = False


def _secret() -> str | None:
    return os.environ.get("FINSIGHT_API_JWT_SECRET") or None


def enabled() -> bool:
    return _secret() is not None


def daily_limit() -> int:
    return int(os.environ.get("FINSIGHT_AI_DAILY_LIMIT", "30"))


def _ensure_schema():
    global _schema_ready
    if not _schema_ready:
        db.execute(SCHEMA)
        _schema_ready = True


def require_user(authorization: str | None = Header(default=None)) -> dict:
    """FastAPI dependency: the signed-in user, or 401 if the request has no valid token."""
    secret = _secret()
    if not secret:
        return LOCAL_USER
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Sign in with Google to use AI features.")
    try:
        claims = jwt.decode(authorization[7:], secret, algorithms=["HS256"], audience=AUDIENCE, issuer=ISSUER,
                            options={"require": ["exp", "sub"]})
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Your session expired. Refresh the page and try again.")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Sign in with Google to use AI features.")
    user = {"sub": claims["sub"], "email": claims.get("email"), "name": claims.get("name"), "picture": claims.get("picture")}
    _ensure_schema()
    db.execute("""INSERT INTO users (sub, email, name, picture) VALUES (%(sub)s, %(email)s, %(name)s, %(picture)s)
                  ON CONFLICT (sub) DO UPDATE SET email = EXCLUDED.email, name = EXCLUDED.name,
                  picture = EXCLUDED.picture, last_seen_at = now()""", user)
    return user


def consume(user: dict, feature: str) -> dict:
    """Charge one AI use against today's allowance, or raise 429 when it's used up."""
    if user["sub"] == "local":
        return {"used": 0, "limit": None}
    _ensure_schema()
    cost, limit = COST[feature], daily_limit()
    today = datetime.now(IST).date()
    with db.conn() as c:
        row = c.execute("""INSERT INTO ai_usage (sub, day, units) VALUES (%s, %s, %s)
                           ON CONFLICT (sub, day) DO UPDATE SET units = ai_usage.units + EXCLUDED.units
                           WHERE ai_usage.units + EXCLUDED.units <= %s
                           RETURNING units""", (user["sub"], today, cost, limit)).fetchone()
    if row is None or row["units"] > limit:
        raise HTTPException(429, f"You've used today's AI allowance ({limit} units; a report uses {COST['report']}). "
                                 "It resets at midnight IST.")
    return {"used": row["units"], "limit": limit}


def usage(user: dict) -> dict:
    if user["sub"] == "local":
        return {"used": 0, "limit": None}
    _ensure_schema()
    row = db.fetch_one("SELECT units FROM ai_usage WHERE sub = %s AND day = %s", (user["sub"], datetime.now(IST).date()))
    return {"used": row["units"] if row else 0, "limit": daily_limit()}
