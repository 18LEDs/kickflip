"""
Datadog Observability Pipelines client.

Each pipeline is expected to have a filter processor whose `include` condition
starts with  `level:debug`  (the drop-debug filter).  When active grants exist
the condition becomes:

    level:debug AND NOT (car_id:1234 OR car_id:5678)

OP pipeline config shape (simplified):

    {
      "data": {
        "id": "<pipeline_id>",
        "type": "observability_pipeline",
        "attributes": {
          "config": {
            "processors": [
              {
                "id": "<processor_id>",
                "type": "filter",
                "include": "level:debug",
                ...
              }
            ]
          }
        }
      }
    }
"""

import logging
from typing import Any

import httpx

from app.config import settings

log = logging.getLogger(__name__)

BASE_DEBUG_FILTER = "level:debug"


def _headers() -> dict[str, str]:
    return {
        "DD-API-KEY": settings.dd_api_key,
        "DD-APPLICATION-KEY": settings.dd_app_key,
        "Content-Type": "application/json",
    }


def _build_filter(active_car_ids: list[str]) -> str:
    if not active_car_ids:
        return BASE_DEBUG_FILTER
    exclusions = " OR ".join(f"car_id:{cid}" for cid in active_car_ids)
    return f"{BASE_DEBUG_FILTER} AND NOT ({exclusions})"


async def _get_pipeline(client: httpx.AsyncClient, pipeline_id: str) -> dict[str, Any]:
    url = f"{settings.dd_base_url}/api/v2/observability_pipelines/{pipeline_id}"
    resp = await client.get(url, headers=_headers())
    resp.raise_for_status()
    return resp.json()


async def _patch_pipeline(
    client: httpx.AsyncClient, pipeline_id: str, payload: dict[str, Any]
) -> None:
    url = f"{settings.dd_base_url}/api/v2/observability_pipelines/{pipeline_id}"
    resp = await client.patch(url, headers=_headers(), json=payload)
    resp.raise_for_status()


def _update_processor_filter(pipeline_data: dict[str, Any], new_filter: str) -> bool:
    """Mutate the pipeline data in-place. Returns True if a processor was found."""
    processors: list[dict] = (
        pipeline_data.get("data", {})
        .get("attributes", {})
        .get("config", {})
        .get("processors", [])
    )
    for proc in processors:
        proc_id: str = proc.get("id", "")
        # Match by configured ID or by detecting the base debug filter
        if proc_id == settings.dd_filter_processor_id or proc.get("include", "").startswith(
            BASE_DEBUG_FILTER
        ):
            proc["include"] = new_filter
            log.debug("Updated processor %s → %s", proc_id, new_filter)
            return True
    return False


async def apply_active_grants(active_car_ids: list[str]) -> None:
    """Push the current active CAR ID set to all configured pipelines."""
    if not settings.pipeline_id_list:
        log.warning("No DD_PIPELINE_IDS configured — skipping OP update")
        return

    new_filter = _build_filter(active_car_ids)
    log.info("Applying filter to %d pipeline(s): %s", len(settings.pipeline_id_list), new_filter)

    async with httpx.AsyncClient(timeout=15) as client:
        for pid in settings.pipeline_id_list:
            try:
                pipeline_data = await _get_pipeline(client, pid)
                found = _update_processor_filter(pipeline_data, new_filter)
                if not found:
                    log.warning("Pipeline %s: debug drop processor not found — skipping", pid)
                    continue
                await _patch_pipeline(client, pid, pipeline_data)
                log.info("Pipeline %s updated OK", pid)
            except httpx.HTTPStatusError as exc:
                log.error("Pipeline %s: HTTP %s — %s", pid, exc.response.status_code, exc.response.text)
            except Exception as exc:
                log.error("Pipeline %s: unexpected error — %s", pid, exc)
