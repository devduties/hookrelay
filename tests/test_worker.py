import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from hookrelay.config import Settings
from hookrelay.store import Store
from hookrelay.worker import DeliveryWorker


@pytest.mark.asyncio
async def test_worker_schedules_retry_after_server_error(tmp_path):
    async def deliver_stub(*_args, **_kwargs):
        return 503, "temporarily unavailable", None, 3, False

    settings = Settings(tmp_path / "hookrelay.sqlite3")
    store = Store(settings.database_path)
    endpoint = store.create_endpoint("Orders", "https://receiver.example/hook", "secret")
    event = store.create_event(endpoint.id, {"id": 1})
    worker = DeliveryWorker(store, settings, deliver_func=deliver_stub)

    started_at = datetime.now(UTC)
    assert await worker.run_once() is True
    finished_at = datetime.now(UTC)

    saved = store.get_event(event.id)
    assert saved.status == "pending"
    assert saved.attempt_count == 1
    assert saved.next_attempt_at is not None
    assert started_at + timedelta(seconds=5) <= saved.next_attempt_at
    assert saved.next_attempt_at <= finished_at + timedelta(seconds=5)
    assert store.list_attempts(event.id)[0].status_code == 503


@pytest.mark.asyncio
async def test_worker_marks_client_error_terminal(tmp_path):
    async def deliver_stub(*_args, **_kwargs):
        return 400, "bad request", None, 3, False

    settings = Settings(tmp_path / "hookrelay.sqlite3")
    store = Store(settings.database_path)
    endpoint = store.create_endpoint("Orders", "https://receiver.example/hook", "secret")
    event = store.create_event(endpoint.id, {"id": 1})
    worker = DeliveryWorker(store, settings, deliver_func=deliver_stub)

    await worker.run_once()

    saved = store.get_event(event.id)
    assert saved.status == "failed"
    assert saved.attempt_count == 1
    assert saved.next_attempt_at is None


@pytest.mark.asyncio
async def test_worker_does_not_call_receiver_before_retry_is_due(tmp_path):
    calls = 0

    async def deliver_stub(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return 503, "temporarily unavailable", None, 3, False

    settings = Settings(tmp_path / "hookrelay.sqlite3")
    store = Store(settings.database_path)
    endpoint = store.create_endpoint("Orders", "https://receiver.example/hook", "secret")
    event = store.create_event(endpoint.id, {"id": 1})
    worker = DeliveryWorker(store, settings, deliver_func=deliver_stub)

    await worker.run_once()
    assert await worker.run_once() is False
    assert calls == 1
    assert store.get_event(event.id).attempt_count == 1


@pytest.mark.asyncio
async def test_worker_marks_event_failed_after_five_total_attempts(tmp_path):
    async def deliver_stub(*_args, **_kwargs):
        return 503, "temporarily unavailable", None, 3, False

    settings = Settings(tmp_path / "hookrelay.sqlite3")
    store = Store(settings.database_path)
    endpoint = store.create_endpoint("Orders", "https://receiver.example/hook", "secret")
    event = store.create_event(endpoint.id, {"id": 1})
    worker = DeliveryWorker(store, settings, deliver_func=deliver_stub)

    for attempt_number in range(1, 6):
        if attempt_number > 1:
            with sqlite3.connect(settings.database_path) as connection:
                connection.execute(
                    "UPDATE events SET next_attempt_at = ?, locked_until = NULL WHERE id = ?",
                    ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), event.id),
                )
        assert await worker.run_once() is True

    saved = store.get_event(event.id)
    assert saved.status == "failed"
    assert saved.attempt_count == 5
    assert saved.next_attempt_at is None
    assert len(store.list_attempts(event.id)) == 5
