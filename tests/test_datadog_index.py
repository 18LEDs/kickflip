"""Tests for the Log Index client (app/clients/datadog_index.py)."""

from unittest.mock import AsyncMock

import pytest

from app.clients import datadog_index
from app.clients.datadog_index import (
    BASE_DEBUG_QUERY,
    _build_exclusion_query,
    _update_exclusion_filter,
    apply_active_grants_to_index,
)
from app.config import settings


# --- _build_exclusion_query ------------------------------------------------

def test_build_query_empty_is_base():
    assert _build_exclusion_query([]) == BASE_DEBUG_QUERY


def test_build_query_single():
    assert _build_exclusion_query(["1234"]) == "status:debug AND NOT (car_id:1234)"


def test_build_query_multiple():
    assert _build_exclusion_query(["1234", "5678"]) == (
        "status:debug AND NOT (car_id:1234 OR car_id:5678)"
    )


# --- _update_exclusion_filter ----------------------------------------------

def _index(query):
    return {"exclusion_filters": [{"name": "drop-debug", "filter": {"query": query}}]}


def test_update_exclusion_filter_found():
    data = _index("status:debug")
    found = _update_exclusion_filter(data, "status:debug AND NOT (car_id:1)")
    assert found is True
    assert data["exclusion_filters"][0]["filter"]["query"] == "status:debug AND NOT (car_id:1)"


def test_update_exclusion_filter_not_found():
    data = _index("service:foo")
    assert _update_exclusion_filter(data, "status:debug") is False


def test_update_exclusion_filter_no_filters():
    assert _update_exclusion_filter({}, "status:debug") is False


# --- apply_active_grants_to_index ------------------------------------------

async def test_apply_to_index_puts_updated_query(monkeypatch):
    monkeypatch.setattr(settings, "dd_index_name", "main")
    get_mock = AsyncMock(return_value=_index("status:debug"))
    put_mock = AsyncMock()
    monkeypatch.setattr(datadog_index, "_get_index", get_mock)
    monkeypatch.setattr(datadog_index, "_put_index", put_mock)

    await apply_active_grants_to_index(["1001", "1002"])

    put_mock.assert_awaited_once()
    _client, payload = put_mock.await_args.args
    query = payload["exclusion_filters"][0]["filter"]["query"]
    assert query == "status:debug AND NOT (car_id:1001 OR car_id:1002)"


async def test_apply_to_index_no_index_configured(monkeypatch):
    monkeypatch.setattr(settings, "dd_index_name", "")
    put_mock = AsyncMock()
    monkeypatch.setattr(datadog_index, "_put_index", put_mock)

    await apply_active_grants_to_index(["1001"])

    put_mock.assert_not_awaited()


async def test_apply_to_index_skips_when_filter_missing(monkeypatch):
    monkeypatch.setattr(settings, "dd_index_name", "main")
    get_mock = AsyncMock(return_value=_index("service:foo"))
    put_mock = AsyncMock()
    monkeypatch.setattr(datadog_index, "_get_index", get_mock)
    monkeypatch.setattr(datadog_index, "_put_index", put_mock)

    await apply_active_grants_to_index(["1001"])

    put_mock.assert_not_awaited()
