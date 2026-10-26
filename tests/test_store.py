from hookrelay.store import Store


def test_event_and_attempt_are_persisted(tmp_path):
    store = Store(tmp_path / "hookrelay.sqlite3")
    endpoint = store.create_endpoint("Orders", "https://receiver.example/hook", "secret")
    event = store.create_event(endpoint.id, {"id": 1})
    attempt = store.record_attempt(event.id, 200, "ok", None, 7)

    loaded = Store(tmp_path / "hookrelay.sqlite3").get_event(event.id)
    assert loaded.status == "delivered"
    assert loaded.attempt_count == 1
    assert store.list_attempts(event.id) == [attempt]


def test_existing_events_table_migrates_replay_source_column(tmp_path):
    import sqlite3

    database_path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE endpoints (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, target_url TEXT NOT NULL,
                secret TEXT NOT NULL, created_at TEXT NOT NULL, is_active INTEGER NOT NULL
            );
            CREATE TABLE events (
                id TEXT PRIMARY KEY,
                endpoint_id TEXT NOT NULL REFERENCES endpoints(id),
                payload_json TEXT NOT NULL,
                received_at TEXT NOT NULL,
                status TEXT NOT NULL,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TEXT,
                last_error TEXT,
                locked_until TEXT
            );
            INSERT INTO endpoints VALUES (
                'endpoint-1', 'Orders', 'https://receiver.example/hook', 'secret',
                '2026-10-26T00:00:00+00:00', 1
            );
            INSERT INTO events (
                id, endpoint_id, payload_json, received_at, status, attempt_count
            ) VALUES (
                'legacy-event', 'endpoint-1', '{"id":1}',
                '2026-10-26T00:00:00+00:00', 'delivered', 1
            );
            """
        )

    store = Store(database_path)
    original = store.get_event("legacy-event")
    replay = store.replay_event(original.id)

    assert original.source_event_id is None
    assert replay.source_event_id == original.id
    assert replay.payload_json == original.payload_json
