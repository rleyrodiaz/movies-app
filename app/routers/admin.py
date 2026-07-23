import secrets
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.db import Base, engine, get_db_dep
from app.models.activity_log import ActivityAction, ActivityLog
from app.models.club import Club
from app.models.invitation import Invitation
from app.models.reminder import PersonalReminder
from app.models.suggestion import Suggestion
from app.models.user import User, UserRole
from app.models.watchlist import WatchlistEntry
from app.services.activity_log import log_activity
from app.services.auth import (
    clear_session,
    create_session_cookie,
    get_session_id,
    require_admin,
    require_superadmin,
)
from app.services.clubs import get_active_club, list_clubs_for_switcher
from app.services.tz import to_local

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="app/templates")
templates.env.filters["local_time"] = to_local

# Tablas que se pueden regenerar selectivamente desde Settings.
# El orden de borrado (hijos antes que padres) se define aparte en RESET_DELETE_ORDER.
RESET_TABLES = {
    "suggestions": {
        "label": "Sugerencias",
        "model": Suggestion,
        "desc": "Elimina todas las sugerencias. También borra sus entradas de watchlist (calificaciones y comentarios) asociadas.",
    },
    "watchlist": {
        "label": "Watchlist",
        "model": WatchlistEntry,
        "desc": "Elimina las entradas de watchlist, calificaciones y comentarios de todos los usuarios.",
    },
    "reminders": {
        "label": "Recordatorios",
        "model": PersonalReminder,
        "desc": "Elimina los recordatorios privados de todos los usuarios (los que todavía no se calificaron ni publicaron).",
    },
    "invitations": {
        "label": "Invitaciones",
        "model": Invitation,
        "desc": "Elimina todas las invitaciones, usadas y pendientes.",
    },
    "activity_log": {
        "label": "Activity log",
        "model": ActivityLog,
        "desc": "Borra el historial completo de actividad.",
    },
}
RESET_DELETE_ORDER = ["watchlist", "reminders", "suggestions", "invitations", "activity_log"]


