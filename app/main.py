from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import chat, health
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestIDMiddleware

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # TODO (step 3): load committed documents and build the retrieval index here.
    app.state.documents_loaded = 0
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    application = FastAPI(title="PropLens", lifespan=lifespan)
    application.state.documents_loaded = 0
    application.add_middleware(RequestIDMiddleware)
    register_exception_handlers(application)
    application.include_router(health.router)
    application.include_router(chat.router)
    application.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return application


app = create_app()
