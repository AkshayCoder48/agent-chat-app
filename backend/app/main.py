# ruff: noqa: I001 - Imports structured for Jinja2 template conditionals
"""FastAPI application entry point."""

import logging
import secrets
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from typing import TypedDict

from fastapi import FastAPI
from fastapi_pagination import add_pagination
from starlette.middleware.cors import CORSMiddleware

from app.api.exception_handlers import register_exception_handlers
from app.api.router import api_router
from app.core.config import settings
from app.db.session import close_db, get_db_context
from app.core.logfire_setup import instrument_app, setup_logfire
from app.core.logfire_setup import instrument_asyncpg
from app.core.logfire_setup import instrument_pydantic_ai
from app.core.logging import setup_logging
from app.core.middleware import RequestIDMiddleware
from app.services.rag.embeddings import EmbeddingService
from app.services.rag.vectorstore import PgVectorStore
from app.services.rag.vectorstore import BaseVectorStore

logger = logging.getLogger(__name__)


class LifespanState(TypedDict, total=False):
    """Lifespan state - resources available via request.state."""
    embedding_service: EmbeddingService
    vector_store: BaseVectorStore


def _run_migrations_on_startup() -> None:
    """Run Alembic migrations to head.

    Imported lazily so the rest of the app can boot even if alembic or its
    config is unavailable. Runs synchronously in a thread to avoid blocking
    the event loop.
    """
    import asyncio
    import os
    from concurrent.futures import ThreadPoolExecutor

    # Skip when explicitly disabled (e.g. for tests or local dev where the
    # developer wants to control migration timing).
    if os.environ.get("SKIP_AUTO_MIGRATIONS", "").lower() in {"1", "true", "yes"}:
        logger.info("Skipping auto-migrations (SKIP_AUTO_MIGRATIONS set)")
        return

    def _do_upgrade() -> None:
        from alembic import command
        from alembic.config import Config

        # alembic.ini lives at the repo root (backend/), and the working
        # directory at startup is /app (the backend root in the container).
        cfg = Config("alembic.ini")
        # Stamp the version table if it doesn't exist yet — without this,
        # `upgrade head` on a fresh DB would try to run every migration from
        # scratch, which is what we want.
        command.upgrade(cfg, "head")

    try:
        # Run in a thread so we don't block the event loop on the (sync)
        # alembic command. The pool is small because this is one-shot.
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_do_upgrade)
            future.result(timeout=120)  # 2-minute ceiling
        logger.info("Auto-migrations applied successfully")
    except Exception as exc:
        logger.warning("Auto-migration failed: %s", exc, exc_info=True)



@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[LifespanState, None]:
    """Application lifespan - startup and shutdown events.

    Resources yielded here are available via request.state in route handlers.
    See: https://asgi.readthedocs.io/en/latest/specs/lifespan.html#lifespan-state
    """
    state: LifespanState = {}
    setup_logfire()
    instrument_asyncpg()
    instrument_pydantic_ai()

    # Auto-run Alembic migrations on startup so HF Space / single-instance
    # deploys don't require a manual `agent_chat_app db upgrade` step.
    # Failures are logged but don't abort startup — the app may still be
    # partially functional (e.g. for routes that don't touch the new column).
    try:
        _run_migrations_on_startup()
    except Exception as exc:
        logger.warning("Startup migration failed (continuing anyway): %s", exc)

    embedder: EmbeddingService | None = None
    try:
        embedder = EmbeddingService(settings=settings.rag)
        embedder.warmup()
        state["embedding_service"] = embedder
    except Exception as e:
        logger.error("Embedding service warmup failed: %s. RAG will not be available.", e)
    if embedder is not None:
        try:
            vector_store = PgVectorStore(settings=settings.rag, embedding_service=embedder)
            state["vector_store"] = vector_store
        except Exception as e:
            logger.error("pgvector connection failed: %s. Vector store will not be available.", e)
    yield state
    if "vector_store" in state:
        with suppress(Exception):
            await state["vector_store"].engine.dispose()  # type: ignore[attr-defined]

    await close_db()


SHOW_DOCS_ENVIRONMENTS = ("local", "staging", "development")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    show_docs = settings.ENVIRONMENT in SHOW_DOCS_ENVIRONMENTS
    openapi_url = f"{settings.API_V1_STR}/openapi.json" if show_docs else None
    docs_url = "/docs" if show_docs else None
    redoc_url = "/redoc" if show_docs else None

    openapi_tags = [
        {
            "name": "health",
            "description": "Health check endpoints for monitoring and Kubernetes probes",
        },
        {
            "name": "auth",
            "description": "Authentication endpoints - login, register, token refresh",
        },
        {
            "name": "users",
            "description": "User management endpoints",
        },
        {
            "name": "conversations",
            "description": "AI conversation persistence - manage chat history",
        },
        {
            "name": "agent",
            "description": "AI agent WebSocket endpoint for real-time chat",
        },
        {
            "name": "websocket",
            "description": "WebSocket endpoints for real-time communication",
        },
        {
            "name": "rag",
            "description": "Retrieval Augmented Generation endpoints",
        },
    ]

    setup_logging()

    app = FastAPI(
        title=settings.PROJECT_NAME,
        summary="FastAPI application with Logfire observability",
        description="""
AI Agent Chat App

## Features
- **Authentication**: JWT-based authentication with refresh tokens
- **API Key**: Header-based API key authentication
- **Database**: Async database operations
- **AI Agent**: PydanticAI-powered conversational assistant
- **Observability**: Logfire integration for tracing and monitoring
- **RAG**: Retrieval Augmented Generation with Milvus and LangChain

## Documentation

- [Swagger UI](/docs) - Interactive API documentation
- [ReDoc](/redoc) - Alternative documentation view
        """.strip(),
        version="0.1.0",
        openapi_url=openapi_url,
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_tags=openapi_tags,
        contact={
            "name": "NormieeBroo",
            "email": "noreply@normiebroo.dev",
        },
        license_info={
            "name": "MIT",
            "identifier": "MIT",
        },
        lifespan=lifespan,
    )
    # setup_logfire() is also called from the lifespan for the runtime app, but
    # we call it here too so that import-time test clients (which never run
    # lifespan) silence the "configure first" warning. setup_logfire() is
    # idempotent via a module-level guard in logfire_setup.py.
    setup_logfire()
    instrument_app(app)

    app.add_middleware(RequestIDMiddleware)

    register_exception_handlers(app)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
        allow_methods=settings.CORS_ALLOW_METHODS,
        allow_headers=settings.CORS_ALLOW_HEADERS,
    )

    app.include_router(api_router, prefix=settings.API_V1_STR)

    add_pagination(app)

    return app


app = create_app()
