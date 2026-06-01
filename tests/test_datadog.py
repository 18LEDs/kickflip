"""Tests for the Observability Pipelines client (app/clients/datadog.py)."""

from unittest.mock import AsyncMock

import pytest

from app.clients import datadog
from app.clients.datadog import (
    BASE_DEBUG_FILTER,
    _build_filter,
    _update_processor_filter,
    apply_active_grants,
)
from app.config import settings


# --- _build_filter ---------------------------------------------------------

def test_build_filter_empty_is_base():
    assert _build_filter([]) == BASE_DEBUG_FILTER


def test_build_filter_single_car():
    assert _build_filter(["1234"]) == "level:debug AND NOT (car_id:1234)"


def test_build_filter_multiple_cars_joined_with_or():
    assert _build_filter(["1234", "5678"]) == (
        "level:debug AND NOT (car_id:1234 OR car_id:5678)"
    )


# --- _update_processor_filter ----------------------------------------------

def _pipeline(processors):
    return {"data": {"attributes": {"config": {"processors": processors}}}}


def test_update_processor_matches_by_configured_id():
    data = _pipeline([{"id": settings.dd_filter_processor_id, "include": "level:debug"}])
    found = _update_processor_filter(data, "level:debug AND NOT (car_id:1)")
    assert found is True
    proc = data["data"]["attributes"]["config"]["processors"][0]
    assert proc["include"] == "level:debug AND NOT (car_id:1)"


def test_update_processor_matches_by_base_filter_prefix():
    # processor id doesn't match, but include starts with the base debug filter
    data = _pipeline([{"id": "some-other-id", "include": "level:debug AND NOT (car_id:9)"}])
    found = _update_processor_filter(data, "level:debug")
    assert found is True
    assert data["data"]["attributes"]["config"]["processors"][0]["include"] == "level:debug"


def test_update_processor_not_found():
    data = _pipeline([{"id": "unrelated", "include": "service:foo"}])
    assert _update_processor_filter(data, "level:debug") is False


def test_update_processor_handles_missing_config():
    assert _update_processor_filter({}, "level:debug") is False


# --- apply_active_grants ----------------------------------------------------

@pytest.fixture
def two_pipelines(monkeypatch):
    monkeypatch.setattr(settings, "dd_pipeline_ids", "pid-A,pid-B")


async def test_apply_active_grants_patches_each_pipeline(monkeypatch, two_pipelines):
    def fresh_pipeline(_client, pid):
        return _pipeline([{"id": settings.dd_filter_processor_id, "include": "level:debug"}])

    get_mock = AsyncMock(side_effect=fresh_pipeline)
    patch_mock = AsyncMock()
    monkeypatch.setattr(datadog, "_get_pipeline", get_mock)
    monkeypatch.setattr(datadog, "_patch_pipeline", patch_mock)

    await apply_active_grants(["1001", "1002"])

    assert patch_mock.await_count == 2
    expected = "level:debug AND NOT (car_id:1001 OR car_id:1002)"
    for call in patch_mock.await_args_list:
        _client, pid, payload = call.args
        proc = payload["data"]["attributes"]["config"]["processors"][0]
        assert proc["include"] == expected


async def test_apply_active_grants_skips_pipeline_without_processor(monkeypatch, two_pipelines):
    get_mock = AsyncMock(return_value=_pipeline([{"id": "x", "include": "service:foo"}]))
    patch_mock = AsyncMock()
    monkeypatch.setattr(datadog, "_get_pipeline", get_mock)
    monkeypatch.setattr(datadog, "_patch_pipeline", patch_mock)

    await apply_active_grants(["1001"])

    # No matching processor → nothing patched
    patch_mock.assert_not_awaited()


async def test_apply_active_grants_no_pipelines_configured(monkeypatch):
    monkeypatch.setattr(settings, "dd_pipeline_ids", "")
    patch_mock = AsyncMock()
    monkeypatch.setattr(datadog, "_patch_pipeline", patch_mock)

    await apply_active_grants(["1001"])

    patch_mock.assert_not_awaited()
