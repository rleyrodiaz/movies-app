from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.exceptions import AccessDenied, NeedsLogin
from app.routers import admin, auth, suggestions, tracking, watchlist

app = FastAPI(title="Movies & Series")

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

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


@app.exception_handler(NeedsLogin)
async def needs_login_handler(request: Request, exc: NeedsLogin):
    return RedirectResponse("/", status_code=303)


@app.exception_handler(AccessDenied)
async def access_denied_handler(request: Request, exc: AccessDenied):
    return templates.TemplateResponse(
        "403.html",
        {"request": request, "user": None},
        status_code=403,
    )
