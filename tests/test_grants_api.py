"""Tests for the grants REST API (app/routers/grants.py)."""

import pytest

from tests.conftest import last_call_car_ids


async def _create(client, car_id, inc="INC0001"):
    resp = await client.post(
        "/api/grants",
        json={"car_id": car_id, "inc_number": inc, "requested_by": "tester"},
    )
    return resp


# --- create ----------------------------------------------------------------

async def test_create_grant_returns_active_grant(client, mocks):
    resp = await _create(client, "1001")
    assert resp.status_code == 201
    body = resp.json()
    assert body["car_id"] == "1001"
    assert body["status"] == "active"
    assert body["seconds_remaining"] > 0
    # filter pushed to both pipeline and index with the new car_id
    assert last_call_car_ids(mocks.apply) == ["1001"]
    mocks.apply_index.assert_awaited()
    mocks.schedule.assert_called_once()


async def test_create_grant_validates_incident_prefix(client):
    resp = await _create(client, "1001", inc="CHG123")
    assert resp.status_code == 422


async def test_create_grant_rejects_empty_car_id(client):
    resp = await _create(client, "   ")
    assert resp.status_code == 422


async def test_duplicate_active_car_id_conflicts(client, mocks):
    assert (await _create(client, "1001")).status_code == 201
    dup = await _create(client, "1001")
    assert dup.status_code == 409
    assert "already exists" in dup.json()["detail"]


async def test_failed_incident_validation_blocks_grant(client, mocks):
    from app.clients.servicenow import IncidentValidationError

    mocks.validate.side_effect = IncidentValidationError("Incident INC0001 not found")
    resp = await _create(client, "1001")
    assert resp.status_code == 422
    # nothing pushed when validation fails
    mocks.apply.assert_not_awaited()


# --- list ------------------------------------------------------------------

async def test_list_grants(client):
    await _create(client, "1001")
    await _create(client, "1002")
    resp = await client.get("/api/grants")
    assert resp.status_code == 200
    car_ids = {g["car_id"] for g in resp.json()}
    assert car_ids == {"1001", "1002"}


# --- revoke ----------------------------------------------------------------

async def test_revoke_marks_reverted_and_cancels_job(client, mocks):
    created = (await _create(client, "1001")).json()
    resp = await client.delete(f"/api/grants/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "reverted"
    assert resp.json()["reverted_at"] is not None
    mocks.cancel.assert_called_once_with(created["id"])
    # after revoking the only grant, the filter is cleared
    assert last_call_car_ids(mocks.apply) == []


async def test_revoke_missing_grant_404(client):
    resp = await client.delete("/api/grants/999")
    assert resp.status_code == 404


async def test_revoke_already_reverted_409(client, mocks):
    created = (await _create(client, "1001")).json()
    await client.delete(f"/api/grants/{created['id']}")
    again = await client.delete(f"/api/grants/{created['id']}")
    assert again.status_code == 409
    assert "already" in again.json()["detail"]


# --- the headline scenario: revoke 3 of 5 ----------------------------------

async def test_revoking_three_of_five_leaves_only_the_other_two(client, mocks):
    """5 active grants, manually revoke 3 → only those 3 car_ids leave the
    filter; the remaining 2 stay protected."""
    ids = {}
    for car in ["1001", "1002", "1003", "1004", "1005"]:
        ids[car] = (await _create(client, car)).json()["id"]

    # All five are present in the most recent filter push.
    assert set(last_call_car_ids(mocks.apply)) == {"1001", "1002", "1003", "1004", "1005"}

    # Manually revoke three specific grants.
    for car in ["1002", "1003", "1004"]:
        resp = await client.delete(f"/api/grants/{ids[car]}")
        assert resp.status_code == 200

    # The final filter pushed to Datadog contains exactly the two survivors.
    assert set(last_call_car_ids(mocks.apply)) == {"1001", "1005"}
    assert set(last_call_car_ids(mocks.apply_index)) == {"1001", "1005"}

    # Only the three revoked grants' scheduler jobs were cancelled.
    cancelled = {c.args[0] for c in mocks.cancel.call_args_list}
    assert cancelled == {ids["1002"], ids["1003"], ids["1004"]}

    # And the API still reports exactly the two as active.
    listed = (await client.get("/api/grants")).json()
    active = {g["car_id"] for g in listed if g["status"] == "active"}
    assert active == {"1001", "1005"}
