from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Club(Base):
    __tablename__ = "clubs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Borrador editable del mensaje de "Anuncios" — se guarda para que un envío
    # manual uno-por-uno (WA no permite mandar a varios de una) no pierda la
    # edición entre un envío y el siguiente. "Regenerar" lo limpia.
    announcement_draft: Mapped[str | None] = mapped_column(Text, nullable=True)
