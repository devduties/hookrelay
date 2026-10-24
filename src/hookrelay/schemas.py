from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, SecretStr


class EndpointCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    target_url: HttpUrl
    secret: SecretStr | None = None


class EndpointCreated(BaseModel):
    id: str
    name: str
    target_url: str
    secret: str
    created_at: datetime
    is_active: bool


class EndpointView(BaseModel):
    id: str
    name: str
    target_url: str
    created_at: datetime
    is_active: bool


class EventCreate(BaseModel):
    payload: dict[str, Any]


class EventView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    endpoint_id: str
    received_at: datetime
    status: Literal["pending", "delivered", "failed"]
    attempt_count: int
    next_attempt_at: datetime | None = None


class AttemptView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_id: str
    attempted_at: datetime
    status_code: int | None
    response_body: str | None
    error: str | None
    duration_ms: int


class EventResult(EventView):
    attempts: list[AttemptView]
