from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Invitation(Base):
    __tablename__ = "invitations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    club_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("clubs.id", ondelete="CASCADE"), nullable=False
    )
    used_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    creator: Mapped["User"] = relationship("User", back_populates="created_invitations", foreign_keys=[created_by])
    used_by_user: Mapped["User | None"] = relationship("User", foreign_keys=[used_by])
