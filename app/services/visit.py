import httpx
from fastapi import Request


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


def get_geo(ip: str) -> dict:
    """Geolocalización aproximada por IP (ip-api.com, gratis, sin API key)."""
    if not ip or ip in ("127.0.0.1", "::1", "testclient"):
        return {}
    try:
        resp = httpx.get(
            f"http://ip-api.com/json/{ip}",
            params={"fields": "country,city,status"},
            timeout=2.0,
        )
        data = resp.json()
        if data.get("status") == "success":
            return {"country": data.get("country"), "city": data.get("city")}
    except httpx.HTTPError:
        pass
    return {}


def parse_device(user_agent_str: str) -> dict:
    try:
        from user_agents import parse
        ua = parse(user_agent_str or "")
        device = "mobile" if ua.is_mobile else "tablet" if ua.is_tablet else "desktop"
        return {"device_type": device, "browser": ua.browser.family, "os": ua.os.family}
    except Exception:
        return {}
