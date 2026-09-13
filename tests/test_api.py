from datetime import UTC, datetime, timedelta


async def test_health(client):
    assert (await client.get("/health/live")).json() == {"status": "ok"}


async def test_register_duplicate(client):
    body = {"email": "moss@example.com", "password": "correct-horse-battery"}
    assert (await client.post("/api/v1/auth/register", json=body)).status_code == 201
    assert (await client.post("/api/v1/auth/register", json=body)).status_code == 409


async def test_create_and_list_event(client, auth):
    start = datetime.now(UTC) + timedelta(days=1)
    body = {"title": "高等数学", "starts_at": start.isoformat(), "ends_at": (start + timedelta(minutes=90)).isoformat(), "kind": "course"}
    assert (await client.post("/api/v1/events", json=body, headers=auth)).status_code == 201
    events = (await client.get("/api/v1/events", headers=auth)).json()
    assert len(events) == 1 and events[0]["title"] == "高等数学"


async def test_reject_invalid_event_range(client, auth):
    at = datetime.now(UTC).isoformat()
    assert (await client.post("/api/v1/events", json={"title": "bad", "starts_at": at, "ends_at": at}, headers=auth)).status_code == 422


async def test_task_focus_and_balance(client, auth):
    task = await client.post("/api/v1/tasks", json={"title": "完成报告"}, headers=auth)
    assert task.status_code == 201
    focus = await client.post("/api/v1/focus/start", json={"planned_minutes": 25}, headers=auth)
    assert focus.status_code == 201
    assert (await client.get("/api/v1/rewards/balance", headers=auth)).json() == {"balance": 0}


async def test_focus_lifecycle(client, auth):
    started = await client.post("/api/v1/focus/start", json={"planned_minutes": 25}, headers=auth)
    assert started.status_code == 201
    body = started.json()
    assert body["status"] == "running"
    assert body["planned_minutes"] == 25
    focus_id = body["id"]
    current = await client.get("/api/v1/focus/current", headers=auth)
    assert current.status_code == 200
    assert current.json()["id"] == focus_id
    fetched = await client.get(f"/api/v1/focus/{focus_id}", headers=auth)
    assert fetched.status_code == 200
    finished = await client.post(f"/api/v1/focus/{focus_id}/finish", headers=auth)
    assert finished.status_code == 200
    assert finished.json()["status"] == "completed"
    current = await client.get("/api/v1/focus/current", headers=auth)
    assert current.status_code == 200
    assert current.json() is None

async def test_reject_two_active_focus_sessions(client, auth):
    body = {"planned_minutes": 25}
    first = await client.post("/api/v1/focus/start", json=body, headers=auth)
    assert first.status_code == 201
    second = await client.post("/api/v1/focus/start", json=body, headers=auth)
    assert second.status_code == 409

async def test_cancel_focus(client, auth):
    started = await client.post("/api/v1/focus/start", json={"planned_minutes": 25}, headers=auth)
    focus_id = started.json()["id"]
    cancelled = await client.post(f"/api/v1/focus/{focus_id}/cancel", headers=auth)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["end_reason"] == "cancelled"

async def test_white_noise(client, auth):
    tracks = await client.get("/api/v1/media/tracks", headers=auth)
    assert tracks.status_code == 200
    noise = await client.get("/api/v1/media/noise/white", headers=auth)
    assert noise.status_code == 200
    assert noise.headers["content-type"].startswith("audio/ogg")
    assert len(noise.content) > 0

async def test_unknown_noise(client, auth):
    response = await client.get("/api/v1/media/noise/not-exist", headers=auth)
    assert response.status_code == 404