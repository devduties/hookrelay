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
