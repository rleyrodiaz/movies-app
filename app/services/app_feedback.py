from app.db import SessionLocal
from app.models.app_feedback import AppFeedback


def pending_feedback_count() -> int:
    """Para el numerito en el menú de Admin — abre su propia sesión corta
    porque se llama desde un Jinja global, fuera del ciclo de vida normal
    de la sesión por request."""
    db = SessionLocal()
    try:
        return db.query(AppFeedback).filter(AppFeedback.checked.is_(False)).count()
    finally:
        db.close()
