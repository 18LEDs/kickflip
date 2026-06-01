"""Tests for the ServiceNow incident validator (app/clients/servicenow.py)."""

import httpx
import pytest

from app.clients import servicenow
from app.clients.servicenow import IncidentValidationError, validate_incident
from app.config import settings


@pytest.fixture
def sn_configured(monkeypatch):
    monkeypatch.setattr(settings, "sn_instance", "acme.service-now.com")
    monkeypatch.setattr(settings, "sn_user", "svc")
    monkeypatch.setattr(settings, "sn_pass", "secret")
    monkeypatch.setattr(settings, "sn_min_severity", 2)


_RealAsyncClient = httpx.AsyncClient


def _install_response(monkeypatch, *, json=None, status_code=200):
    """Route servicenow's httpx calls through a MockTransport."""

    def handler(request):
        return httpx.Response(status_code, json=json if json is not None else {})

    def factory(*args, **kwargs):
        return _RealAsyncClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(servicenow.httpx, "AsyncClient", factory)


# --- stub mode (unconfigured) ----------------------------------------------

async def test_stub_mode_accepts_anything(monkeypatch):
    monkeypatch.setattr(settings, "sn_instance", "")
    inc = await validate_incident("INC9999")
    assert inc["number"] == "INC9999"
    assert "stub" in inc["short_description"].lower()


# --- configured: happy path ------------------------------------------------

async def test_valid_active_high_priority_incident(monkeypatch, sn_configured):
    _install_response(
        monkeypatch,
        json={"result": [{"number": "INC0001", "state": "2", "priority": "1"}]},
    )
    inc = await validate_incident("INC0001")
    assert inc["number"] == "INC0001"


# --- configured: failure paths ---------------------------------------------

async def test_incident_not_found(monkeypatch, sn_configured):
    _install_response(monkeypatch, json={"result": []})
    with pytest.raises(IncidentValidationError, match="not found"):
        await validate_incident("INC0002")


async def test_inactive_incident_rejected(monkeypatch, sn_configured):
    _install_response(
        monkeypatch,
        json={"result": [{"number": "INC0003", "state": "6", "priority": "1"}]},
    )
    with pytest.raises(IncidentValidationError, match="not active"):
        await validate_incident("INC0003")


async def test_low_priority_rejected(monkeypatch, sn_configured):
    _install_response(
        monkeypatch,
        json={"result": [{"number": "INC0004", "state": "2", "priority": "3"}]},
    )
    with pytest.raises(IncidentValidationError, match="minimum"):
        await validate_incident("INC0004")


async def test_http_error_surfaces_validation_error(monkeypatch, sn_configured):
    _install_response(monkeypatch, status_code=401, json={})
    with pytest.raises(IncidentValidationError, match="HTTP 401"):
        await validate_incident("INC0005")
