import logging
import secrets

from fastapi import Depends, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from passlib.context import CryptContext

logging.getLogger("passlib").setLevel(logging.ERROR)
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db_dep
from app.exceptions import AccessDenied, NeedsLogin
from app.models.user import User, UserRole

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

COOKIE_NAME = "session"


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return _pwd_context.verify(password, hashed)


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().secret_key)


def _new_session_id() -> str:
    return secrets.token_hex(8)


def create_session_cookie(user_id: int, session_id: str) -> str:
    return _serializer().dumps({"uid": user_id, "sid": session_id})


def decode_session_cookie(value: str) -> dict | None:
    max_age = get_settings().session_max_age_days * 86400
    try:
        data = _serializer().loads(value, max_age=max_age)
        return {"uid": int(data["uid"]), "sid": data.get("sid")}
    except (BadSignature, SignatureExpired, KeyError, ValueError):
        return None


def get_current_user(request: Request, db: Session = Depends(get_db_dep)) -> User | None:
    cookie = request.cookies.get(COOKIE_NAME)
    if not cookie:
        return None
    data = decode_session_cookie(cookie)
    if not data:
        return None
    request.state.session_id = data.get("sid")
    return db.get(User, data["uid"])


def get_session_id(request: Request) -> str | None:
    """ID de la sesión de login actual, para asociarlo al activity log."""
    return getattr(request.state, "session_id", None)


def require_user(user: User | None = Depends(get_current_user)) -> User:
    if user is None:
        raise NeedsLogin()
    return user


def require_admin(user: User = Depends(require_user)) -> User:
    if user.role not in (UserRole.admin, UserRole.superadmin):
        raise AccessDenied()
    return user


def require_superadmin(user: User = Depends(require_user)) -> User:
    if user.role != UserRole.superadmin:
        raise AccessDenied()
    return user


def set_session(response, user_id: int) -> str:
    """Crea la cookie de sesión y devuelve el session_id generado (para el activity log)."""
    settings = get_settings()
    session_id = _new_session_id()
    response.set_cookie(
        COOKIE_NAME,
        create_session_cookie(user_id, session_id),
        max_age=settings.session_max_age_days * 86400,
        httponly=True,
        samesite="lax",
    )
    return session_id


def clear_session(response) -> None:
    response.delete_cookie(COOKIE_NAME, httponly=True, samesite="lax")
