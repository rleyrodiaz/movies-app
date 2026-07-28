import json
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db_dep
from app.models.activity_log import ActivityAction
from app.models.club import Club
from app.models.invitation import Invitation
from app.models.user import User
from app.services import tmdb
from app.services.activity_log import log_activity
from app.services.auth import (
    clear_session,
    get_current_user,
    hash_password,
    require_user,
    set_session,
    verify_password,
)
from app.services.emails import send_login_notification, send_registration_notification
from app.services.visit import get_client_ip, parse_device

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["platform_choices"] = tmdb.PLATFORM_CHOICES


def _client_origin(request: Request) -> dict:
    """De dónde vino el login: IP real (respetando proxy) + user agent."""
    forwarded = request.headers.get("x-forwarded-for")
    ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else None)
    return {"ip": ip, "user_agent": request.headers.get("user-agent")}


@router.get("/login")
def login_page(error: str = ""):
    # La página de login vieja quedó reemplazada por el modal de login en "/".
    query = f"?login_error={quote(error)}" if error else ""
    return RedirectResponse(f"/{query}", status_code=303)


@router.post("/login")
def login_submit(
    request: Request,
    background_tasks: BackgroundTasks,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db_dep),
):
    user = db.scalar(select(User).where(User.email == email.lower().strip()))
    if not user or not verify_password(password, user.password_hash):
        return RedirectResponse(
            f"/?login_error={quote('Email o contraseña incorrectos.')}",
            status_code=303,
        )
    response = RedirectResponse("/feed", status_code=303)
    session_id = set_session(response, user.id, user.club_id)
    log_activity(
        db, ActivityAction.user_login,
        user_id=user.id,
        club_id=user.club_id,
        detail=_client_origin(request),
        session_id=session_id,
    )

    club = db.get(Club, user.club_id)
    device = parse_device(request.headers.get("user-agent", ""))
    background_tasks.add_task(
        send_login_notification,
        user.display_name,
        user.email,
        get_client_ip(request),
        device.get("device_type", ""),
        device.get("browser", ""),
        device.get("os", ""),
        club.name if club else "",
    )
    return response


@router.post("/logout")
def logout():
    response = RedirectResponse("/", status_code=303)
    clear_session(response)
    return response


@router.get("/register/{token}", response_class=HTMLResponse)
def register_page(
    token: str,
    request: Request,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db_dep),
):
    invitation = _get_valid_invitation(token, db)
    return templates.TemplateResponse(
        "landing.html",
        {
            "request": request,
            "user": user,
            "login_error": "",
            "register_open": True,
            "token": token,
            "invitation_invalid": invitation is None,
        },
    )


@router.post("/register/{token}")
def register_submit(
    token: str,
    request: Request,
    background_tasks: BackgroundTasks,
    display_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db_dep),
):
    invitation = _get_valid_invitation(token, db)
    if invitation is None:
        return templates.TemplateResponse(
            "landing.html",
            {
                "request": request,
                "user": user,
                "login_error": "",
                "register_open": True,
                "token": token,
                "invitation_invalid": True,
            },
        )

    errors: list[str] = []
    if len(display_name.strip()) < 2:
        errors.append("El nombre debe tener al menos 2 caracteres.")
    if "@" not in email or "." not in email:
        errors.append("Email inválido.")
    if len(password) < 8:
        errors.append("La contraseña debe tener al menos 8 caracteres.")
    if password != confirm_password:
        errors.append("Las contraseñas no coinciden.")

    if not errors:
        existing = db.scalar(select(User).where(User.email == email.lower().strip()))
        if existing:
            errors.append("Ya existe una cuenta con ese email.")

    if errors:
        return templates.TemplateResponse(
            "landing.html",
            {
                "request": request,
                "user": user,
                "login_error": "",
                "register_open": True,
                "token": token,
                "invitation_invalid": False,
                "errors": errors,
                "form": {"display_name": display_name, "email": email},
            },
        )

    user = User(
        email=email.lower().strip(),
        password_hash=hash_password(password),
        display_name=display_name.strip(),
        invited_by=invitation.created_by,
        club_id=invitation.club_id,
    )
    db.add(user)
    db.flush()

    invitation.used_by = user.id
    invitation.used_at = datetime.now(timezone.utc)

    response = RedirectResponse("/", status_code=303)
    session_id = set_session(response, user.id, user.club_id)

    log_activity(
        db, ActivityAction.user_registered,
        user_id=user.id,
        club_id=invitation.club_id,
        target_type="invitation",
        target_id=invitation.id,
        session_id=session_id,
    )
    log_activity(
        db, ActivityAction.invitation_used,
        user_id=invitation.created_by,
        club_id=invitation.club_id,
        target_type="invitation",
        target_id=invitation.id,
        detail={"used_by_email": user.email},
        session_id=session_id,
    )

    club = db.get(Club, invitation.club_id)
    inviter_name = invitation.creator.display_name if invitation.creator else ""
    background_tasks.add_task(
        send_registration_notification,
        user.display_name,
        user.email,
        inviter_name,
        club.name if club else "",
    )

    return response


def _get_valid_invitation(token: str, db: Session) -> Invitation | None:
    invitation = db.scalar(select(Invitation).where(Invitation.token == token))
    if invitation is None or invitation.used_by is not None:
        return None
    if invitation.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        return None
    return invitation


@router.post("/profile/platforms")
async def update_platforms(
    request: Request,
    current_user: User = Depends(require_user),
    db: Session = Depends(get_db_dep),
):
    form = await request.form()
    valid_values = {value for value, _ in tmdb.PLATFORM_CHOICES}
    selected = [v for v in form.getlist("platforms") if v in valid_values]
    current_user.platforms = json.dumps(selected, ensure_ascii=False) if selected else None
    return JSONResponse({"ok": True, "platforms": selected})


@router.post("/profile/password")
def update_password(
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    current_user: User = Depends(require_user),
    db: Session = Depends(get_db_dep),
):
    if not verify_password(current_password, current_user.password_hash):
        return JSONResponse({"ok": False, "error": "La contraseña actual es incorrecta."}, status_code=400)
    if len(new_password) < 8:
        return JSONResponse({"ok": False, "error": "La nueva contraseña debe tener al menos 8 caracteres."}, status_code=400)
    if new_password != confirm_password:
        return JSONResponse({"ok": False, "error": "Las contraseñas no coinciden."}, status_code=400)

    current_user.password_hash = hash_password(new_password)
    return JSONResponse({"ok": True})
