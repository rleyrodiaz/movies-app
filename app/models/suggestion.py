import enum
import json
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class MediaType(str, enum.Enum):
    movie = "movie"
    tv = "tv"


class Suggestion(Base):
    __tablename__ = "suggestions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tmdb_id: Mapped[int] = mapped_column(Integer, nullable=False)
    media_type: Mapped[MediaType] = mapped_column(
        Enum(MediaType, name="mediatype"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    poster_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    overview: Mapped[str | None] = mapped_column(Text, nullable=True)
    release_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    genres: Mapped[str | None] = mapped_column(Text, nullable=True)
    origin_country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cast_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    providers: Mapped[str | None] = mapped_column(Text, nullable=True)
    episode_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    season_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tmdb_rating: Mapped[float | None] = mapped_column(nullable=True)
    suggested_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    suggester: Mapped["User"] = relationship("User", back_populates="suggestions", foreign_keys=[suggested_by])
    comments: Mapped[list["Comment"]] = relationship("Comment", back_populates="suggestion", cascade="all, delete-orphan")
    watchlist_entries: Mapped[list["WatchlistEntry"]] = relationship("WatchlistEntry", back_populates="suggestion", cascade="all, delete-orphan")

    def _parse(self, field: str | None) -> list[str]:
        if not field:
            return []
        try:
            return json.loads(field)
        except (json.JSONDecodeError, TypeError):
            return []

    @property
    def genres_list(self) -> list[str]:
        return self._parse(self.genres)

    @property
    def cast_list(self) -> list[str]:
        return self._parse(self.cast_summary)

    @property
    def providers_list(self) -> list[str]:
        return self._parse(self.providers)
