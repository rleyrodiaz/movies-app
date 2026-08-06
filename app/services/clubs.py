from sqlalchemy import select
from sqlalchemy.orm import Session

from app.exceptions import AccessDenied
from app.models.club import Club
from app.models.user import User, UserRole


def get_active_club(user: User, db: Session) -> Club:
    """Club en el que el usuario está parado ahora mismo.

    Persiste en user.last_active_club_id (no en la cookie de sesión), así
    sobrevive entre sesiones y dispositivos. El superadmin puede pararse en
    cualquier club (no depende de tener una membresía ahí); cualquier otro
    usuario solo puede estar parado en un club del que sea miembro."""
    if user.is_superadmin:
        if user.last_active_club_id:
            club = db.get(Club, user.last_active_club_id)
            if club is not None:
                return club
        club = db.scalar(select(Club).order_by(Club.name))
        if club is not None:
            user.last_active_club_id = club.id
        return club

    membership_ids = {m.club_id for m in user.memberships}
    if user.last_active_club_id in membership_ids:
        return db.get(Club, user.last_active_club_id)

    first = min(user.memberships, key=lambda m: m.id) if user.memberships else None
    if first is None:
        raise AccessDenied()
    user.last_active_club_id = first.club_id
    return db.get(Club, first.club_id)


def is_active_club_admin(user: User, active_club: Club) -> bool:
    """True si el usuario puede administrar el club activo: superadmin
    (siempre), o admin de ese club puntual."""
    if user.is_superadmin:
        return True
    return any(m.club_id == active_club.id and m.role == UserRole.admin for m in user.memberships)


def list_own_clubs(user: User, db: Session) -> list[Club]:
    """Clubes "propios" del usuario: todos si es superadmin (tiene acceso a
    cualquiera, aunque no tenga una membresía explícita ahí), o los de sus
    membresías reales para cualquier otro usuario."""
    if user.is_superadmin:
        return list(db.scalars(select(Club).order_by(Club.name)).all())
    club_ids = [m.club_id for m in user.memberships]
    return list(db.scalars(select(Club).where(Club.id.in_(club_ids)).order_by(Club.name)).all())


def list_clubs_for_switcher(user: User, db: Session) -> list[Club] | None:
    """Lista de clubes para el selector del nav. None si no hace falta
    mostrarlo (superadmin siempre lo ve; cualquier otro usuario solo si
    pertenece a más de un club)."""
    clubs = list_own_clubs(user, db)
    if not user.is_superadmin and len(clubs) <= 1:
        return None
    return clubs
