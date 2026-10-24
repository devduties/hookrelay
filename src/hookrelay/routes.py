import secrets

from fastapi import APIRouter, HTTPException, Request, status

from hookrelay.errors import NotFoundError
from hookrelay.schemas import (
    AttemptView,
    EndpointCreate,
    EndpointCreated,
    EndpointView,
    EventCreate,
    EventResult,
)

router = APIRouter()


@router.post("/endpoints", response_model=EndpointCreated, status_code=status.HTTP_201_CREATED)
def create_endpoint(body: EndpointCreate, request: Request):
    target = str(body.target_url)
    secret = body.secret.get_secret_value() if body.secret else secrets.token_urlsafe(32)
    endpoint = request.app.state.store.create_endpoint(body.name, target, secret)
    return EndpointCreated(
        id=endpoint.id,
        name=endpoint.name,
        target_url=endpoint.target_url,
        secret=endpoint.secret,
        created_at=endpoint.created_at,
        is_active=endpoint.is_active,
    )


@router.get("/endpoints/{endpoint_id}", response_model=EndpointView)
def get_endpoint(endpoint_id: str, request: Request):
    try:
        endpoint = request.app.state.store.get_endpoint(endpoint_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return EndpointView(
        id=endpoint.id,
        name=endpoint.name,
        target_url=endpoint.target_url,
        created_at=endpoint.created_at,
        is_active=endpoint.is_active,
    )


@router.post(
    "/endpoints/{endpoint_id}/events",
    response_model=EventResult,
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_event(endpoint_id: str, body: EventCreate, request: Request):
    store = request.app.state.store
    try:
        endpoint = store.get_endpoint(endpoint_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not endpoint.is_active:
        raise HTTPException(status_code=409, detail="Endpoint is inactive")
    event = store.create_event(endpoint_id, body.payload)
    return EventResult(
        id=event.id,
        endpoint_id=event.endpoint_id,
        received_at=event.received_at,
        status=event.status,
        attempt_count=event.attempt_count,
        next_attempt_at=event.next_attempt_at,
        attempts=[],
    )


@router.get("/events/{event_id}", response_model=EventResult)
def get_event(event_id: str, request: Request):
    store = request.app.state.store
    try:
        event = store.get_event(event_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return EventResult(
        id=event.id,
        endpoint_id=event.endpoint_id,
        received_at=event.received_at,
        status=event.status,
        attempt_count=event.attempt_count,
        next_attempt_at=event.next_attempt_at,
        attempts=[AttemptView.model_validate(attempt) for attempt in store.list_attempts(event_id)],
    )
