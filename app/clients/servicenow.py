"""
ServiceNow incident validation client.

Checks that an incident:
  - exists
  - is active (not resolved/closed)
  - is at or above the configured minimum severity (SEV2 = priority <= 2)

SN priority field values:
    1 = Critical / SEV1
    2 = High     / SEV2
    3 = Moderate / SEV3
    4 = Low      / SEV4
    5 = Planning / SEV5

SN state field values (string):
    1 = New, 2 = In Progress, 3 = On Hold, 6 = Resolved, 7 = Closed, 8 = Cancelled
"""

import logging

import httpx

from app.config import settings

log = logging.getLogger(__name__)

_INACTIVE_STATES = {"6", "7", "8"}  # resolved, closed, cancelled


class IncidentValidationError(Exception):
    """Raised when an incident fails validation with a user-facing message."""


async def validate_incident(inc_number: str) -> dict:
    """
    Return the incident record if it passes validation.
    Raises IncidentValidationError with a descriptive message otherwise.
    """
    if not all([settings.sn_instance, settings.sn_user, settings.sn_pass]):
        log.warning("ServiceNow not configured — skipping incident validation (stub mode)")
        return _stub_incident(inc_number)

    url = (
        f"https://{settings.sn_instance}/api/now/table/incident"
        f"?sysparm_query=number={inc_number}"
        f"&sysparm_fields=number,state,priority,short_description,assigned_to"
        f"&sysparm_limit=1"
    )

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(
                url,
                auth=(settings.sn_user, settings.sn_pass),
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise IncidentValidationError(
                f"ServiceNow returned HTTP {exc.response.status_code} — check credentials"
            ) from exc

    results = resp.json().get("result", [])
    if not results:
        raise IncidentValidationError(f"Incident {inc_number} not found in ServiceNow")

    inc = results[0]
    state = str(inc.get("state", ""))
    priority = int(inc.get("priority", 99))

    if state in _INACTIVE_STATES:
        raise IncidentValidationError(
            f"Incident {inc_number} is not active (state={state})"
        )

    if priority > settings.sn_min_severity:
        raise IncidentValidationError(
            f"Incident {inc_number} priority {priority} does not meet the required "
            f"minimum SEV{settings.sn_min_severity} (priority ≤ {settings.sn_min_severity})"
        )

    return inc


def _stub_incident(inc_number: str) -> dict:
    """Permissive stub used when SN is not configured (dev/test)."""
    log.info("SN stub: accepting %s without validation", inc_number)
    return {
        "number": inc_number,
        "state": "2",
        "priority": "2",
        "short_description": "[stub] ServiceNow not configured",
    }
