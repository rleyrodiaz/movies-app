from datetime import date

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.db import get_db_dep
from app.exceptions import AccessDenied
from app.models.activity_log import ActivityAction
from app.models.reminder import PersonalReminder
from app.models.suggestion import MediaType, Suggestion
from app.models.user import User
from app.models.watchlist import WatchlistEntry, WatchlistStatus
from app.services import tmdb
from app.services.activity_log import log_activity
from app.services.auth import get_session_id, require_user
from app.services.suggestion_creation import create_suggestion

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/watchlist", response_class=HTMLResponse)
def watchlist_page(
    request: Request,
    current_user: User = Depends(require_user),
    db: Session = Depends(get_db_dep),
    genre: str = Query(default=""),
    platform: str = Query(default=""),
    media: str = Query(default=""),
    by: str = Query(default=""),
    sort: str = Query(default=""),
    status_filter: str = Query(default=""),
):
    all_entries = db.scalars(
        select(WatchlistEntry)
        .options(
            joinedload(WatchlistEntry.suggestion).options(
                joinedload(Suggestion.suggester),
                selectinload(Suggestion.watchlist_entries),
            )
        )
        .where(
            WatchlistEntry.user_id == current_user.id,
            WatchlistEntry.hidden_from_watchlist.is_(False),
        )
        .order_by(WatchlistEntry.updated_at.desc())
    ).unique().all()

    # Build filter option data from all entries
    all_genres: list[str] = sorted({g for e in all_entries for g in e.suggestion.genres_list})
    all_platforms: list[str] = sorted({p for e in all_entries for p in e.suggestion.providers_list})
    suggesters: dict[int, User] = {}
    for e in all_entries:
        s = e.suggestion
        if s.suggester and s.suggested_by not in suggesters:
            suggesters[s.suggested_by] = s.suggester

    # Normalize filters
    f_media = media if media in ("movie", "tv") else ""
    f_genre = genre.strip()
    f_platform = platform.strip()
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
    if f_platform:
        entries = [e for e in entries if f_platform in e.suggestion.providers_list]

    # Sort
    if f_sort == "name":
        entries = sorted(entries, key=lambda e: e.suggestion.title.lower())
    elif f_sort == "rating":
        entries = sorted(entries, key=lambda e: e.suggestion.tmdb_rating or 0, reverse=True)

    active_filters = sum([bool(f_genre), bool(f_platform), bool(f_media), bool(f_by), bool(f_status)])

    reminders = db.scalars(
        select(PersonalReminder)
        .where(PersonalReminder.user_id == current_user.id)
        .order_by(PersonalReminder.created_at.desc())
    ).all()

    return templates.TemplateResponse(
        "watchlist.html",
        {
            "request": request,
            "user": current_user,
            "entries": entries,
            "total": len(all_entries),
            "reminders": reminders,
            "all_genres": all_genres,
            "all_platforms": all_platforms,
            "tmdb_genres": tmdb.get_all_genre_names(),
            "suggesters": suggesters,
            "f_genre": f_genre,
            "f_platform": f_platform,
            "f_media": f_media,
            "f_by": f_by,
            "f_sort": f_sort,
            "f_status": f_status,
            "active_filters": active_filters,
        },
    )


@router.post("/watchlist/reminders")
def reminder_create(
    request: Request,
    current_user: User = Depends(require_user),
    db: Session = Depends(get_db_dep),
    tmdb_id: int = Form(...),
    media_type: str = Form(...),
    title: str = Form(...),
    poster_path: str = Form(""),
    overview: str = Form(""),
    release_date: str = Form(""),
):
    if media_type not in ("movie", "tv"):
        return RedirectResponse("/watchlist", status_code=303)

    # Si ya es una sugerencia pública, se agrega normalmente como pendiente
    # en vez de crear un recordatorio privado duplicado.
    existing = db.scalar(
        select(Suggestion).where(
            Suggestion.tmdb_id == tmdb_id,
            Suggestion.media_type == MediaType(media_type),
        )
    )
    if existing:
        entry = db.scalar(
            select(WatchlistEntry).where(
                WatchlistEntry.user_id == current_user.id,
                WatchlistEntry.suggestion_id == existing.id,
            )
        )
        if entry:
            entry.hidden_from_watchlist = False
        else:
            db.add(WatchlistEntry(
                user_id=current_user.id,
                suggestion_id=existing.id,
                status=WatchlistStatus.pending,
            ))
        log_activity(
            db, ActivityAction.watchlist_added,
            user_id=current_user.id,
            target_type="suggestion",
            target_id=existing.id,
            detail={"title": existing.title, "media_type": existing.media_type.value},
            session_id=get_session_id(request),
        )
        return RedirectResponse("/watchlist", status_code=303)

    already = db.scalar(
        select(PersonalReminder).where(
            PersonalReminder.user_id == current_user.id,
            PersonalReminder.tmdb_id == tmdb_id,
            PersonalReminder.media_type == MediaType(media_type),
        )
    )
    if not already:
        parsed_date: date | None = None
        if release_date:
            try:
                parsed_date = date.fromisoformat(release_date[:10])
            except ValueError:
                pass
        reminder = PersonalReminder(
            user_id=current_user.id,
            tmdb_id=tmdb_id,
            media_type=MediaType(media_type),
            title=title,
            poster_path=poster_path or None,
            overview=overview or None,
            release_date=parsed_date,
        )
        db.add(reminder)
        db.flush()
        log_activity(
            db, ActivityAction.reminder_created,
            user_id=current_user.id,
            target_type="reminder",
            target_id=reminder.id,
            detail={"title": title, "media_type": media_type},
            session_id=get_session_id(request),
        )
    return RedirectResponse("/watchlist", status_code=303)


