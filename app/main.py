from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
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


@app.exception_handler(NeedsLogin)
async def needs_login_handler(request: Request, exc: NeedsLogin):
    return RedirectResponse("/login", status_code=303)


@app.exception_handler(AccessDenied)
async def access_denied_handler(request: Request, exc: AccessDenied):
    return templates.TemplateResponse(
        "403.html",
        {"request": request, "user": None},
        status_code=403,
    )
