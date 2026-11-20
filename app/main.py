import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import chat, health
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestIDMiddleware
from app.llm.openrouter import OpenRouterClient
from app.retrieval.bm25 import BM25Retriever
from app.retrieval.chunking import chunk_documents
from app.retrieval.load import load_documents

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    documents, counts = load_documents(app.state.settings.data_dir)
    chunks = chunk_documents(documents)
    app.state.documents_loaded = len(documents)
    app.state.document_counts = counts
    app.state.retriever = BM25Retriever(chunks)
    app.state.llm_client = OpenRouterClient(app.state.settings)
    logging.getLogger(__name__).info(
        "Search index ready: documents=%d chunks=%d", len(documents), len(chunks)
    )
    try:
        yield
    finally:
        await app.state.llm_client.aclose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    application = FastAPI(title="PropLens", lifespan=lifespan)
    application.state.settings = settings
    application.state.documents_loaded = 0
    application.state.document_counts = {"darglobal": 0, "wasalt": 0}
    application.add_middleware(RequestIDMiddleware)
    register_exception_handlers(application)
    application.include_router(health.router)
    application.include_router(chat.router)
    application.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return application


app = create_app()