@router.post("/watchlist/{suggestion_id}")
def watchlist_update(
    request: Request,
    suggestion_id: int,
    status: str = Form(...),
    current_user: User = Depends(require_user),
    db: Session = Depends(get_db_dep),
):
    if status not in ("pending", "watched"):
        return RedirectResponse(f"/suggestions/{suggestion_id}", status_code=303)

    suggestion = db.get(Suggestion, suggestion_id)
    if suggestion is None:
        return RedirectResponse("/watchlist", status_code=303)

    entry = db.scalar(
        select(WatchlistEntry).where(
            WatchlistEntry.user_id == current_user.id,
            WatchlistEntry.suggestion_id == suggestion_id,
        )
    )

    if entry and entry.status == WatchlistStatus(status) and not entry.hidden_from_watchlist:
        db.delete(entry)
        action = ActivityAction.watchlist_removed
    else:
        if entry:
            entry.status = WatchlistStatus(status)
            entry.hidden_from_watchlist = False
        else:
            db.add(WatchlistEntry(
                user_id=current_user.id,
                suggestion_id=suggestion_id,
                status=WatchlistStatus(status),
            ))
        action = ActivityAction.watchlist_added

    log_activity(
        db, action,
        user_id=current_user.id,
        target_type="suggestion",
        target_id=suggestion_id,
        detail={"title": suggestion.title, "media_type": suggestion.media_type.value},
        session_id=get_session_id(request),
    )
    return RedirectResponse(f"/suggestions/{suggestion_id}", status_code=303)


@router.post("/watchlist/{suggestion_id}/rate")
def watchlist_rate(
    request: Request,
    suggestion_id: int,
    rating: int = Form(0),
    watched_on: str = Form(""),
    comment: str = Form(""),
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
    clean_comment = comment.strip() or None
    valid_rating = rating if 1 <= rating <= 10 else None
    suggestion = entry.suggestion if entry else db.get(Suggestion, suggestion_id)

    if entry:
        entry.watched_on = clean_watched_on
        entry.comment = clean_comment
        if valid_rating is not None:
            entry.rating = valid_rating
            entry.status = WatchlistStatus.watched
    else:
        if suggestion and valid_rating is not None:
            db.add(WatchlistEntry(
                user_id=current_user.id,
                suggestion_id=suggestion_id,
                status=WatchlistStatus.watched,
                rating=valid_rating,
                watched_on=clean_watched_on,
                comment=clean_comment,
            ))

    if suggestion and valid_rating is not None:
        log_activity(
            db, ActivityAction.watchlist_rated,
            user_id=current_user.id,
            target_type="suggestion",
            target_id=suggestion_id,
            detail={"title": suggestion.title, "media_type": suggestion.media_type.value},
            session_id=get_session_id(request),
        )
    return RedirectResponse("/watchlist", status_code=303)


@router.post("/watchlist/reminders/{reminder_id}/rate")
def reminder_promote(
    request: Request,
    reminder_id: int,
    rating: int = Form(0),
    comment: str = Form(""),
    current_user: User = Depends(require_user),
    db: Session = Depends(get_db_dep),
):
    reminder = db.get(PersonalReminder, reminder_id)
    if reminder is None:
        return RedirectResponse("/watchlist", status_code=303)
    if reminder.user_id != current_user.id:
        raise AccessDenied()
    if not (1 <= rating <= 10):
        return RedirectResponse("/watchlist", status_code=303)

    # Puede haberse sugerido públicamente mientras estaba en tus recordatorios.
    # En ese caso no se pierde tu calificación: se aplica sobre la sugerencia existente.
    existing = db.scalar(
        select(Suggestion).where(
            Suggestion.tmdb_id == reminder.tmdb_id,
            Suggestion.media_type == reminder.media_type,
        )
    )
    if existing:
        clean_comment = comment.strip() or None
        entry = db.scalar(
            select(WatchlistEntry).where(
                WatchlistEntry.user_id == current_user.id,
                WatchlistEntry.suggestion_id == existing.id,
            )
        )
        if entry:
            entry.rating = rating
            entry.comment = clean_comment
            entry.status = WatchlistStatus.watched
            entry.hidden_from_watchlist = False
        else:
            db.add(WatchlistEntry(
                user_id=current_user.id,
                suggestion_id=existing.id,
                status=WatchlistStatus.watched,
                rating=rating,
                comment=clean_comment,
            ))
        log_activity(
            db, ActivityAction.watchlist_rated,
            user_id=current_user.id,
            target_type="suggestion",
            target_id=existing.id,
            detail={"title": existing.title, "media_type": existing.media_type.value},
            session_id=get_session_id(request),
        )
        db.delete(reminder)
        return RedirectResponse(f"/suggestions/{existing.id}?duplicate=1", status_code=303)

    create_suggestion(
        db, current_user.id, reminder.tmdb_id, reminder.media_type.value, reminder.title,
        poster_path=reminder.poster_path or "",
        overview=reminder.overview or "",
        release_date=reminder.release_date.isoformat() if reminder.release_date else "",
        rating=rating,
        comment=comment,
        session_id=get_session_id(request),
    )
    db.delete(reminder)
    return RedirectResponse("/suggestions/new", status_code=303)


@router.post("/watchlist/reminders/{reminder_id}/discard")
def reminder_discard(
    reminder_id: int,
    current_user: User = Depends(require_user),
    db: Session = Depends(get_db_dep),
):
    reminder = db.get(PersonalReminder, reminder_id)
    if reminder is None:
        return RedirectResponse("/watchlist", status_code=303)
    if reminder.user_id != current_user.id:
        raise AccessDenied()
    db.delete(reminder)
    return RedirectResponse("/watchlist", status_code=303)
