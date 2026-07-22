from datetime import datetime, timezone

import resend

from app.config import get_settings
from app.services.tz import to_local


def _send(to: str, subject: str, html: str) -> bool:
    settings = get_settings()
    if not settings.resend_api_key or not to:
        return False
    try:
        resend.api_key = settings.resend_api_key
        resend.Emails.send({"from": settings.email_from, "to": to, "subject": subject, "html": html})
        return True
    except Exception as e:
        print(f"[WARN] Error enviando email '{subject}' -> {to}: {e}")
        return False


def send_visit_notification(
    ip: str | None = None,
    country: str = "",
    city: str = "",
    device: str = "",
    browser: str = "",
    os: str = "",
    referrer: str = "",
    entry_page: str = "",
    session_id: str = "",
) -> bool:
    settings = get_settings()
    to = settings.visit_notify_to
    if not to:
        return False

    hora = to_local(datetime.now(timezone.utc)).strftime("%d/%m/%Y %H:%M")
    geo = ", ".join(filter(None, [city, country])) or "—"
    disp = " · ".join(filter(None, [device, browser, os])) or "—"
    ref = referrer or "directo"

    html = f"""
      <div style="font-family:Arial,Helvetica,sans-serif;max-width:480px;margin:0 auto;color:#1a1a1a">
        <p style="font-size:0.7rem;letter-spacing:0.1em;text-transform:uppercase;color:#7c3aed;margin:0 0 8px">movieLeyro</p>
        <h2 style="margin:0 0 16px;font-size:1.2rem">Nueva visita al sitio</h2>
        <table style="width:100%;border-collapse:collapse;font-size:0.9rem">
          <tr><td style="padding:4px 8px 4px 0;color:#666">Hora</td><td style="padding:4px 0">{hora}</td></tr>
          <tr><td style="padding:4px 8px 4px 0;color:#666">Ubicación</td><td style="padding:4px 0">{geo}</td></tr>
          <tr><td style="padding:4px 8px 4px 0;color:#666">IP</td><td style="padding:4px 0">{ip or '—'}</td></tr>
          <tr><td style="padding:4px 8px 4px 0;color:#666">Dispositivo</td><td style="padding:4px 0">{disp}</td></tr>
          <tr><td style="padding:4px 8px 4px 0;color:#666">Página de entrada</td><td style="padding:4px 0">{entry_page or '/'}</td></tr>
          <tr><td style="padding:4px 8px 4px 0;color:#666">Origen</td><td style="padding:4px 0">{ref}</td></tr>
          <tr><td style="padding:4px 8px 4px 0;color:#666">Session ID</td><td style="padding:4px 0;font-family:monospace;font-size:0.8rem">{session_id or '—'}</td></tr>
        </table>
      </div>
    """
    return _send(to, f"movieLeyro — Nueva visita desde {geo}", html)
