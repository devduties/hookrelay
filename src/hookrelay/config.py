import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    database_path: Path
    request_timeout_seconds: float = 5.0
    max_response_bytes: int = 4_096
    worker_poll_interval_seconds: float = 0.5
    worker_lease_seconds: int = 30
    api_key: str | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_path=Path(os.getenv("HOOKRELAY_DATABASE_PATH", "hookrelay.db")),
            request_timeout_seconds=float(os.getenv("HOOKRELAY_REQUEST_TIMEOUT", "5")),
            worker_poll_interval_seconds=float(os.getenv("HOOKRELAY_WORKER_POLL_INTERVAL", "0.5")),
            worker_lease_seconds=int(os.getenv("HOOKRELAY_WORKER_LEASE_SECONDS", "30")),
            api_key=os.getenv("HOOKRELAY_API_KEY") or None,
        )
