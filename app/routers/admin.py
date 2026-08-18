import secrets
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote, quote_plus

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.db import Base, engine, get_db_dep
from app.exceptions import AccessDenied
from app.models.activity_log import ActivityAction, ActivityLog
from app.models.club import Club
from app.models.club_membership import ClubMembership
from app.models.invitation import Invitation
from app.models.reminder import PersonalReminder
from app.models.suggestion import Suggestion
from app.models.user import User, UserRole
from app.models.watchlist import WatchlistEntry
from app.services.activity_log import log_activity
from app.services.auth import (
    clear_session,
    get_session_id,
    require_admin,
    require_superadmin,
    require_user,
)
from app.services import tmdb
from app.services.clubs import get_active_club, is_active_club_admin, list_clubs_for_switcher
from app.services.tz import to_local
from app.services.version import APP_VERSION

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="app/templates")
templates.env.filters["local_time"] = to_local
templates.env.globals["platform_choices"] = tmdb.PLATFORM_CHOICES
templates.env.globals["app_version"] = APP_VERSION

# Tablas que se pueden regenerar selectivamente desde Settings — siempre acotado
# al club activo (ver _club_scope_filter). El orden de borrado (hijos antes que
# padres) se define aparte en RESET_DELETE_ORDER.
RESET_TABLES = {
    "suggestions": {
        "label": "Sugerencias",
        "model": Suggestion,
        "desc": "Elimina las sugerencias del club activo. También borra sus entradas de watchlist (calificaciones y comentarios) asociadas.",
    },
    "watchlist": {
        "label": "Watchlist",
        "model": WatchlistEntry,
        "desc": "Elimina las entradas de watchlist, calificaciones y comentarios de los usuarios del club activo.",
    },
    "reminders": {
        "label": "Recordatorios",
        "model": PersonalReminder,
        "desc": "Elimina los recordatorios privados de los usuarios del club activo (los que todavía no se calificaron ni publicaron).",
    },
    "invitations": {
        "label": "Invitaciones",
        "model": Invitation,
        "desc": "Elimina las invitaciones del club activo, usadas y pendientes.",
    },
    "activity_log": {
        "label": "Activity log",
        "model": ActivityLog,
        "desc": "Borra el historial de actividad del club activo.",
    },
}
RESET_DELETE_ORDER = ["watchlist", "reminders", "suggestions", "invitations", "activity_log"]


def _club_scope_filter(key: str, club_id: int):
    """Condición WHERE para acotar la tabla `key` al club dado — reusada tanto
    para las stats de Settings como para el borrado selectivo."""
    if key == "suggestions":
        return Suggestion.club_id == club_id
    if key == "invitations":
        return Invitation.club_id == club_id
    if key == "activity_log":
        return ActivityLog.club_id == club_id
    if key == "watchlist":
        return WatchlistEntry.suggestion_id.in_(select(Suggestion.id).where(Suggestion.club_id == club_id))
    if key == "reminders":
        return PersonalReminder.user_id.in_(
            select(ClubMembership.user_id).where(ClubMembership.club_id == club_id)
        )
    raise ValueError(f"unknown reset table key: {key}")


@router.get("/invitations", response_class=HTMLResponse)
def invitations_page(
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db_dep),
):
    active_club = get_active_club(current_user, db)

    invitations = db.scalars(
        select(Invitation)
        .where(Invitation.club_id == active_club.id)
        .order_by(Invitation.created_at.desc())
    ).all()

    base_url = str(request.base_url).rstrip("/")
    now = datetime.now(timezone.utc)

    invite_data = []
    for inv in invitations:
        expires_at = inv.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        is_used = inv.used_by is not None
        is_expired = expires_at < now
        link = f"{base_url}/register/{inv.token}"
        msg = (
            f"Te invito a mi club privado de pelis y series en movieLeyro: *{active_club.name}*.\n\n"
            "Armé la app para sugerirnos títulos entre nosotros, sin el eterno \"¿qué vemos hoy?\".\n\n"
            f"Esta invitación es de un solo uso, para registrarte entrá al siguiente link: {link}\n\n"
            "Una vez que entrás al club, en el menú vas a encontrar la opción \"Guía\" — ahí te "
            "explico cómo funciona todo, y al final tenés las instrucciones para instalarla en "
            "tu celular o computadora."
        )
        invite_data.append({
            "inv": inv,
            "link": link,
            "msg": msg,
            "is_used": is_used,
            "is_expired": is_expired,
            "is_active": not is_used and not is_expired,
            "wa_url": f"https://wa.me/?text={quote_plus(msg)}",
            "mailto_url": (
                f"mailto:?subject={quote('Invitación a movieLeyro')}"
                f"&body={quote(msg)}"
            ),
        })

    return templates.TemplateResponse(
        "admin_invitations.html",
        {
            "request": request,
            "user": current_user,
            "invite_data": invite_data,
            "expiry_days": get_settings().invitation_expiry_days,
            "active_club": active_club,
            "is_club_admin": is_active_club_admin(current_user, active_club),
            "all_clubs": list_clubs_for_switcher(current_user, db),
        },
    )


