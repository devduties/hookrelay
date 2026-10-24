import asyncio
import logging
from collections.abc import Awaitable, Callable

from hookrelay.config import Settings
from hookrelay.delivery import deliver
from hookrelay.retry import RetryPolicy
from hookrelay.store import Store

logger = logging.getLogger(__name__)
DeliveryFunction = Callable[..., Awaitable[tuple[int | None, str | None, str | None, int, bool]]]


class DeliveryWorker:
    """Poll SQLite for due events and make one delivery attempt at a time."""

    def __init__(
        self,
        store: Store,
        settings: Settings,
        retry_policy: RetryPolicy | None = None,
        deliver_func: DeliveryFunction | None = None,
    ):
        self.store = store
        self.settings = settings
        self.retry_policy = retry_policy or RetryPolicy()
        self.deliver_func = deliver_func or deliver

    async def run_once(self) -> bool:
        event = await asyncio.to_thread(
            self.store.claim_due_event,
            self.settings.worker_lease_seconds,
        )
        if event is None:
            return False

        endpoint = await asyncio.to_thread(self.store.get_endpoint, event.endpoint_id)
        result = await self.deliver_func(
            endpoint.target_url,
            event.payload_json.encode("utf-8"),
            endpoint.secret,
            timeout=self.settings.request_timeout_seconds,
            max_response_bytes=self.settings.max_response_bytes,
        )
        status_code, response_body, error, duration_ms, retryable_error = result
        await asyncio.to_thread(
            self.store.record_attempt,
            event.id,
            status_code,
            response_body,
            error,
            duration_ms,
            retryable_error,
            self.retry_policy,
        )
        return True

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                did_work = await self.run_once()
            except Exception:
                logger.exception("Delivery worker iteration failed")
                did_work = False

            if not did_work:
                try:
                    await asyncio.wait_for(
                        stop_event.wait(),
                        timeout=self.settings.worker_poll_interval_seconds,
                    )
                except TimeoutError:
                    pass
