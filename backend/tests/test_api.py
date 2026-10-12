"""End-to-end API flow with the weather service stubbed (no network)."""
import os
import tempfile
import uuid

os.environ["AGRI_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")  # ignored when DATABASE_URL is set

import pytest
from fastapi.testclient import TestClient

from app import main, weather
from tests.test_risk_engine import make_weather


@pytest.fixture(autouse=True)
def no_rain_gauge(monkeypatch):
    monkeypatch.setattr(weather, "measured_rain", lambda lat, lon: {"mm": 0.3, "station": "Test gauge", "distance_km": 2.0})


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(weather, "fetch_forecast", lambda lat, lon, tz=None: make_weather(rain=[25, 20, 10, 0, 0, 0, 0]))
    with TestClient(main.app) as c:
        token = c.post("/api/session").json()["token"]
        c.headers["Authorization"] = f"Bearer {token}"
        r = c.post("/api/auth/register", json={"email": f"{uuid.uuid4().hex[:10]}@example.com", "password": "correct-horse"})
        assert r.status_code == 200, r.text
        yield c


@pytest.fixture()
def anon(monkeypatch):
    monkeypatch.setattr(weather, "fetch_forecast", lambda lat, lon, tz=None: make_weather())
    with TestClient(main.app) as c:
        c.headers["Authorization"] = f"Bearer {c.post('/api/session').json()['token']}"
        yield c


def test_full_flow(client):
    farm = client.post("/api/farms", json={"latitude": 52.2, "longitude": 0.1, "location_label": "Cambridge",
                                           "onboarding_step": 2}).json()
    fid = farm["id"]
    assert farm["status"] == "draft"
    client.put(f"/api/farms/{fid}", json={
        "production_types": ["vegetables"], "production_items": [{"type": "vegetables", "name": "Potatoes"}],
        "conditions": {"water_access": "rainfall_only"}, "main_concern": "weather", "status": "complete"})

    d = client.get(f"/api/farms/{fid}/dashboard").json()
    assert d["weather"]["status"] == "fresh"
    rain = next(a for a in d["assessments"] if a["hazard"] == "heavy_rain")
    assert rain["level"] == "high" and rain["model_version"] == "rules-2026.10-v2"

    # cached: second call reuses the same run
    d2 = client.get(f"/api/farms/{fid}/dashboard").json()
    assert d2["assessments"][0]["id"] == d["assessments"][0]["id"]

    # follow-up answer re-runs assessment
    client.post(f"/api/farms/{fid}/follow-up", json={"key": "drainage", "value": "good"})
    d3 = client.get(f"/api/farms/{fid}/dashboard").json()
    rain3 = next(a for a in d3["assessments"] if a["hazard"] == "heavy_rain")
    assert rain3["id"] != rain["id"]
    assert all(m["key"] != "drainage" for m in rain3["missing_inputs"])

    rec_id = rain3["recommendations"][0]["id"]
    assert client.post(f"/api/recommendations/{rec_id}/feedback", json={"useful": True}).status_code == 200
    client.post(f"/api/recommendations/{rec_id}/feedback", json={"action_taken": True})
    a = client.get(f"/api/assessments/{rain3['id']}").json()
    assert a["recommendations"][0]["feedback"]["useful"] == 1
    assert a["recommendations"][0]["feedback"]["action_taken"] == 1

    h = client.get(f"/api/farms/{fid}/history").json()["history"]
    assert any(x["hazard"] == "heavy_rain" for x in h)


def test_other_users_cannot_see_farm(client):
    fid = client.post("/api/farms", json={"latitude": 1, "longitude": 1}).json()["id"]
    other = client.post("/api/session").json()["token"]
    r = client.get(f"/api/farms/{fid}", headers={"Authorization": f"Bearer {other}"})
    assert r.status_code == 404


def test_weather_outage_is_handled(client, monkeypatch):
    def boom(lat, lon, tz=None):
        raise ConnectionError("down")
    monkeypatch.setattr(weather, "fetch_forecast", boom)
    fid = client.post("/api/farms", json={"latitude": 10, "longitude": 10, "production_types": ["fruit"]}).json()["id"]
    d = client.get(f"/api/farms/{fid}/dashboard").json()
    assert d["weather"]["status"] == "unavailable"
    assert d["assessments"] == []


def test_delete_all_data(client):
    fid = client.post("/api/farms", json={"latitude": 1, "longitude": 1}).json()["id"]
    assert client.delete("/api/me").json()["deleted"]
    assert client.get(f"/api/farms/{fid}").status_code == 401


def test_anonymous_can_draft_but_not_see_results(anon):
    fid = anon.post("/api/farms", json={"latitude": 1, "longitude": 1, "production_types": ["fruit"]}).json()["id"]
    assert anon.get(f"/api/farms/{fid}").status_code == 200
    assert anon.get(f"/api/farms/{fid}/dashboard").status_code == 403
    assert anon.put(f"/api/farms/{fid}", json={"status": "complete"}).status_code == 403


def test_register_login_logout_and_draft_transfer(anon):
    email = f"{uuid.uuid4().hex[:10]}@Example.com"
    assert anon.post("/api/auth/register", json={"email": email, "password": "short"}).status_code == 422
    assert anon.post("/api/auth/register", json={"email": email, "password": "a-good-password"}).json()["registered"]
    assert anon.get("/api/me").json()["email"] == email.lower()
    assert anon.post("/api/auth/logout").json()["ok"]
    assert anon.get("/api/me").status_code == 401

    # new device: start a draft anonymously, then sign in -> draft moves to the account
    anon.headers["Authorization"] = f"Bearer {anon.post('/api/session').json()['token']}"
    fid = anon.post("/api/farms", json={"latitude": 2, "longitude": 2}).json()["id"]
    assert anon.post("/api/auth/login", json={"email": email, "password": "wrong-password"}).status_code == 401
    tok = anon.post("/api/auth/login", json={"email": email, "password": "a-good-password"}).json()["token"]
    anon.headers["Authorization"] = f"Bearer {tok}"
    assert [f["id"] for f in anon.get("/api/farms").json()["farms"]] == [fid]

    # duplicate registration is refused
    anon.headers["Authorization"] = f"Bearer {anon.post('/api/session').json()['token']}"
    assert anon.post("/api/auth/register", json={"email": email, "password": "another-pass"}).status_code == 409


def test_login_throttle(anon):
    email = f"{uuid.uuid4().hex[:10]}@example.com"
    for _ in range(5):
        assert anon.post("/api/auth/login", json={"email": email, "password": "nope-nope"}).status_code == 401
    assert anon.post("/api/auth/login", json={"email": email, "password": "nope-nope"}).status_code == 429