@router.post("/invitations")
def create_invitation(
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db_dep),
):
    settings = get_settings()
    active_club = get_active_club(current_user, db)
    invitation = Invitation(
        token=secrets.token_urlsafe(32),
        created_by=current_user.id,
        club_id=active_club.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.invitation_expiry_days),
    )
    db.add(invitation)
    db.flush()
    log_activity(
        db, ActivityAction.invitation_created,
        user_id=current_user.id,
        club_id=active_club.id,
        target_type="invitation",
        target_id=invitation.id,
        session_id=get_session_id(request),
    )
    return RedirectResponse("/admin/invitations", status_code=303)


ACTION_LABELS = {
    "user_registered": "Nuevo usuario",
    "user_login": "Login",
    "suggestion_created": "Nueva Sugerencia",
    "suggestion_deleted": "Borrar Sugerencia",
    "comment_created": "Comentario creado",
    "watchlist_updated": "Watchlist actualizada",
    "watchlist_added": "Agregar Watchlist",
    "watchlist_removed": "Quitar de Watchlist",
    "watchlist_rated": "Vista + Calificar",
    "reminder_created": "Agregar Recordatorio",
    "invitation_created": "Invitación creada",
    "invitation_used": "Invitación usada",
    "role_changed": "Rol cambiado",
    "db_initialized": "DB inicializada",
    "db_reset": "DB reseteada",
}


ACTIVITY_LOG_PAGE_SIZE = 50


@router.get("/activity-log", response_class=HTMLResponse)
def activity_log_page(
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db_dep),
    action: str = Query(default=""),
    target_type: str = Query(default=""),
    session_id: str = Query(default=""),
    user_id: str = Query(default=""),
    date_from: str = Query(default=""),
    date_to: str = Query(default=""),
    page: int = Query(default=1),
):
    active_club = get_active_club(current_user, db)

    all_entries = db.scalars(
        select(ActivityLog)
        .options(joinedload(ActivityLog.user))
        .where(ActivityLog.club_id == active_club.id)
        .order_by(ActivityLog.created_at.desc())
    ).unique().all()

    all_target_types = sorted({e.target_type for e in all_entries if e.target_type})
    all_users: dict[int, User] = {}
    for e in all_entries:
        if e.user and e.user_id not in all_users:
            all_users[e.user_id] = e.user

    f_action = action.strip()
    f_target_type = target_type.strip()
    f_session_id = session_id.strip()
    try:
        f_user_id = int(user_id)
    except (ValueError, TypeError):
        f_user_id = 0
    if f_user_id not in all_users:
        f_user_id = 0
    f_date_from = date_from.strip()
    f_date_to = date_to.strip()

    entries = list(all_entries)
    if f_action:
        entries = [e for e in entries if e.action.value == f_action]
    if f_target_type:
        entries = [e for e in entries if e.target_type == f_target_type]
    if f_session_id:
        entries = [e for e in entries if e.session_id == f_session_id]
    if f_user_id:
        entries = [e for e in entries if e.user_id == f_user_id]
    if f_date_from:
        try:
            d_from = date.fromisoformat(f_date_from)
            entries = [e for e in entries if to_local(e.created_at).date() >= d_from]
        except ValueError:
            f_date_from = ""
    if f_date_to:
        try:
            d_to = date.fromisoformat(f_date_to)
            entries = [e for e in entries if to_local(e.created_at).date() <= d_to]
        except ValueError:
            f_date_to = ""

    total = len(entries)
    all_total = len(all_entries)
    total_pages = max((total + ACTIVITY_LOG_PAGE_SIZE - 1) // ACTIVITY_LOG_PAGE_SIZE, 1)
    page = min(max(page, 1), total_pages)
    page_entries = entries[(page - 1) * ACTIVITY_LOG_PAGE_SIZE: page * ACTIVITY_LOG_PAGE_SIZE]

    active_filters = sum([
        bool(f_action), bool(f_target_type), bool(f_session_id), bool(f_user_id), bool(f_date_from), bool(f_date_to),
    ])

    return templates.TemplateResponse(
        "admin_activity_log.html",
        {
            "request": request,
            "user": current_user,
            "entries": page_entries,
            "action_labels": ACTION_LABELS,
            "all_actions": list(ActivityAction),
            "all_target_types": all_target_types,
            "all_users": sorted(all_users.values(), key=lambda u: u.display_name.lower()),
            "f_action": f_action,
            "f_target_type": f_target_type,
            "f_session_id": f_session_id,
            "f_user_id": f_user_id,
            "f_date_from": f_date_from,
            "f_date_to": f_date_to,
            "page": page,
            "total_pages": total_pages,
            "total": total,
            "all_total": all_total,
            "active_filters": active_filters,
            "active_club": active_club,
            "is_club_admin": is_active_club_admin(current_user, active_club),
            "all_clubs": list_clubs_for_switcher(current_user, db),
        },
    )


@router.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request,
    current_user: User = Depends(require_superadmin),
    db: Session = Depends(get_db_dep),
    msg: str = "",
):
    active_club = get_active_club(current_user, db)
    stats = {
        key: db.scalar(select(func.count()).select_from(cfg["model"]).where(_club_scope_filter(key, active_club.id)))
        for key, cfg in RESET_TABLES.items()
    }
    stats["users"] = db.scalar(select(func.count()).select_from(User))
    return templates.TemplateResponse(
        "admin_settings.html",
        {
            "request": request,
            "user": current_user,
            "msg": msg,
            "reset_tables": RESET_TABLES,
            "stats": stats,
            "active_club": active_club,
            "is_club_admin": is_active_club_admin(current_user, active_club),
            "all_clubs": list_clubs_for_switcher(current_user, db),
        },
    )


