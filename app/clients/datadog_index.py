"""
Datadog Log Index client.

Manages the exclusion filter on a single shared index to allow debug logs
for specific CAR IDs to be indexed during an active grant.

Index exclusion filters work as an allowlist-within-a-blocklist: the index
has an exclusion filter with query `status:debug` that drops all debug logs.
When a grant is active we narrow that query so debug logs for the granted
CAR IDs are no longer excluded:

    status:debug AND NOT (car_id:1234 OR car_id:5678)

Index API: GET/PUT /api/v1/logs/config/indexes/{name}
"""

import logging
from typing import Any

import httpx

from app.clients.datadog import _headers
from app.config import settings

log = logging.getLogger(__name__)

BASE_DEBUG_QUERY = "status:debug"


async def _get_index(client: httpx.AsyncClient) -> dict[str, Any]:
    url = f"{settings.dd_base_url}/api/v1/logs/config/indexes/{settings.dd_index_name}"
    resp = await client.get(url, headers=_headers())
    resp.raise_for_status()
    return resp.json()


async def _put_index(client: httpx.AsyncClient, payload: dict[str, Any]) -> None:
    url = f"{settings.dd_base_url}/api/v1/logs/config/indexes/{settings.dd_index_name}"
    resp = await client.put(url, headers=_headers(), json=payload)
    resp.raise_for_status()


def _build_exclusion_query(active_car_ids: list[str]) -> str:
    if not active_car_ids:
        return BASE_DEBUG_QUERY
    exclusions = " OR ".join(f"car_id:{cid}" for cid in active_car_ids)
    return f"{BASE_DEBUG_QUERY} AND NOT ({exclusions})"


def _update_exclusion_filter(index_data: dict[str, Any], new_query: str) -> bool:
    """
    Find the debug exclusion filter and update its query in-place.
    Returns True if the filter was found.
    """
    for excl in index_data.get("exclusion_filters", []):
        query = excl.get("filter", {}).get("query", "")
        if query.startswith(BASE_DEBUG_QUERY):
            excl["filter"]["query"] = new_query
            log.debug("Updated exclusion filter '%s' → %s", excl.get("name"), new_query)
            return True
    return False


async def apply_active_grants_to_index(active_car_ids: list[str]) -> None:
    """Push the current active CAR ID set to the shared log index exclusion filter."""
    if not settings.dd_index_name:
        log.warning("DD_INDEX_NAME not configured — skipping index update (stub mode)")
        return

    new_query = _build_exclusion_query(active_car_ids)
    log.info("Updating index '%s' exclusion filter: %s", settings.dd_index_name, new_query)

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            index_data = await _get_index(client)
            found = _update_exclusion_filter(index_data, new_query)
            if not found:
                log.warning(
                    "Index '%s': no exclusion filter starting with '%s' found — skipping",
                    settings.dd_index_name,
                    BASE_DEBUG_QUERY,
                )
                return
            await _put_index(client, index_data)
            log.info("Index '%s' updated OK", settings.dd_index_name)
        except httpx.HTTPStatusError as exc:
            log.error(
                "Index '%s': HTTP %s — %s",
                settings.dd_index_name,
                exc.response.status_code,
                exc.response.text,
            )
        except Exception as exc:
            log.error("Index '%s': unexpected error — %s", settings.dd_index_name, exc)
