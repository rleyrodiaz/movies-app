from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.suggestion import MediaType


class PersonalReminder(Base):
    """Recordatorio privado: algo que un usuario quiere ver pero todavía no vio.

    No es una Suggestion — no aparece en el Feed ni cuenta para nadie más.
    Al calificarlo se promueve a una Suggestion real; al descartarlo se borra sin dejar rastro.
    """

    __tablename__ = "personal_reminders"
    __table_args__ = (UniqueConstraint("user_id", "tmdb_id", "media_type", name="uq_reminder_user_tmdb"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    tmdb_id: Mapped[int] = mapped_column(Integer, nullable=False)
    media_type: Mapped[MediaType] = mapped_column(
        Enum(MediaType, name="mediatype"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    poster_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    overview: Mapped[str | None] = mapped_column(Text, nullable=True)
    release_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship("User", back_populates="reminders")
