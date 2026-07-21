import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Form, Request
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
from app.services.auth import clear_session, require_admin, require_superadmin

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


@router.get("/activity-log", response_class=HTMLResponse)
def activity_log_page(
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db_dep),
):
    entries = db.scalars(
        select(ActivityLog)
        .options(joinedload(ActivityLog.user))
        .order_by(ActivityLog.created_at.desc())
        .limit(200)
    ).unique().all()
    return templates.TemplateResponse(
        "admin_activity_log.html",
        {
            "request": request,
            "user": current_user,
            "entries": entries,
            "action_labels": ACTION_LABELS,
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
    current_user: User = Depends(require_superadmin),
    db: Session = Depends(get_db_dep),
):
    Base.metadata.create_all(bind=engine)
    log_activity(db, ActivityAction.db_initialized, user_id=current_user.id)
    return RedirectResponse("/admin/settings?msg=init_ok", status_code=303)


@router.post("/settings/reset-tables")
def settings_reset_tables(
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
    )
    return RedirectResponse("/admin/settings?msg=reset_tables_ok", status_code=303)


@router.post("/settings/reset")
def settings_reset(
    current_user: User = Depends(require_superadmin),
    confirm: str = Form(""),
):
    if confirm.strip() != "RESET":
        return RedirectResponse("/admin/settings?msg=confirm_error", status_code=303)

    saved_email = current_user.email
    saved_hash = current_user.password_hash
    saved_name = current_user.display_name

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
                "INSERT INTO activity_log (user_id, action, created_at) "
                "VALUES (:uid, 'db_reset', NOW())"
            ),
            {"uid": new_user_id},
        )

    response = RedirectResponse("/login", status_code=303)
    clear_session(response)
    return response
