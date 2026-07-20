import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class WatchlistStatus(str, enum.Enum):
    pending = "pending"
    watched = "watched"


class WatchlistEntry(Base):
    __tablename__ = "watchlist_entries"
    __table_args__ = (UniqueConstraint("user_id", "suggestion_id", name="uq_watchlist_user_suggestion"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    suggestion_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("suggestions.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[WatchlistStatus] = mapped_column(
        Enum(WatchlistStatus, name="watchliststatus"),
        nullable=False,
        default=WatchlistStatus.pending,
    )
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    opinion: Mapped[str | None] = mapped_column(Text, nullable=True)
    watched_on: Mapped[str | None] = mapped_column(String(100), nullable=True)
    hidden_from_watchlist: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user: Mapped["User"] = relationship("User", back_populates="watchlist_entries")
    suggestion: Mapped["Suggestion"] = relationship("Suggestion", back_populates="watchlist_entries")
