from urllib.parse import quote

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.exceptions import AccessDenied, NeedsLogin
from app.models.user import User
from app.routers import admin, auth, suggestions, tracking, watchlist
from app.services.auth import clear_session, get_current_user
from app.services.version import APP_VERSION

app = FastAPI(title="Movies & Series")

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["app_version"] = APP_VERSION

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(suggestions.router)
app.include_router(watchlist.router)
app.include_router(tracking.router)


@app.get("/sw.js")
def service_worker():
    # Servido en la raíz (no en /static) para que su scope cubra toda la app.
    return FileResponse(
        "app/static/sw.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"},
    )


@app.get("/manifest.json")
def manifest():
    return FileResponse("app/static/manifest.json", media_type="application/manifest+json")


@app.get("/guia", response_class=HTMLResponse)
def guia(request: Request, current_user: User | None = Depends(get_current_user)):
    # Pública (sin login) para poder compartirla con gente que todavía no se registró.
    return templates.TemplateResponse("guia.html", {"request": request, "user": current_user})


@app.exception_handler(NeedsLogin)
async def needs_login_handler(request: Request, exc: NeedsLogin):
    if getattr(request.state, "session_expired", False):
        message = quote("Tu sesión expiró por inactividad. Iniciá sesión de nuevo.")
        response = RedirectResponse(f"/?login_error={message}", status_code=303)
        clear_session(response)
        return response
    return RedirectResponse("/", status_code=303)


@app.exception_handler(AccessDenied)
async def access_denied_handler(request: Request, exc: AccessDenied):
    return templates.TemplateResponse(
        "403.html",
        {"request": request, "user": None},
        status_code=403,
    )
