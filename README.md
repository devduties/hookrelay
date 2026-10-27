# HookRelay

HookRelay is a small self-hosted service that receives webhook events, delivers them to a registered URL, and keeps a record of every attempt so you can see exactly what was sent, what succeeded, and what failed.

## Features

- Register endpoints with a provided secret or a generated one (shown only in the create response).
- Accept JSON events and queue delivery in the background.
- Replay events as new rows with their own IDs and attempt histories.
- Retry network errors, HTTP 408, HTTP 429, and HTTP 5xx responses up to five total attempts.
- Use exponential retry delays beginning at 5 seconds and capped at 5 minutes.
- Treat other non-2xx responses as terminal failures.
- Lease due events in SQLite so concurrent workers do not claim the same event at once; a crashed worker's lease expires.
- Send `X-HookRelay-Signature` as a lowercase hexadecimal HMAC-SHA256 digest of the exact body bytes.
- Record every delivery attempt with its status code, response body (up to 4 KB), error message, and elapsed time.
- Reject endpoints that resolve to loopback, private, or reserved IP addresses; HTTP redirects are not followed.
- Optionally protect every `/v1/` route with a Bearer API key configured through `HOOKRELAY_API_KEY`; `/health` remains public.

When `HOOKRELAY_API_KEY` is unset or empty, API authentication is disabled for local development. Endpoint secrets are stored in plaintext in SQLite, there is no encryption at rest. HookRelay is not ready for public deployment yet; keep the database file private and don't run it on a network you don't control.

## Run locally

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -e ".[dev]"
uvicorn hookrelay.main:app --reload
```

Open `http://127.0.0.1:8000/docs` for the API explorer. By default the database is `hookrelay.db`; set `HOOKRELAY_DATABASE_PATH` to change it. `HOOKRELAY_REQUEST_TIMEOUT` sets the outbound HTTP timeout in seconds (default: 5). Set `HOOKRELAY_API_KEY` to require `Authorization: Bearer <key>` on API requests.

## Example

Create an endpoint:

```bash
curl -X POST http://127.0.0.1:8000/v1/endpoints \
  -H "Content-Type: application/json" \
  -d '{"name":"Orders","target_url":"https://example.com/webhooks","secret":"replace-me"}'
```

The response includes the signing secret because it is returned only when the endpoint is created. Save it now, it won't appear again in future requests.

Submit an event using the returned endpoint ID:

```bash
curl -X POST http://127.0.0.1:8000/v1/endpoints/ENDPOINT_ID/events \
  -H "Content-Type: application/json" \
  -d '{
    "payload": {
      "event": "payment.failed",
      "payment_id": "pay_8f3kx91",
      "amount": 4900,
      "currency": "usd",
      "failed_at": "2026-10-27T00:14:30Z"
    }
  }'
```

The response includes the event ID. Use `GET /v1/events/EVENT_ID` to check its delivery status and see each attempt.

The receiver verifies the signature by computing `HMAC-SHA256(secret, raw_request_body)`, hex-encoding the digest, and comparing it to `X-HookRelay-Signature` using a constant-time comparison. Do not parse and re-serialize the JSON before checking; whitespace and byte encoding affect the signature.

## Retry behavior

HookRelay tries delivery up to five times. The first attempt fires immediately; if it fails, the next ones wait 5, 10, 20, and 40 seconds. A 2xx response marks the event `delivered`. Network errors, 408, 429, and 5xx responses are worth retrying; anything else, including 4xx client errors, is treated as a permanent failure and won't be retried. If all five attempts fail, the event is marked `failed` and stays that way unless you replay it.

## Replay events

To redeliver a past event, call `POST /v1/events/{event_id}/replay`. It works on any event regardless of its current status. A replay always creates a new pending event with a fresh ID; it never resets or otherwise modifies the source event. The new event uses the same endpoint and payload, starts fresh with zero attempts, and records the source event's ID in `source_event_id`. The API returns `202 Accepted` with the new event.

The worker delivers a replay just like a newly submitted event. It gets its own delivery attempts and status, while the source event and its attempt history remain unchanged. Replays can be chained -- replaying a replay creates another new event with its own `source_event_id` pointing to the one before it.

If your receiver can't safely process the same event twice, make sure to check for duplicates before acting on a replayed event.

## Development

Run the test suite and linter before committing:

```bash
pytest
ruff check .
```

