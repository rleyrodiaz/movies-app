from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db_dep
from app.models.activity_log import ActivityAction
from app.models.invitation import Invitation
from app.models.user import User
from app.services.activity_log import log_activity
from app.services.auth import (
    clear_session,
    get_current_user,
    hash_password,
    set_session,
    verify_password,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _client_origin(request: Request) -> dict:
    """De dónde vino el login: IP real (respetando proxy) + user agent."""
    forwarded = request.headers.get("x-forwarded-for")
    ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else None)
    return {"ip": ip, "user_agent": request.headers.get("user-agent")}


@router.get("/login", response_class=HTMLResponse)
def login_page(
    request: Request,
    user: User | None = Depends(get_current_user),
    error: str = "",
):
    if user:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "error": error})


@router.post("/login")
def login_submit(
    request: Request,
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
    session_id = set_session(response, user.id)
    log_activity(
        db, ActivityAction.user_login,
        user_id=user.id,
        detail=_client_origin(request),
        session_id=session_id,
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
    )
    db.add(user)
    db.flush()

    invitation.used_by = user.id
    invitation.used_at = datetime.now(timezone.utc)

    response = RedirectResponse("/", status_code=303)
    session_id = set_session(response, user.id)

    log_activity(
        db, ActivityAction.user_registered,
        user_id=user.id,
        target_type="invitation",
        target_id=invitation.id,
        session_id=session_id,
    )
    log_activity(
        db, ActivityAction.invitation_used,
        user_id=invitation.created_by,
        target_type="invitation",
        target_id=invitation.id,
        detail={"used_by_email": user.email},
        session_id=session_id,
    )

    return response


def _get_valid_invitation(token: str, db: Session) -> Invitation | None:
    invitation = db.scalar(select(Invitation).where(Invitation.token == token))
    if invitation is None or invitation.used_by is not None:
        return None
    if invitation.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        return None
    return invitation
