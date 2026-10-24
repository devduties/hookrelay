# HookRelay

HookRelay is a small webhook delivery service built to make integrations observable. It accepts an event for a registered endpoint, queues it durably in SQLite, signs the exact JSON request bytes with HMAC-SHA256, and delivers it in the background while recording each attempt.

## Current scope

- Register endpoints with a provided secret or a generated one (shown only in the create response).
- Accept JSON events quickly and queue delivery in the background.
- Retry network errors, HTTP 408, HTTP 429, and HTTP 5xx responses up to five total attempts.
- Use exponential retry delays beginning at 5 seconds and capped at 5 minutes.
- Treat other non-2xx responses as terminal failures.
- Lease due events in SQLite so concurrent workers do not claim the same event at once; a crashed worker's lease expires.
- Send `X-HookRelay-Signature` as a lowercase hexadecimal HMAC-SHA256 digest of the exact body bytes.
- Persist events and individual delivery attempts, including status, bounded response text, errors, and elapsed time.
- Reject endpoints that resolve to loopback, private, or reserved IP addresses; HTTP redirects are not followed.
- Optionally protect every `/v1/` route with a Bearer API key configured through `HOOKRELAY_API_KEY`; `/health` remains public.

When `HOOKRELAY_API_KEY` is unset or empty, API authentication is disabled for local development. Secret encryption is not implemented, and endpoint secrets are stored in plaintext in SQLite. This milestone is not ready for public deployment; protect the database file and do not expose the service to untrusted users.

## Run locally

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -e ".[dev]"
uvicorn hookrelay.main:app --reload
```

Open `http://127.0.0.1:8000/docs` for the API explorer. By default the database is `hookrelay.db`; set `HOOKRELAY_DATABASE_PATH` to change it. `HOOKRELAY_REQUEST_TIMEOUT` sets the outbound HTTP timeout in seconds. Set `HOOKRELAY_API_KEY` to require `Authorization: Bearer <key>` on API requests.

## Example

Create an endpoint:

```bash
curl -X POST http://127.0.0.1:8000/v1/endpoints \
  -H "Content-Type: application/json" \
  -d '{"name":"Orders","target_url":"https://example.com/webhooks","secret":"replace-me"}'
```

The response includes the signing secret because it is returned only when the endpoint is created. Store it securely; subsequent endpoint reads omit it.

Submit an event using the returned endpoint ID:

```bash
curl -X POST http://127.0.0.1:8000/v1/endpoints/ENDPOINT_ID/events \
  -H "Content-Type: application/json" \
  -d '{"payload":{"event":"order.created","order_id":123}}'
```

The request returns `202 Accepted` with the queued event ID. Poll `GET /v1/events/EVENT_ID` for its current state and attempt history.

The receiver verifies the signature by computing `HMAC-SHA256(secret, raw_request_body)`, hex-encoding the digest, and comparing it to `X-HookRelay-Signature` using a constant-time comparison. Do not parse and re-serialize the JSON before checking; whitespace and byte encoding affect the signature.

## Retry behavior

The first delivery is attempt one. Transient failures are retried after 5, 10, 20, and 40 seconds. A successful 2xx response marks the event `delivered`. A network error, 408, 429, or 5xx response keeps it `pending` until the next due attempt. Other responses, including other 3xx and 4xx statuses, mark it `failed`. After the fifth failed attempt, the event is terminally `failed`.

## Development

```bash
pytest
ruff check .
```

