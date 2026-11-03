"""Shared fixtures. DB tests run only when TEST_DATABASE_URL points at a disposable Postgres
(CI provides one); locally they are skipped."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aggregator.db.models import Base
from aggregator.db.session import create_engine, create_session_factory


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set (needs Postgres with pg_trgm)")
    engine = create_engine(url)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield create_session_factory(engine)
    finally:
        await engine.dispose()
