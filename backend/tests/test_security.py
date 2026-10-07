"""Rate limits, no cross-user data access, and no secrets or database details in responses or logs."""
import io

import jwt
import pytest
from fastapi.testclient import TestClient

from app import ipos, main, research, security, watchlist
from app.providers import yahoo
from tests.conftest import add_company
from tests.test_auth import SECRET, token

# Fake credentials, assembled at runtime so the source holds nothing that looks like a real key to secret scanners
FAKE_KEY = "sk-" + "f" * 32
FAKE_ANTHROPIC = "sk-" + "ant-" + "x" * 30
FAKE_DB_PASSWORD = "npg" + "_" + "Z" * 12
DB_ERROR = ('connection to server at "ep-cool-river-123.ap-southeast-1.aws.neon.tech" (13.228.1.2), port 5432 failed: '
            'FATAL: password authentication failed for user "neondb_owner"')


@pytest.fixture
def client(clean_db, monkeypatch):
    monkeypatch.setenv("FINSIGHT_API_JWT_SECRET", SECRET)
    add_company(clean_db, "TCS", "Tata Consultancy Services Limited")
    add_company(clean_db, "INFY", "Infosys Limited")
    return TestClient(main.app, raise_server_exceptions=False)


# ---------------------------------------------------------------- secrets never leave the server

def test_redact_removes_secrets_and_database_details(monkeypatch):
    database_url = f"postgresql://neondb_owner:{FAKE_DB_PASSWORD}@ep-x.neon.tech/neondb?sslmode=require"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("DEEPSEEK_API_KEY", FAKE_KEY)
    text = security.redact(f"{DB_ERROR}; url={database_url}; key {FAKE_KEY}; "
                           "host=ep-x.neon.tech password=hunter22 Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig")
    for leaked in ("neon.tech", "neondb_owner", FAKE_DB_PASSWORD, "hunter22", FAKE_KEY, "13.228.1.2", "eyJhbGci"):
        assert leaked not in text, leaked


def test_printed_output_and_tracebacks_are_redacted(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_ANTHROPIC)
    out = io.StringIO()
    security._RedactingStream(out).write(f"calling with {FAKE_ANTHROPIC} at postgresql://u:p@h/db\n")
    assert FAKE_ANTHROPIC not in out.getvalue() and "u:p@h" not in out.getvalue()


def test_a_crash_returns_a_generic_message(client, monkeypatch):
    def boom(symbol):
        raise RuntimeError(DB_ERROR)
    monkeypatch.setattr(research, "company_report", boom)
    r = client.get("/api/company/TCS")
    assert r.status_code == 500 and r.json() == {"detail": security.GENERIC_500}


def test_upstream_failures_dont_echo_the_error(client, monkeypatch):
    monkeypatch.setattr(ipos, "current", lambda: (_ for _ in ()).throw(RuntimeError(DB_ERROR)))
    r = client.get("/api/ipos")
    assert r.status_code == 502 and "neon" not in r.text and "password" not in r.text


def test_internal_diagnostics_are_hidden_without_the_admin_token(client, monkeypatch):
    assert client.get("/api/health/storage").status_code == 404
    assert client.get("/api/health/sources").status_code == 404
    monkeypatch.setenv("FINSIGHT_ADMIN_TOKEN", "admin-token-for-tests")
    assert client.get("/api/health/storage", headers={"X-Admin-Token": "wrong"}).status_code == 404
    assert client.get("/api/health/storage", headers={"X-Admin-Token": "admin-token-for-tests"}).status_code == 200


# ---------------------------------------------------------------- one user can never reach another's data

def test_users_cannot_read_or_change_each_others_watchlists(client, monkeypatch):
    monkeypatch.setattr(research, "company_report", lambda s: {"scores": {"overall": {"score": 70, "label": "Stable"}},
                                                               "profile": {"price": 1.0, "change_pct": 0.0}})
    monkeypatch.setattr(watchlist.nse, "announcements", lambda s, n: [])
    asha = {"authorization": token(sub="user-a", email="a@example.com")}
    ravi = {"authorization": token(sub="user-b", email="b@example.com")}
    client.post("/api/watchlist", json={"symbol": "TCS"}, headers=asha)
    client.patch("/api/watchlist/TCS", json={"note": "Asha's private note"}, headers=asha)

    # Ravi aims at the same symbol: reads see nothing, writes touch only his own (empty) list
    assert client.get("/api/watchlist", headers=ravi).json()["items"] == []
    assert client.get("/api/watchlist/TCS/details", headers=ravi).status_code == 404
    client.patch("/api/watchlist/TCS", json={"note": "overwritten"}, headers=ravi)
    client.delete("/api/watchlist/TCS", headers=ravi)
    items = client.get("/api/watchlist", headers=asha).json()["items"]
    assert [(i["symbol"], i["note"]) for i in items] == [("TCS.NS", "Asha's private note")]


