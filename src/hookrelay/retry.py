from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

DeliveryStatus = Literal["delivered", "retrying", "failed"]


@dataclass(frozen=True, slots=True)
class RetryDecision:
    status: DeliveryStatus
    next_attempt_at: datetime | None


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Deterministic, bounded retry policy for a single event."""

    max_attempts: int = 5
    base_delay_seconds: int = 5
    max_delay_seconds: int = 300

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.base_delay_seconds < 1:
            raise ValueError("base_delay_seconds must be positive")
        if self.max_delay_seconds < self.base_delay_seconds:
            raise ValueError("max_delay_seconds cannot be smaller than the base delay")

    def decide(
        self,
        *,
        status_code: int | None,
        error: str | None,
        attempt_number: int,
        retryable_error: bool = False,
        now: datetime | None = None,
    ) -> RetryDecision:
        """Classify the result and, when appropriate, calculate its next due time.

        `attempt_number` includes the current attempt. Thus attempt one schedules the
        first retry, while `max_attempts` is the final allowed attempt.
        """
        if attempt_number < 1:
            raise ValueError("attempt_number must be at least 1")

        if status_code is not None and 200 <= status_code < 300 and error is None:
            return RetryDecision("delivered", None)

        retryable_status = status_code in {408, 429} or (
            status_code is not None and 500 <= status_code < 600
        )
        if not (retryable_error or retryable_status) or attempt_number >= self.max_attempts:
            return RetryDecision("failed", None)

        delay = min(
            self.base_delay_seconds * (2 ** (attempt_number - 1)),
            self.max_delay_seconds,
        )
        decision_time = now or datetime.now(UTC)
        return RetryDecision("retrying", decision_time + timedelta(seconds=delay))
