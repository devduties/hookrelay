from contextlib import asynccontextmanager

import httpx
import pytest

from hookrelay.main import create_app


@asynccontextmanager
async def endpoint_client(tmp_path, monkeypatch, api_key: str | None):
    monkeypatch.setenv("HOOKRELAY_DATABASE_PATH", str(tmp_path / "hookrelay.sqlite3"))
    if api_key is None:
        monkeypatch.delenv("HOOKRELAY_API_KEY", raising=False)
    else:
        monkeypatch.setenv("HOOKRELAY_API_KEY", api_key)

    app = create_app()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            endpoint = app.state.store.create_endpoint(
                "Orders", "https://receiver.example/hook", "secret"
            )
            yield client, endpoint.id


@pytest.mark.asyncio
async def test_missing_bearer_token_is_rejected(tmp_path, monkeypatch):
    async with endpoint_client(tmp_path, monkeypatch, "test-api-key") as (client, endpoint_id):
        response = await client.get(f"/v1/endpoints/{endpoint_id}")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.asyncio
async def test_wrong_bearer_token_is_rejected(tmp_path, monkeypatch):
    async with endpoint_client(tmp_path, monkeypatch, "test-api-key") as (client, endpoint_id):
        response = await client.get(
            f"/v1/endpoints/{endpoint_id}", headers={"Authorization": "Bearer wrong-key"}
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_correct_bearer_token_is_accepted(tmp_path, monkeypatch):
    async with endpoint_client(tmp_path, monkeypatch, "test-api-key") as (client, endpoint_id):
        response = await client.get(
            f"/v1/endpoints/{endpoint_id}", headers={"Authorization": "Bearer test-api-key"}
        )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_authentication_is_optional_when_environment_key_is_unset(tmp_path, monkeypatch):
    async with endpoint_client(tmp_path, monkeypatch, None) as (client, endpoint_id):
        response = await client.get(f"/v1/endpoints/{endpoint_id}")

    assert response.status_code == 200
