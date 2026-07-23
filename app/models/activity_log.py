import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class ActivityAction(str, enum.Enum):
    user_registered = "user_registered"
    user_login = "user_login"
    suggestion_created = "suggestion_created"
    suggestion_deleted = "suggestion_deleted"
    comment_created = "comment_created"
    watchlist_updated = "watchlist_updated"
    watchlist_added = "watchlist_added"
    watchlist_removed = "watchlist_removed"
    watchlist_rated = "watchlist_rated"
    reminder_created = "reminder_created"
    invitation_created = "invitation_created"
    invitation_used = "invitation_used"
    role_changed = "role_changed"
    db_initialized = "db_initialized"
    db_reset = "db_reset"
    club_created = "club_created"
    club_renamed = "club_renamed"
    club_switched = "club_switched"


class ActivityLog(Base):
    __tablename__ = "activity_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    club_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("clubs.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[ActivityAction] = mapped_column(
        Enum(ActivityAction, name="activityaction"), nullable=False
    )
    target_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User | None"] = relationship("User", back_populates="activity_logs")
