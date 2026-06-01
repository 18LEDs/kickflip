"""Tests for background tasks (app/tasks.py)."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app import tasks
from app.models import Grant
from tests.conftest import last_call_car_ids, make_grant


@pytest.fixture
def task_env(monkeypatch, session_factory):
    """Point tasks at the test DB and stub out the Datadog pushes."""
    apply = AsyncMock()
    apply_index = AsyncMock()
    monkeypatch.setattr(tasks, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(tasks, "apply_active_grants", apply)
    monkeypatch.setattr(tasks, "apply_active_grants_to_index", apply_index)
    return apply, apply_index


async def _status(session_factory, grant_id):
    async with session_factory() as s:
        g = await s.get(Grant, grant_id)
        return g.status


# --- revert_grant ----------------------------------------------------------

async def test_revert_grant_reverts_only_target(task_env, session_factory):
    apply, apply_index = task_env
    g1 = await make_grant(session_factory, "1001")
    g2 = await make_grant(session_factory, "1002")

    await tasks.revert_grant(g1.id, g1.car_id)

    assert await _status(session_factory, g1.id) == "reverted"
    assert await _status(session_factory, g2.id) == "active"
    # remaining active set pushed = just the survivor
    assert last_call_car_ids(apply) == ["1002"]
    assert last_call_car_ids(apply_index) == ["1002"]


async def test_revert_grant_missing_is_noop(task_env, session_factory):
    apply, _ = task_env
    await tasks.revert_grant(999, "9999")
    apply.assert_not_awaited()


async def test_revert_grant_already_reverted_is_noop(task_env, session_factory):
    apply, _ = task_env
    g = await make_grant(session_factory, "1001", status="reverted")
    await tasks.revert_grant(g.id, g.car_id)
    apply.assert_not_awaited()


# --- recover_on_startup ----------------------------------------------------

async def test_recover_expires_only_past_due_grants(task_env, session_factory):
    apply, apply_index = task_env
    # already past its window — should be expired
    stale = await make_grant(session_factory, "1001", expires_in=-60)
    # still within window — should remain active
    fresh = await make_grant(session_factory, "1002", expires_in=600)

    await tasks.recover_on_startup()

    assert await _status(session_factory, stale.id) == "expired"
    assert await _status(session_factory, fresh.id) == "active"
    # the pushed filter reflects only the still-active grant
    assert last_call_car_ids(apply) == ["1002"]
    assert last_call_car_ids(apply_index) == ["1002"]
