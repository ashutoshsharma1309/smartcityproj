"""Shared setup for the pipeline scripts.

Puts ``backend/`` on the import path so scripts can use the application's
models, settings and session factory, and exposes one place to open a database
session. Every script goes through here, so they cannot drift into using
different connection settings from the API.
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_ROOT = REPO_ROOT / "backend"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import Settings, get_settings  # noqa: E402
from app.core.logging import configure_logging  # noqa: E402


def settings() -> Settings:
    return get_settings()


def setup_logging() -> None:
    configure_logging(get_settings())


@asynccontextmanager
async def session_scope() -> AsyncIterator["AsyncSession"]:  # noqa: F821
    """Open a session against the configured database and dispose the engine."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    config = get_settings()
    engine = create_async_engine(config.database_url, echo=config.db_echo)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()


def data_path(*parts: str) -> Path:
    return REPO_ROOT.joinpath("data", *parts)
