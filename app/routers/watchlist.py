from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db import get_db_dep
from app.models.activity_log import ActivityAction
from app.models.suggestion import Suggestion
from app.models.user import User
from app.models.watchlist import WatchlistEntry, WatchlistStatus
from app.services.activity_log import log_activity
from app.services.auth import require_user

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/watchlist", response_class=HTMLResponse)
def watchlist_page(
    request: Request,
    current_user: User = Depends(require_user),
    db: Session = Depends(get_db_dep),
    genre: str = Query(default=""),
    media: str = Query(default=""),
    by: str = Query(default=""),
    sort: str = Query(default=""),
    status_filter: str = Query(default=""),
):
    all_entries = db.scalars(
        select(WatchlistEntry)
        .options(joinedload(WatchlistEntry.suggestion).joinedload(Suggestion.suggester))
        .where(WatchlistEntry.user_id == current_user.id)
        .order_by(WatchlistEntry.updated_at.desc())
    ).unique().all()

    # Build filter option data from all entries
    all_genres: list[str] = sorted({g for e in all_entries for g in e.suggestion.genres_list})
    suggesters: dict[int, User] = {}
    for e in all_entries:
        s = e.suggestion
        if s.suggester and s.suggested_by not in suggesters:
            suggesters[s.suggested_by] = s.suggester

    # Normalize filters
    f_media = media if media in ("movie", "tv") else ""
    f_genre = genre.strip()
    f_sort = sort if sort in ("name", "rating") else ""
    f_status = status_filter if status_filter in ("pending", "watched") else ""
    try:
        f_by = int(by)
    except (ValueError, TypeError):
        f_by = 0

    # Apply filters
    entries = list(all_entries)
    if f_status:
        entries = [e for e in entries if e.status.value == f_status]
    if f_media:
        entries = [e for e in entries if e.suggestion.media_type.value == f_media]
    if f_by:
        entries = [e for e in entries if e.suggestion.suggested_by == f_by]
    if f_genre:
        entries = [e for e in entries if f_genre in e.suggestion.genres_list]

    # Sort
    if f_sort == "name":
        entries = sorted(entries, key=lambda e: e.suggestion.title.lower())
    elif f_sort == "rating":
        entries = sorted(entries, key=lambda e: e.suggestion.tmdb_rating or 0, reverse=True)

    active_filters = sum([bool(f_genre), bool(f_media), bool(f_by), bool(f_status)])

    return templates.TemplateResponse(
        "watchlist.html",
        {
            "request": request,
            "user": current_user,
            "entries": entries,
            "total": len(all_entries),
            "all_genres": all_genres,
            "suggesters": suggesters,
            "f_genre": f_genre,
            "f_media": f_media,
            "f_by": f_by,
            "f_sort": f_sort,
            "f_status": f_status,
            "active_filters": active_filters,
        },
    )


@router.post("/watchlist/{suggestion_id}")
def watchlist_update(
    suggestion_id: int,
    status: str = Form(...),
    current_user: User = Depends(require_user),
    db: Session = Depends(get_db_dep),
):
    if status not in ("pending", "watched"):
        return RedirectResponse(f"/suggestions/{suggestion_id}", status_code=303)

    entry = db.scalar(
        select(WatchlistEntry).where(
            WatchlistEntry.user_id == current_user.id,
            WatchlistEntry.suggestion_id == suggestion_id,
        )
    )

    if entry and entry.status == WatchlistStatus(status):
        db.delete(entry)
    elif entry:
        entry.status = WatchlistStatus(status)
    else:
        if db.get(Suggestion, suggestion_id) is None:
            return RedirectResponse("/watchlist", status_code=303)
        db.add(WatchlistEntry(
            user_id=current_user.id,
            suggestion_id=suggestion_id,
            status=WatchlistStatus(status),
        ))

    log_activity(
        db, ActivityAction.watchlist_updated,
        user_id=current_user.id,
        target_type="suggestion",
        target_id=suggestion_id,
        detail={"status": status},
    )
    return RedirectResponse(f"/suggestions/{suggestion_id}", status_code=303)


@router.post("/watchlist/{suggestion_id}/rate")
def watchlist_rate(
    suggestion_id: int,
    rating: int = Form(0),
    watched_on: str = Form(""),
    current_user: User = Depends(require_user),
    db: Session = Depends(get_db_dep),
):
    entry = db.scalar(
        select(WatchlistEntry).where(
            WatchlistEntry.user_id == current_user.id,
            WatchlistEntry.suggestion_id == suggestion_id,
        )
    )
    clean_watched_on = watched_on.strip() or None
    if entry:
        if rating != 0:
            entry.rating = rating if 1 <= rating <= 10 else None
        entry.watched_on = clean_watched_on
    else:
        suggestion = db.get(Suggestion, suggestion_id)
        if suggestion and 1 <= rating <= 10:
            db.add(WatchlistEntry(
                user_id=current_user.id,
                suggestion_id=suggestion_id,
                status=WatchlistStatus.watched,
                rating=rating,
                watched_on=clean_watched_on,
            ))
    return RedirectResponse("/watchlist", status_code=303)