@router.post("/settings/init")
def settings_init(
    request: Request,
    current_user: User = Depends(require_superadmin),
    db: Session = Depends(get_db_dep),
):
    Base.metadata.create_all(bind=engine)
    log_activity(db, ActivityAction.db_initialized, user_id=current_user.id, session_id=get_session_id(request))
    return RedirectResponse("/admin/settings?msg=init_ok", status_code=303)


@router.post("/settings/reset-tables")
def settings_reset_tables(
    request: Request,
    current_user: User = Depends(require_superadmin),
    db: Session = Depends(get_db_dep),
    confirm: str = Form(""),
    tables: list[str] = Form(default=[]),
):
    active_club = get_active_club(current_user, db)
    if confirm.strip() != active_club.name.upper():
        return RedirectResponse("/admin/settings?msg=confirm_error", status_code=303)

    selected = [key for key in RESET_DELETE_ORDER if key in tables and key in RESET_TABLES]
    if not selected:
        return RedirectResponse("/admin/settings?msg=no_selection", status_code=303)

    for key in selected:
        db.execute(delete(RESET_TABLES[key]["model"]).where(_club_scope_filter(key, active_club.id)))

    log_activity(
        db, ActivityAction.db_reset,
        user_id=current_user.id,
        club_id=active_club.id,
        detail={"tables": selected, "club": active_club.name},
        session_id=get_session_id(request),
    )
    return RedirectResponse("/admin/settings?msg=reset_tables_ok", status_code=303)


@router.post("/settings/reset")
def settings_reset(
    request: Request,
    current_user: User = Depends(require_superadmin),
    db: Session = Depends(get_db_dep),
    confirm: str = Form(""),
):
    if confirm.strip() != "RESET":
        return RedirectResponse("/admin/settings?msg=confirm_error", status_code=303)

    saved_email = current_user.email
    saved_hash = current_user.password_hash
    saved_name = current_user.display_name
    saved_club = get_active_club(current_user, db)
    saved_club_name = saved_club.name if saved_club else "Club Original"
    session_id = get_session_id(request)

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    with engine.begin() as conn:
        club_result = conn.execute(
            text("INSERT INTO clubs (name, created_at) VALUES (:name, NOW()) RETURNING id"),
            {"name": saved_club_name},
        )
        new_club_id = club_result.scalar()
        result = conn.execute(
            text(
                "INSERT INTO users (email, password_hash, display_name, is_superadmin, last_active_club_id, created_at) "
                "VALUES (:email, :pw_hash, :name, true, :club_id, NOW()) RETURNING id"
            ),
            {"email": saved_email, "pw_hash": saved_hash, "name": saved_name, "club_id": new_club_id},
        )
        new_user_id = result.scalar()
        conn.execute(
            text(
                "INSERT INTO club_memberships (user_id, club_id, role, created_at) "
                "VALUES (:uid, :club_id, 'admin', NOW())"
            ),
            {"uid": new_user_id, "club_id": new_club_id},
        )
        conn.execute(
            text(
                "INSERT INTO activity_log (user_id, action, session_id, created_at) "
                "VALUES (:uid, 'db_reset', :sid, NOW())"
            ),
            {"uid": new_user_id, "sid": session_id},
        )

    response = RedirectResponse("/login", status_code=303)
    clear_session(response)
    return response


