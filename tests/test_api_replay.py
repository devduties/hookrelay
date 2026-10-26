import asyncio
from contextlib import asynccontextmanager

import httpx
import pytest

from hookrelay.config import Settings
from hookrelay.main import create_app
from hookrelay.store import Store


@asynccontextmanager
async def running_client(database_path):
    app = create_app(Settings(database_path))
    app.state.store = Store(database_path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client, app.state.store


async def create_endpoint(client):
    response = await client.post(
        "/v1/endpoints",
        json={
            "name": "Orders",
            "target_url": "https://receiver.example/hook",
            "secret": "test-secret",
        },
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.asyncio
async def test_replay_creates_new_event(tmp_path):
    async with running_client(tmp_path / "hookrelay.sqlite3") as (client, store):
        endpoint = await create_endpoint(client)
        original = store.create_event(endpoint["id"], {"order_id": 17})
        store.record_attempt(original.id, 200, "accepted", None, 3)

        response = await client.post(f"/v1/events/{original.id}/replay")

        assert response.status_code == 202
        replay = response.json()
        assert replay["id"] != original.id
        assert replay["endpoint_id"] == original.endpoint_id
        assert replay["source_event_id"] == original.id
        assert replay["status"] == "pending"
        assert replay["attempt_count"] == 0
        assert replay["attempts"] == []

        stored_replay = store.get_event(replay["id"])
        assert stored_replay.payload_json == original.payload_json
        assert stored_replay.source_event_id == original.id


@pytest.mark.asyncio
async def test_replay_worker_delivers_normally(tmp_path, monkeypatch):
    database_path = tmp_path / "hookrelay.sqlite3"
    store = Store(database_path)
    endpoint = store.create_endpoint(
        "Orders",
        "https://receiver.example/hook",
        "test-secret",
    )
    original = store.create_event(endpoint.id, {"order_id": 42})
    store.record_attempt(original.id, 200, "already delivered", None, 2)

    deliveries = []

    async def fake_deliver(url, payload, secret, **kwargs):
        deliveries.append((url, payload, secret, kwargs))
        return 204, "accepted", None, 4, False

    monkeypatch.setattr("hookrelay.worker.deliver", fake_deliver)
    app = create_app(
        Settings(
            database_path,
            worker_poll_interval_seconds=0.01,
        )
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(f"/v1/events/{original.id}/replay")
            assert response.status_code == 202
            replay_id = response.json()["id"]

            for _ in range(100):
                result = (await client.get(f"/v1/events/{replay_id}")).json()
                if result["status"] == "delivered":
                    break
                await asyncio.sleep(0.01)

            assert result["status"] == "delivered"
            assert result["attempt_count"] == 1
            assert len(result["attempts"]) == 1
            assert result["attempts"][0]["status_code"] == 204
            assert len(deliveries) == 1
            assert deliveries[0][0] == endpoint.target_url
            assert deliveries[0][1] == original.payload_json.encode("utf-8")
            assert deliveries[0][2] == endpoint.secret


@pytest.mark.asyncio
async def test_original_event_unchanged(tmp_path):
    async with running_client(tmp_path / "hookrelay.sqlite3") as (client, store):
        endpoint = await create_endpoint(client)
        original = store.create_event(endpoint["id"], {"order_id": 99})
        store.record_attempt(original.id, 400, "rejected", "HTTP 400", 8)
        event_before = store.get_event(original.id)
        attempts_before = store.list_attempts(original.id)

        response = await client.post(f"/v1/events/{original.id}/replay")

        assert response.status_code == 202
        assert store.get_event(original.id) == event_before
        assert store.list_attempts(original.id) == attempts_before
        assert event_before.status == "failed"
        assert len(attempts_before) == 1


@pytest.mark.asyncio
async def test_replay_of_nonexistent_event(tmp_path):
    async with running_client(tmp_path / "hookrelay.sqlite3") as (client, _):
        response = await client.post("/v1/events/not-a-real-event/replay")

    assert response.status_code == 404
