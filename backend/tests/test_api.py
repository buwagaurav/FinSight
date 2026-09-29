"""The HTTP layer: sign-in is enforced, and signed-in requests reach the right user's data. No AI is ever called."""
import pytest
from fastapi.testclient import TestClient

from app import main, research
from app.ai import llm
from app.providers import nse
from tests.conftest import add_company
from tests.test_auth import SECRET, token


@pytest.fixture
def client(clean_db, monkeypatch):
    monkeypatch.setenv("FINSIGHT_API_JWT_SECRET", SECRET)
    add_company(clean_db, "TCS", "Tata Consultancy Services Limited")
    return TestClient(main.app)


def test_health(client):
    assert client.get("/api/health").json() == {"ok": True}


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/me"), ("GET", "/api/watchlist"), ("GET", "/api/watchlist/symbols"), ("POST", "/api/watchlist"),
    ("DELETE", "/api/watchlist/TCS"), ("PATCH", "/api/watchlist/TCS"), ("GET", "/api/watchlist/TCS/details"),
    ("POST", "/api/ask"), ("POST", "/api/company/TCS.NS/report"), ("POST", "/api/screener/parse"),
])
def test_personal_and_ai_endpoints_need_sign_in(client, method, path):
    assert client.request(method, path, json={}).status_code == 401


def test_watchlist_round_trip(client, monkeypatch):
    monkeypatch.setattr(research, "company_report", lambda s: {"scores": {"overall": {"score": 70, "label": "Stable"}},
                                                               "profile": {"price": 1.0, "change_pct": 0.0}})
    monkeypatch.setattr(nse, "announcements", lambda s, n: [])
    me = {"authorization": token()}
    other = {"authorization": token(sub="someone-else", email="b@example.com")}

    assert client.post("/api/watchlist", json={"symbol": "TCS.NS"}, headers=me).json() == {"symbol": "TCS", "watching": True}
    assert client.post("/api/watchlist", json={"symbol": "NOPE"}, headers=me).status_code == 404
    assert client.patch("/api/watchlist/TCS", json={"note": "x" * 201}, headers=me).status_code == 422
    assert client.patch("/api/watchlist/TCS", json={"note": "watch margins"}, headers=me).status_code == 200
    assert client.get("/api/watchlist/symbols", headers=me).json() == ["TCS"]
    assert client.get("/api/watchlist/symbols", headers=other).json() == []

    body = client.get("/api/watchlist", headers=me).json()
    assert body["limit"] == 50 and body["items"][0]["note"] == "watch margins"
    assert client.get("/api/watchlist/TCS/details", headers=me).json()["label"] == "Stable"

    assert client.delete("/api/watchlist/TCS", headers=me).json()["watching"] is False
    assert client.get("/api/watchlist", headers=me).json()["items"] == []


def test_ai_is_not_charged_when_no_model_is_configured(client, monkeypatch):
    monkeypatch.setattr(llm, "is_configured", lambda feature: False)
    me = {"authorization": token()}
    assert client.post("/api/ask", json={"question": "Is TCS cheap?"}, headers=me).status_code == 503
    assert client.get("/api/me", headers=me).json()["ai_usage"]["used"] == 0


def test_ai_allowance_is_enforced(client, monkeypatch):
    monkeypatch.setenv("FINSIGHT_AI_DAILY_LIMIT", "2")
    monkeypatch.setattr(llm, "is_configured", lambda feature: True)
    monkeypatch.setattr(main.assistant, "ask", lambda q, s, h: {"answer": "stub"})
    me = {"authorization": token()}
    codes = [client.post("/api/ask", json={"question": "Is TCS cheap?"}, headers=me).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_background_loader_starts_and_stops_with_the_app(clean_db, monkeypatch):
    started = []
    monkeypatch.setenv("FINSIGHT_BACKGROUND_LOADER", "1")
    monkeypatch.setattr(main.loader, "run_forever", lambda stop: started.append(stop))
    with TestClient(main.app):
        pass
    assert len(started) == 1 and started[0].is_set()


def test_ai_requests_beyond_the_cap_are_told_to_retry_and_not_charged(client, monkeypatch):
    import threading
    monkeypatch.setattr(llm, "is_configured", lambda feature: True)
    monkeypatch.setattr(llm, "_slots", threading.BoundedSemaphore(1))
    monkeypatch.setattr(llm, "AI_WAIT_SECONDS", 0.2)
    release = threading.Event()
    monkeypatch.setattr(main.assistant, "ask", lambda q, s, h: release.wait(5) and {"answer": "ok"})
    me = {"authorization": token()}
    first = {}
    t = threading.Thread(target=lambda: first.update(r=client.post("/api/ask", json={"question": "Is it cheap?"}, headers=me)))
    t.start()
    import time
    time.sleep(0.3)                                                    # the only slot is now taken
    busy = client.post("/api/ask", json={"question": "Is it cheap?"}, headers=me)
    assert busy.status_code == 503 and "busy" in busy.json()["detail"]
    release.set()
    t.join()
    assert first["r"].status_code == 200
    assert client.get("/api/me", headers=me).json()["ai_usage"]["used"] == 1   # the busy one wasn't charged
