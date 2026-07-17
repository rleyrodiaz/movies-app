import logging

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


def create_session_cookie(user_id: int) -> str:
    return _serializer().dumps({"uid": user_id})


def decode_session_cookie(value: str) -> int | None:
    max_age = get_settings().session_max_age_days * 86400
    try:
        data = _serializer().loads(value, max_age=max_age)
        return int(data["uid"])
    except (BadSignature, SignatureExpired, KeyError, ValueError):
        return None


def get_current_user(request: Request, db: Session = Depends(get_db_dep)) -> User | None:
    cookie = request.cookies.get(COOKIE_NAME)
    if not cookie:
        return None
    user_id = decode_session_cookie(cookie)
    if not user_id:
        return None
    return db.get(User, user_id)


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


def set_session(response, user_id: int) -> None:
    settings = get_settings()
    response.set_cookie(
        COOKIE_NAME,
        create_session_cookie(user_id),
        max_age=settings.session_max_age_days * 86400,
        httponly=True,
        samesite="lax",
    )


def clear_session(response) -> None:
    response.delete_cookie(COOKIE_NAME, httponly=True, samesite="lax")
