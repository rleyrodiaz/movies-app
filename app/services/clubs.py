from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.club import Club
from app.models.user import User, UserRole


def get_active_club(request: Request, user: User, db: Session) -> Club:
    """Club que el usuario está viendo en este request.

    Para cualquier usuario no-superadmin siempre es su propio club (fijo).
    Para el superadmin es el club activo guardado en la cookie de sesión,
    si todavía existe; si no, cae también a su propio club."""
    if user.role == UserRole.superadmin:
        candidate_id = getattr(request.state, "active_club_id", None)
        if candidate_id is not None:
            club = db.get(Club, candidate_id)
            if club is not None:
                return club
    return db.get(Club, user.club_id)


def list_clubs_for_switcher(user: User, db: Session) -> list[Club] | None:
    """Lista de clubes para el selector del nav. None si el usuario no es superadmin
    (así no se hace ninguna query extra para el resto de los usuarios)."""
    if user.role != UserRole.superadmin:
        return None
    return list(db.scalars(select(Club).order_by(Club.name)).all())
