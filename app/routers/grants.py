from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.datadog import apply_active_grants
from app.clients.servicenow import IncidentValidationError, validate_incident
from app.config import settings
from app.database import get_db
from app.models import Grant
from app.scheduler import cancel_revert, schedule_revert

router = APIRouter(prefix="/api/grants", tags=["grants"])


class GrantRequest(BaseModel):
    car_id: str
    inc_number: str
    requested_by: str = "anonymous"

    @field_validator("car_id")
    @classmethod
    def car_id_nonempty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("CAR ID must not be empty")
        return v

    @field_validator("inc_number")
    @classmethod
    def inc_format(cls, v: str) -> str:
        v = v.strip().upper()
        if not v.startswith("INC"):
            raise ValueError("Incident number must start with INC")
        return v


class GrantResponse(BaseModel):
    id: int
    car_id: str
    inc_number: str
    requested_by: str
    created_at: datetime
    expires_at: datetime
    reverted_at: Optional[datetime]
    status: str
    seconds_remaining: Optional[int] = None

    model_config = {"from_attributes": True}


def _enrich(grant: Grant) -> GrantResponse:
    resp = GrantResponse.model_validate(grant)
    if grant.status == "active":
        delta = grant.expires_at - datetime.utcnow()
        resp.seconds_remaining = max(0, int(delta.total_seconds()))
    return resp


@router.get("", response_model=List[GrantResponse])
async def list_grants(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Grant).order_by(Grant.created_at.desc()).limit(50)
    )
    return [_enrich(g) for g in result.scalars().all()]


@router.post("", response_model=GrantResponse, status_code=201)
async def create_grant(body: GrantRequest, db: AsyncSession = Depends(get_db)):
    # Validate incident
    try:
        await validate_incident(body.inc_number)
    except IncidentValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # Check for an existing active grant for this CAR ID
    existing = await db.execute(
        select(Grant).where(Grant.car_id == body.car_id, Grant.status == "active")
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail=f"An active debug grant already exists for CAR ID {body.car_id}",
        )

    now = datetime.utcnow()
    expires = now + timedelta(seconds=settings.grant_duration_seconds)

    grant = Grant(
        car_id=body.car_id,
        inc_number=body.inc_number,
        requested_by=body.requested_by,
        created_at=now,
        expires_at=expires,
        status="active",
    )
    db.add(grant)
    await db.commit()
    await db.refresh(grant)

    # Collect all active CAR IDs (including the new one) and push to pipelines
    result = await db.execute(select(Grant.car_id).where(Grant.status == "active"))
    active_ids = [row[0] for row in result.all()]
    await apply_active_grants(active_ids)

    schedule_revert(grant.id, grant.car_id, expires)
    return _enrich(grant)


@router.delete("/{grant_id}", response_model=GrantResponse)
async def revoke_grant(grant_id: int, db: AsyncSession = Depends(get_db)):
    grant = await db.get(Grant, grant_id)
    if not grant:
        raise HTTPException(status_code=404, detail="Grant not found")
    if grant.status != "active":
        raise HTTPException(status_code=409, detail=f"Grant is already {grant.status}")

    grant.status = "reverted"
    grant.reverted_at = datetime.utcnow()
    await db.commit()

    cancel_revert(grant_id)

    result = await db.execute(select(Grant.car_id).where(Grant.status == "active"))
    active_ids = [row[0] for row in result.all()]
    await apply_active_grants(active_ids)

    return _enrich(grant)