@router.get("/clubs", response_class=HTMLResponse)
def clubs_page(
    request: Request,
    current_user: User = Depends(require_superadmin),
    db: Session = Depends(get_db_dep),
):
    active_club = get_active_club(current_user, db)
    rows = db.execute(
        select(Club, func.count(ClubMembership.id))
        .outerjoin(ClubMembership, ClubMembership.club_id == Club.id)
        .group_by(Club.id)
        .order_by(Club.name)
    ).all()

    all_memberships = db.scalars(
        select(ClubMembership).options(joinedload(ClubMembership.user)).join(User).order_by(User.display_name)
    ).all()
    members_by_club: dict[int, list[ClubMembership]] = {}
    for membership in all_memberships:
        members_by_club.setdefault(membership.club_id, []).append(membership)

    clubs_data = [
        {"club": club, "member_count": count, "members": members_by_club.get(club.id, [])}
        for club, count in rows
    ]

    return templates.TemplateResponse(
        "admin_clubs.html",
        {
            "request": request,
            "user": current_user,
            "clubs_data": clubs_data,
            "active_club": active_club,
            "is_club_admin": is_active_club_admin(current_user, active_club),
            "all_clubs": list_clubs_for_switcher(current_user, db),
        },
    )


@router.post("/clubs")
def create_club(
    request: Request,
    current_user: User = Depends(require_superadmin),
    db: Session = Depends(get_db_dep),
    name: str = Form(...),
):
    clean_name = name.strip()
    if not clean_name:
        return RedirectResponse("/admin/clubs", status_code=303)

    club = Club(name=clean_name)
    db.add(club)
    db.flush()
    log_activity(
        db, ActivityAction.club_created,
        user_id=current_user.id,
        club_id=club.id,
        target_type="club",
        target_id=club.id,
        detail={"name": club.name},
        session_id=get_session_id(request),
    )

    # El superadmin que crea el club queda como miembro real (admin) — así
    # el club funciona como "propio" (recordatorios, etc.), no solo administrado.
    db.add(ClubMembership(user_id=current_user.id, club_id=club.id, role=UserRole.admin))

    current_user.last_active_club_id = club.id
    return RedirectResponse("/admin/clubs", status_code=303)


@router.post("/clubs/{club_id}/rename")
def rename_club(
    request: Request,
    club_id: int,
    current_user: User = Depends(require_superadmin),
    db: Session = Depends(get_db_dep),
    name: str = Form(...),
):
    club = db.get(Club, club_id)
    clean_name = name.strip()
    if club is None or not clean_name:
        return RedirectResponse("/admin/clubs", status_code=303)

    old_name = club.name
    club.name = clean_name
    log_activity(
        db, ActivityAction.club_renamed,
        user_id=current_user.id,
        club_id=club.id,
        target_type="club",
        target_id=club.id,
        detail={"old_name": old_name, "new_name": club.name},
        session_id=get_session_id(request),
    )
    return RedirectResponse("/admin/clubs", status_code=303)


@router.post("/clubs/switch")
def switch_club(
    request: Request,
    current_user: User = Depends(require_user),
    db: Session = Depends(get_db_dep),
    club_id: int = Form(...),
):
    club = db.get(Club, club_id)
    if club is None:
        return RedirectResponse("/feed", status_code=303)

    if not current_user.is_superadmin:
        is_member = any(m.club_id == club_id for m in current_user.memberships)
        if not is_member:
            raise AccessDenied()

    log_activity(
        db, ActivityAction.club_switched,
        user_id=current_user.id,
        club_id=club.id,
        target_type="club",
        target_id=club.id,
        detail={"name": club.name},
        session_id=get_session_id(request),
    )

    current_user.last_active_club_id = club.id
    redirect_to = request.headers.get("referer") or "/feed"
    return RedirectResponse(redirect_to, status_code=303)


@router.post("/clubs/{club_id}/members/{user_id}/role")
def toggle_member_role(
    request: Request,
    club_id: int,
    user_id: int,
    current_user: User = Depends(require_superadmin),
    db: Session = Depends(get_db_dep),
):
    membership = db.scalar(
        select(ClubMembership).where(
            ClubMembership.club_id == club_id, ClubMembership.user_id == user_id
        )
    )
    member = db.get(User, user_id)
    if membership is None or member is None or member.is_superadmin:
        return RedirectResponse("/admin/clubs", status_code=303)

    old_role = membership.role
    membership.role = UserRole.user if membership.role == UserRole.admin else UserRole.admin

    log_activity(
        db, ActivityAction.role_changed,
        user_id=current_user.id,
        club_id=club_id,
        target_type="user",
        target_id=member.id,
        detail={"member": member.display_name, "old_role": old_role.value, "new_role": membership.role.value},
        session_id=get_session_id(request),
    )
    return RedirectResponse("/admin/clubs", status_code=303)
