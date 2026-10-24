import asyncio
import hashlib
import hmac
import ipaddress
import socket
import time
from urllib.parse import urlsplit

import httpx

from hookrelay.errors import UnsafeTargetError


def signature_for(payload: bytes, secret: str) -> str:
    """Return the lowercase hex HMAC-SHA256 digest of the exact transmitted bytes."""
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def ensure_public_target(url: str) -> None:
    """Reject non-HTTP URLs and targets resolving to loopback, private, or reserved IPs."""
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise UnsafeTargetError("Target must be an HTTP(S) URL without embedded credentials")
    host = parsed.hostname.rstrip(".")
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            records = socket.getaddrinfo(
                host,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as exc:
            raise UnsafeTargetError("Target hostname could not be resolved") from exc
        addresses = [ipaddress.ip_address(record[4][0]) for record in records]
    if not addresses or any(not address.is_global for address in addresses):
        raise UnsafeTargetError("Target must resolve only to public IP addresses")


async def deliver(
    url: str,
    payload: bytes,
    secret: str,
    timeout: float = 5.0,
    max_response_bytes: int = 4096,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[int | None, str | None, str | None, int, bool]:
    started = time.perf_counter()
    try:
        await asyncio.to_thread(ensure_public_target, url)
        headers = {
            "Content-Type": "application/json",
            "X-HookRelay-Signature": signature_for(payload, secret),
        }
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=False, transport=transport
        ) as client:
            async with client.stream("POST", url, content=payload, headers=headers) as response:
                body_bytes = bytearray()
                async for chunk in response.aiter_bytes():
                    remaining = max_response_bytes - len(body_bytes)
                    if remaining <= 0:
                        break
                    body_bytes.extend(chunk[:remaining])
                body = bytes(body_bytes).decode("utf-8", errors="replace")
                return (
                    response.status_code,
                    body,
                    None,
                    round((time.perf_counter() - started) * 1000),
                    False,
                )
    except UnsafeTargetError as exc:
        return None, None, str(exc), round((time.perf_counter() - started) * 1000), False
    except httpx.HTTPError as exc:
        return None, None, str(exc), round((time.perf_counter() - started) * 1000), True
