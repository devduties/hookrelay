import asyncio
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from hookrelay.auth import require_api_key
from hookrelay.config import Settings
from hookrelay.routes import router
from hookrelay.store import Store
from hookrelay.worker import DeliveryWorker


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = app_settings
        app.state.store = Store(app_settings.database_path)
        stop_event = asyncio.Event()
        worker = DeliveryWorker(app.state.store, app_settings)
        worker_task = asyncio.create_task(worker.run_forever(stop_event))
        try:
            yield
        finally:
            stop_event.set()
            worker_task.cancel()
            try:
                await worker_task
            except asyncio.CancelledError:
                pass

    app = FastAPI(title="HookRelay", version="0.1.0", lifespan=lifespan)
    app.include_router(
        router,
        prefix="/v1",
        dependencies=[Depends(require_api_key(app_settings.api_key))],
    )

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()
