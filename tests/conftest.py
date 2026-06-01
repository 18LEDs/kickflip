"""
Shared pytest fixtures.

Every test runs against a private in-memory SQLite database (shared across
connections via StaticPool) so tests never touch the real ``grants.db`` and
never hit the network. The Datadog, ServiceNow and scheduler integrations are
replaced with mocks so we can assert exactly what would have been pushed.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401 — register the ORM model with Base.metadata
from app.database import Base, get_db
from app.models import Grant


@pytest_asyncio.fixture
async def engine():
    """A fresh in-memory database per test, with the schema created."""
    eng = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def session(session_factory):
    async with session_factory() as s:
        yield s


@pytest.fixture
def mocks(monkeypatch):
    """Replace the router's external integrations with mocks."""
    apply = AsyncMock()
    apply_index = AsyncMock()
    validate = AsyncMock(return_value={"number": "INC0001", "state": "2", "priority": "2"})
    schedule = MagicMock()
    cancel = MagicMock()

    monkeypatch.setattr("app.routers.grants.apply_active_grants", apply)
    monkeypatch.setattr("app.routers.grants.apply_active_grants_to_index", apply_index)
    monkeypatch.setattr("app.routers.grants.validate_incident", validate)
    monkeypatch.setattr("app.routers.grants.schedule_revert", schedule)
    monkeypatch.setattr("app.routers.grants.cancel_revert", cancel)

    return SimpleNamespace(
        apply=apply,
        apply_index=apply_index,
        validate=validate,
        schedule=schedule,
        cancel=cancel,
    )


@pytest_asyncio.fixture
async def client(session_factory, mocks):
    """An httpx client wired to a minimal app exposing the grants router.

    We build a bare FastAPI app (no lifespan) so the real scheduler / DB
    startup never runs; ``get_db`` is overridden to use the in-memory engine.
    """
    from app.routers.grants import router

    app = FastAPI()
    app.include_router(router)

    async def override_get_db():
        async with session_factory() as s:
            yield s

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def last_call_car_ids(apply_mock) -> list[str]:
    """The car_id list passed to the most recent apply_active_grants call."""
    return list(apply_mock.call_args.args[0])


async def make_grant(
    session_factory,
    car_id: str,
    *,
    status: str = "active",
    inc_number: str = "INC0001",
    expires_in: int = 600,
) -> Grant:
    """Insert a Grant row directly and return it."""
    now = datetime.utcnow()
    grant = Grant(
        car_id=car_id,
        inc_number=inc_number,
        requested_by="tester",
        created_at=now,
        expires_at=now + timedelta(seconds=expires_in),
        status=status,
    )
    async with session_factory() as s:
        s.add(grant)
        await s.commit()
        await s.refresh(grant)
    return grant
