import hashlib
import hmac

import httpx
import pytest

from hookrelay.delivery import deliver, signature_for


def test_signature_matches_hmac_sha256_over_exact_payload_bytes():
    payload = b'{"message":"caf\xc3\xa9"}'
    expected = hmac.new(b"test-secret", payload, hashlib.sha256).hexdigest()
    assert signature_for(payload, "test-secret") == expected


@pytest.mark.asyncio
async def test_delivery_sends_exact_payload_and_signature(monkeypatch):
    monkeypatch.setattr("hookrelay.delivery.ensure_public_target", lambda _url: None)
    payload = b'{"event":"created"}'
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = await request.aread()
        captured["signature"] = request.headers["X-HookRelay-Signature"]
        return httpx.Response(202, text="accepted")

    status, response, error, _duration, retryable_error = await deliver(
        "https://receiver.example/hook", payload, "secret", transport=httpx.MockTransport(handler)
    )
    assert (status, response, error) == (202, "accepted", None)
    assert retryable_error is False
    assert captured["body"] == payload
    assert captured["signature"] == signature_for(payload, "secret")


@pytest.mark.asyncio
async def test_delivery_rejects_private_target(monkeypatch):
    from hookrelay.errors import UnsafeTargetError

    def reject(_url):
        raise UnsafeTargetError("Target must resolve only to public IP addresses")

    monkeypatch.setattr("hookrelay.delivery.ensure_public_target", reject)
    status, response, error, _duration, retryable_error = await deliver(
        "http://127.0.0.1/hook", b"{}", "secret"
    )
    assert status is None
    assert response is None
    assert "public IP" in error
    assert retryable_error is False