def test_forged_or_tampered_tokens_are_refused(client):
    stranger = token(secret="not-the-real-secret-but-long-enough!!", sub="user-a")
    unsigned = "Bearer " + jwt.encode({"sub": "user-a", "iss": "finsight-web", "aud": "finsight-api", "exp": 9999999999},
                                      None, algorithm="none")
    wrong_audience = token(aud="some-other-api")
    for bad in (stranger, unsigned, wrong_audience):
        assert client.get("/api/watchlist", headers={"authorization": bad}).status_code == 401


def test_adding_gmp_needs_sign_in_and_safe_links(client):
    entry = {"gmp": 12, "source": "Test"}
    assert client.post("/api/ipos/IG-1/gmp", json=entry).status_code == 401
    me = {"authorization": token()}
    bad_link = client.post("/api/ipos/IG-1/gmp", json={**entry, "source_url": "javascript:alert(1)"}, headers=me)
    assert bad_link.status_code == 422
    assert client.post("/api/ipos/IG-1/gmp", json={**entry, "source_url": "https://example.com/x"}, headers=me).status_code == 200


# ---------------------------------------------------------------- rate limits

def test_rate_limit_answers_429_with_retry_after(client, monkeypatch):
    monkeypatch.setattr(yahoo, "search", lambda q: [])
    codes = [client.get("/api/search", params={"q": "tcs"}).status_code for _ in range(61)]
    assert codes[:60] == [200] * 60 and codes[60] == 429
    r = client.get("/api/search", params={"q": "tcs"})
    assert int(r.headers["retry-after"]) >= 1 and "Too many requests" in r.json()["detail"]
    assert client.get("/api/health").status_code == 200          # the keep-warm ping is never limited


def test_ai_endpoints_have_a_tighter_limit(client):
    me = {"authorization": token()}
    codes = [client.post("/api/ask", json={"question": "Tell me a joke"}, headers=me).status_code for _ in range(11)]
    assert codes[:10] == [200] * 10 and codes[10] == 429             # refused off-topic questions still count


def test_visitors_are_told_apart_by_cloudflare_header_only_on_render(client, monkeypatch):
    monkeypatch.setattr(yahoo, "search", lambda q: [])
    hammer = lambda ip: [client.get("/api/search", params={"q": "x"}, headers={"True-Client-IP": ip}).status_code
                         for _ in range(61)][-1]
    assert hammer("1.1.1.1") == 429
    assert hammer("2.2.2.2") == 429      # not on Render: the header is ignored, so it's the same visitor
    security.limiter.reset()
    monkeypatch.setenv("RENDER", "true")
    assert hammer("1.1.1.1") == 429
    assert client.get("/api/search", params={"q": "x"}, headers={"True-Client-IP": "2.2.2.2"}).status_code == 200


def test_limiter_window_slides():
    lim = security.RateLimiter()
    assert all(lim.hit(("k",), 2, 10, now=t) is None for t in (0, 1))
    assert lim.hit(("k",), 2, 10, now=2) == pytest.approx(8)
    assert lim.hit(("k",), 2, 10, now=10.5) is None                    # the first hit has left the window


# ---------------------------------------------------------------- hardening

def test_oversized_requests_and_odd_symbols_are_refused(client):
    me = {"authorization": token()}
    big = client.post("/api/ask", content=b"x" * (security.MAX_BODY_BYTES + 1),
                      headers={**me, "content-type": "application/json"})
    assert big.status_code == 413
    for bad in ("TCS%20OR%201=1", "TCS;rm", "A" * 41, "<script>"):
        assert client.get(f"/api/company/{bad}").status_code == 422, bad


def test_api_responses_carry_security_headers(client):
    r = client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert r.headers["cache-control"] == "no-store"


def test_api_docs_are_off_in_production(monkeypatch):
    import importlib
    monkeypatch.setenv("RENDER", "true")
    prod = importlib.reload(main)
    try:
        c = TestClient(prod.app)
        assert c.get("/docs").status_code == 404 and c.get("/openapi.json").status_code == 404
    finally:
        monkeypatch.delenv("RENDER")
        importlib.reload(main)


def test_remote_databases_always_use_tls():
    from app.db import require_tls
    assert "sslmode=require" in require_tls("postgresql://u:p@ep-x.neon.tech/db")
    assert "sslmode=require" in require_tls("postgresql://u:p@ep-x.neon.tech/db?sslmode=disable")
    assert "sslmode=verify-full" in require_tls("postgresql://u:p@ep-x.neon.tech/db?sslmode=verify-full")
    assert require_tls("postgresql://u:p@localhost/db") == "postgresql://u:p@localhost/db"


# ---------------------------------------------------------------- unbounded input (DoS)

def test_list_and_query_inputs_are_bounded(client):
    me = {"authorization": token()}
    assert client.post("/api/screener", json={"filters": [{"field": "pe", "op": ">", "value": 1}] * 5000}).status_code == 422
    assert client.post("/api/screener", json={"sectors": ["Technology"] * 50}).status_code == 422
    big_history = {"question": "hello there", "history": [{"role": "user", "content": "x"}] * 2000}
    assert client.post("/api/ask", json=big_history, headers=me).status_code == 422
    assert client.get("/api/search", params={"q": "x" * 200}).status_code == 422
    assert client.patch("/api/watchlist/<script>", json={"note": "x"}, headers=me).status_code == 422
