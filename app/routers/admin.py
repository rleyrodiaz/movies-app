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
from app.models.invitation import Invitation
from app.models.suggestion import Suggestion
from app.models.user import User, UserRole
from app.models.watchlist import WatchlistEntry
from app.services.activity_log import log_activity
from app.services.auth import clear_session, get_session_id, require_admin, require_superadmin

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="app/templates")

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
RESET_DELETE_ORDER = ["watchlist", "suggestions", "invitations", "activity_log"]


@router.get("/invitations", response_class=HTMLResponse)
def invitations_page(
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db_dep),
):
    invitations = db.scalars(
        select(Invitation).order_by(Invitation.created_at.desc())
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
        msg = f"Te invito a Movies & Series! Registrate acá: {link}"
        invite_data.append({
            "inv": inv,
            "link": link,
            "is_used": is_used,
            "is_expired": is_expired,
            "is_active": not is_used and not is_expired,
            "wa_url": f"https://wa.me/?text={quote_plus(msg)}",
            "mailto_url": (
                f"mailto:?subject={quote_plus('Invitación a Movies & Series')}"
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
        },
    )


@router.post("/invitations")
def create_invitation(
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db_dep),
):
    settings = get_settings()
    invitation = Invitation(
        token=secrets.token_urlsafe(32),
        created_by=current_user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.invitation_expiry_days),
    )
    db.add(invitation)
    db.flush()
    log_activity(
        db, ActivityAction.invitation_created,
        user_id=current_user.id,
        target_type="invitation",
        target_id=invitation.id,
        session_id=get_session_id(request),
    )
    return RedirectResponse("/admin/invitations", status_code=303)


ACTION_LABELS = {
    "user_registered": "Nuevo usuario",
    "user_login": "Login",
    "suggestion_created": "Sugerencia creada",
    "comment_created": "Comentario creado",
    "watchlist_updated": "Watchlist actualizada",
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
    all_entries = db.scalars(
        select(ActivityLog)
        .options(joinedload(ActivityLog.user))
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
            entries = [e for e in entries if e.created_at.date() >= d_from]
        except ValueError:
            f_date_from = ""
    if f_date_to:
        try:
            d_to = date.fromisoformat(f_date_to)
            entries = [e for e in entries if e.created_at.date() <= d_to]
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
    confirm: str = Form(""),
):
    if confirm.strip() != "RESET":
        return RedirectResponse("/admin/settings?msg=confirm_error", status_code=303)

    saved_email = current_user.email
    saved_hash = current_user.password_hash
    saved_name = current_user.display_name
    session_id = get_session_id(request)

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    with engine.begin() as conn:
        result = conn.execute(
            text(
                "INSERT INTO users (email, password_hash, display_name, role, created_at) "
                "VALUES (:email, :pw_hash, :name, 'superadmin', NOW()) RETURNING id"
            ),
            {"email": saved_email, "pw_hash": saved_hash, "name": saved_name},
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