@router.get("/invitations", response_class=HTMLResponse)
def invitations_page(
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db_dep),
):
    active_club = get_active_club(request, current_user, db)

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
            "Armé movieLeyro: una app privada, de grupo cerrado, para sugerirnos pelis y series "
            "entre nosotros, sin el eterno \"¿qué vemos hoy?\". Cargás tus sugerencias eligiendo "
            "de toda la base de TMDB con filtros (título, género, calificación, director, actor). "
            "Después, con esos mismos filtros, vas pasando lo que te interesa a Mi Watchlist, y "
            "cuando la ves, la calificás y dejás tu comentario — así el rating no es de un "
            "desconocido de internet sino de gente en la que confiás. Te dejo tu acceso, es de un "
            f"solo uso 👇\n{link}"
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
                f"mailto:?subject={quote_plus('Invitación a movieLeyro')}"
                f"&body={quote_plus(msg)}"
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
    active_club = get_active_club(request, current_user, db)
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
    date_from: str = Query(default=""),
    date_to: str = Query(default=""),
    page: int = Query(default=1),
):
    active_club = get_active_club(request, current_user, db)

    all_entries = db.scalars(
        select(ActivityLog)
        .options(joinedload(ActivityLog.user))
        .where(ActivityLog.club_id == active_club.id)
        .order_by(ActivityLog.created_at.desc())
    ).unique().all()

    all_target_types = sorted({e.target_type for e in all_entries if e.target_type})

    f_action = action.strip()
    f_target_type = target_type.strip()
    f_session_id = session_id.strip()
    f_date_from = date_from.strip()
    f_date_to = date_to.strip()

    entries = list(all_entries)
    if f_action:
        entries = [e for e in entries if e.action.value == f_action]
    if f_target_type:
        entries = [e for e in entries if e.target_type == f_target_type]
    if f_session_id:
        entries = [e for e in entries if e.session_id == f_session_id]
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
    total_pages = max((total + ACTIVITY_LOG_PAGE_SIZE - 1) // ACTIVITY_LOG_PAGE_SIZE, 1)
    page = min(max(page, 1), total_pages)
    page_entries = entries[(page - 1) * ACTIVITY_LOG_PAGE_SIZE: page * ACTIVITY_LOG_PAGE_SIZE]

    active_filters = sum([
        bool(f_action), bool(f_target_type), bool(f_session_id), bool(f_date_from), bool(f_date_to),
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
            "f_action": f_action,
            "f_target_type": f_target_type,
            "f_session_id": f_session_id,
            "f_date_from": f_date_from,
            "f_date_to": f_date_to,
            "page": page,
            "total_pages": total_pages,
            "total": total,
            "active_filters": active_filters,
            "active_club": active_club,
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
    stats = {key: db.scalar(select(func.count()).select_from(cfg["model"])) for key, cfg in RESET_TABLES.items()}
    stats["users"] = db.scalar(select(func.count()).select_from(User))
    return templates.TemplateResponse(
        "admin_settings.html",
        {
            "request": request,
            "user": current_user,
            "msg": msg,
            "reset_tables": RESET_TABLES,
            "stats": stats,
            "active_club": get_active_club(request, current_user, db),
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
    if confirm.strip() != "RESET":
        return RedirectResponse("/admin/settings?msg=confirm_error", status_code=303)

    selected = [key for key in RESET_DELETE_ORDER if key in tables and key in RESET_TABLES]
    if not selected:
        return RedirectResponse("/admin/settings?msg=no_selection", status_code=303)

    for key in selected:
        db.execute(delete(RESET_TABLES[key]["model"]))

    log_activity(
        db, ActivityAction.db_reset,
        user_id=current_user.id,
        detail={"tables": selected},
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
    saved_club = db.get(Club, current_user.club_id)
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
                "INSERT INTO users (email, password_hash, display_name, role, club_id, created_at) "
                "VALUES (:email, :pw_hash, :name, 'superadmin', :club_id, NOW()) RETURNING id"
            ),
            {"email": saved_email, "pw_hash": saved_hash, "name": saved_name, "club_id": new_club_id},
        )
        new_user_id = result.scalar()
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


def _issue_active_club_cookie(response, request: Request, current_user: User, club: Club) -> None:
    """Reemite la cookie de sesión con un nuevo club activo, preservando uid/sid."""
    response.set_cookie(
        "session",
        create_session_cookie(current_user.id, get_session_id(request), club.id),
        max_age=get_settings().session_max_age_days * 86400,
        httponly=True,
        samesite="lax",
    )


@router.get("/clubs", response_class=HTMLResponse)
def clubs_page(
    request: Request,
    current_user: User = Depends(require_superadmin),
    db: Session = Depends(get_db_dep),
):
    active_club = get_active_club(request, current_user, db)
    rows = db.execute(
        select(Club, func.count(User.id))
        .outerjoin(User, User.club_id == Club.id)
        .group_by(Club.id)
        .order_by(Club.name)
    ).all()
    clubs_data = [{"club": club, "member_count": count} for club, count in rows]

    return templates.TemplateResponse(
        "admin_clubs.html",
        {
            "request": request,
            "user": current_user,
            "clubs_data": clubs_data,
            "active_club": active_club,
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

    response = RedirectResponse("/admin/clubs", status_code=303)
    _issue_active_club_cookie(response, request, current_user, club)
    return response


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
    current_user: User = Depends(require_superadmin),
    db: Session = Depends(get_db_dep),
    club_id: int = Form(...),
):
    club = db.get(Club, club_id)
    if club is None:
        return RedirectResponse("/feed", status_code=303)

    log_activity(
        db, ActivityAction.club_switched,
        user_id=current_user.id,
        club_id=club.id,
        target_type="club",
        target_id=club.id,
        detail={"name": club.name},
        session_id=get_session_id(request),
    )

    redirect_to = request.headers.get("referer") or "/feed"
    response = RedirectResponse(redirect_to, status_code=303)
    _issue_active_club_cookie(response, request, current_user, club)
    return response
