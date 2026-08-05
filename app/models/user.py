import enum
import json
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class UserRole(str, enum.Enum):
    user = "user"
    admin = "admin"
    superadmin = "superadmin"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_superadmin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    last_active_club_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("clubs.id", ondelete="SET NULL"), nullable=True
    )
    invited_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    platforms: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    inviter: Mapped["User | None"] = relationship("User", remote_side="User.id", foreign_keys=[invited_by])
    suggestions: Mapped[list["Suggestion"]] = relationship("Suggestion", back_populates="suggester", foreign_keys="Suggestion.suggested_by")
    watchlist_entries: Mapped[list["WatchlistEntry"]] = relationship("WatchlistEntry", back_populates="user")
    reminders: Mapped[list["PersonalReminder"]] = relationship("PersonalReminder", back_populates="user", cascade="all, delete-orphan")
    activity_logs: Mapped[list["ActivityLog"]] = relationship("ActivityLog", back_populates="user")
    created_invitations: Mapped[list["Invitation"]] = relationship("Invitation", back_populates="creator", foreign_keys="Invitation.created_by")
    memberships: Mapped[list["ClubMembership"]] = relationship("ClubMembership", back_populates="user", cascade="all, delete-orphan")

    @property
    def platforms_list(self) -> list[str]:
        if not self.platforms:
            return []
        try:
            return json.loads(self.platforms)
        except (json.JSONDecodeError, TypeError):
            return []
