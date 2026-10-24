from dataclasses import dataclass
from datetime import datetime
from typing import Literal

EventStatus = Literal["pending", "delivered", "failed"]


@dataclass(frozen=True, slots=True)
class Endpoint:
    id: str
    name: str
    target_url: str
    secret: str
    created_at: datetime
    is_active: bool


@dataclass(frozen=True, slots=True)
class Event:
    id: str
    endpoint_id: str
    payload_json: str
    received_at: datetime
    status: EventStatus
    attempt_count: int
    next_attempt_at: datetime | None


@dataclass(frozen=True, slots=True)
class Attempt:
    id: int
    event_id: str
    attempted_at: datetime
    status_code: int | None
    response_body: str | None
    error: str | None
    duration_ms: int
