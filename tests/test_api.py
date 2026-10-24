import asyncio

import httpx
import pytest

from hookrelay.config import Settings
from hookrelay.main import create_app


@pytest.fixture
async def client(tmp_path):
    app = create_app(Settings(tmp_path / "hookrelay.sqlite3", worker_poll_interval_seconds=3600))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as test_client:
            yield test_client


@pytest.mark.asyncio
async def test_create_ingest_and_read_event(client):
    endpoint_response = await client.post(
        "/v1/endpoints",
        json={
            "name": "Orders",
            "target_url": "https://receiver.example/hook",
            "secret": "my-secret",
        },
    )
    assert endpoint_response.status_code == 201
    endpoint = endpoint_response.json()
    assert endpoint["secret"] == "my-secret"

    ingest_response = await client.post(
        f"/v1/endpoints/{endpoint['id']}/events", json={"payload": {"id": 17}}
    )
    assert ingest_response.status_code == 202
    event = ingest_response.json()
    assert event["status"] == "pending"
    assert event["attempt_count"] == 0
    assert event["attempts"] == []

    endpoint_read = await client.get(f"/v1/endpoints/{endpoint['id']}")
    assert "secret" not in endpoint_read.json()
    event_read = await client.get(f"/v1/events/{event['id']}")
    assert event_read.json()["id"] == event["id"]


@pytest.mark.asyncio
async def test_unknown_endpoint_returns_404(client):
    response = await client.post("/v1/endpoints/not-found/events", json={"payload": {"id": 17}})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_app_worker_delivers_queued_event(tmp_path, monkeypatch):
    async def fake_deliver(_url, _payload, _secret, **_kwargs):
        return 202, "accepted", None, 1, False

    monkeypatch.setattr("hookrelay.worker.deliver", fake_deliver)
    app = create_app(Settings(tmp_path / "hookrelay.sqlite3", worker_poll_interval_seconds=0.01))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            endpoint = (
                await client.post(
                    "/v1/endpoints",
                    json={"name": "Orders", "target_url": "https://receiver.example/hook"},
                )
            ).json()
            accepted = await client.post(
                f"/v1/endpoints/{endpoint['id']}/events", json={"payload": {"id": 42}}
            )
            assert accepted.status_code == 202

            for _ in range(100):
                result = (await client.get(f"/v1/events/{accepted.json()['id']}")).json()
                if result["status"] == "delivered":
                    break
                await asyncio.sleep(0.01)

            assert result["status"] == "delivered"
            assert result["attempt_count"] == 1
            assert result["attempts"][0]["status_code"] == 202
