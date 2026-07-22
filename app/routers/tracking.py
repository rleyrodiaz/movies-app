import time

from fastapi import APIRouter, BackgroundTasks, Request

from app.config import get_settings
from app.services.emails import send_visit_notification
from app.services.visit import get_client_ip, get_geo, parse_device

router = APIRouter()

# ── RATE LIMITING AVISO DE VISITA ────────────────────────────────────────────
# El endpoint es público (sin login) y el único freno del lado del cliente es
# sessionStorage, que se puede saltear pegándole directo al endpoint. Esto
# limita cuántos emails puede gatillar una misma IP.
# Para desactivar: poner VISIT_EMAIL_RATE_LIMIT=false en .env.
VISIT_EMAIL_COOLDOWN_SEG = 5 * 60  # 5 minutos
_last_visit_email_by_ip: dict[str, float] = {}


def _visit_email_allowed(ip: str) -> bool:
    if not get_settings().visit_email_rate_limit or not ip:
        return True
    now = time.monotonic()
    last = _last_visit_email_by_ip.get(ip)
    if last is not None and (now - last) < VISIT_EMAIL_COOLDOWN_SEG:
        return False
    _last_visit_email_by_ip[ip] = now
    return True


def _notify_visit(ip: str, user_agent: str, entry_page: str, referrer: str, session_id: str) -> None:
    if not _visit_email_allowed(ip):
        return
    geo = get_geo(ip)
    device = parse_device(user_agent)
    send_visit_notification(
        ip=ip,
        country=geo.get("country", ""),
        city=geo.get("city", ""),
        device=device.get("device_type", ""),
        browser=device.get("browser", ""),
        os=device.get("os", ""),
        referrer=referrer,
        entry_page=entry_page,
        session_id=session_id,
    )


@router.post("/api/session/start")
async def session_start(request: Request, background_tasks: BackgroundTasks):
    """Ping público (sin login) que dispara el aviso por email una vez por
    sesión de navegador — el frontend lo llama solo la primera vez que ve
    la página en esa pestaña (dedup vía sessionStorage). Además, del lado
    del servidor, una misma IP no puede gatillar más de un email cada
    VISIT_EMAIL_COOLDOWN_SEG segundos, aunque le peguen directo al endpoint."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    session_id = str(body.get("session_id") or "")
    entry_page = str(body.get("entry_page") or "")
    referrer = str(body.get("referrer") or "")

    background_tasks.add_task(
        _notify_visit,
        get_client_ip(request),
        request.headers.get("user-agent", ""),
        entry_page,
        referrer,
        session_id,
    )
    return {"ok": True}
