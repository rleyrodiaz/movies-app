from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AppVersionCommit(Base):
    """Un registro por cada commit que llegó a correr en producción, para
    poder mostrar un número de versión incremental sin depender de que el
    entorno de deploy tenga el historial completo de git disponible."""

    __tablename__ = "app_version_commits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    commit_sha: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
