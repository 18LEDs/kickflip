from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Grant(Base):
    __tablename__ = "grants"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    car_id: Mapped[str] = mapped_column(String(64), index=True)
    inc_number: Mapped[str] = mapped_column(String(32))
    requested_by: Mapped[str] = mapped_column(String(128), default="anonymous")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    reverted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # active | reverted | expired
    status: Mapped[str] = mapped_column(String(16), default="active")
