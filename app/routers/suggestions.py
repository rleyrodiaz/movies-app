import json
from datetime import date

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.db import get_db_dep
from app.exceptions import AccessDenied
from app.models.activity_log import ActivityAction
from app.models.suggestion import MediaType, Suggestion
from app.models.user import User
from app.models.watchlist import WatchlistEntry, WatchlistStatus
from app.services import tmdb
from app.services.activity_log import log_activity
from app.services.auth import get_current_user, get_session_id, require_user

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
def landing(
    request: Request,
    current_user: User | None = Depends(get_current_user),
    login_error: str = Query(default=""),
):
    return templates.TemplateResponse(
        "landing.html",
        {"request": request, "user": current_user, "login_error": login_error},
    )


@router.get("/feed", response_class=HTMLResponse)
def feed(
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
    all_suggestions = db.scalars(
        select(Suggestion)
        .options(joinedload(Suggestion.suggester), selectinload(Suggestion.watchlist_entries))
        .order_by(Suggestion.created_at.desc())
    ).unique().all()

    # Build filter option data
    all_genres: list[str] = sorted({g for s in all_suggestions for g in s.genres_list})
    all_platforms: list[str] = sorted({p for s in all_suggestions for p in s.providers_list})
    suggesters: dict[int, User] = {}
    for s in all_suggestions:
        if s.suggester and s.suggested_by not in suggesters:
            suggesters[s.suggested_by] = s.suggester

    entries = db.scalars(
        select(WatchlistEntry).where(WatchlistEntry.user_id == current_user.id)
    ).all()
    watchlist_map = {e.suggestion_id: e for e in entries}

    # Normalize filter values
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
    suggestions = list(all_suggestions)
    if f_media:
        suggestions = [s for s in suggestions if s.media_type.value == f_media]
    if f_by:
        suggestions = [s for s in suggestions if s.suggested_by == f_by]
    if f_genre:
        suggestions = [s for s in suggestions if f_genre in s.genres_list]
    if f_platform:
        suggestions = [s for s in suggestions if f_platform in s.providers_list]
    if f_status == "watched":
        suggestions = [
            s for s in suggestions
            if watchlist_map.get(s.id) and watchlist_map[s.id].status == WatchlistStatus.watched
        ]
    elif f_status == "pending":
        suggestions = [
            s for s in suggestions
            if not (watchlist_map.get(s.id) and watchlist_map[s.id].status == WatchlistStatus.watched)
        ]

    # Apply sort (default: most recent, already sorted by query)
    if f_sort == "name":
        suggestions = sorted(suggestions, key=lambda s: s.title.lower())
    elif f_sort == "rating":
        suggestions = sorted(suggestions, key=lambda s: s.tmdb_rating or 0, reverse=True)

    active_filters = sum([bool(f_genre), bool(f_platform), bool(f_media), bool(f_by), bool(f_status)])

    return templates.TemplateResponse(
        "feed.html",
        {
            "request": request,
            "user": current_user,
            "suggestions": suggestions,
            "all_genres": all_genres,
            "all_platforms": all_platforms,
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


@router.get("/suggestions/search")
def tmdb_search(
    q: str = "",
    genre: str = "",
    min_rating: float = Query(default=0.0),
    director: str = "",
    actor: str = "",
    current_user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db_dep),
):
    if current_user is None:
        return JSONResponse({"error": "not_authenticated"}, status_code=401)

    q = q.strip()
    genre = genre.strip()
    director = director.strip()
    actor = actor.strip()
    has_filters = bool(genre or min_rating or director or actor)

    if len(q) >= 2:
        results = tmdb.search_multi(q, genre=genre, min_rating=min_rating, director=director, actor=actor)
    elif has_filters:
        results = tmdb.discover(genre=genre, min_rating=min_rating, director=director, actor=actor)
    else:
        return JSONResponse([])

    if results:
        tmdb_ids = [r["tmdb_id"] for r in results]
        existing = db.scalars(
            select(Suggestion)
            .options(joinedload(Suggestion.suggester))
            .where(Suggestion.tmdb_id.in_(tmdb_ids))
        ).unique().all()
        existing_map = {(s.tmdb_id, s.media_type.value): s for s in existing}
        for r in results:
            match = existing_map.get((r["tmdb_id"], r["media_type"]))
            if match:
                r["already_suggested"] = True
                r["suggested_by_name"] = match.suggester.display_name if match.suggester else "alguien"
                r["existing_id"] = match.id
            else:
                r["already_suggested"] = False
                r["existing_id"] = None
    return JSONResponse(results)


@router.get("/suggestions/tmdb-detail")
def tmdb_detail(
    tmdb_id: int,
    media_type: str,
    current_user: User | None = Depends(get_current_user),
):
    if current_user is None:
        return JSONResponse({"error": "not_authenticated"}, status_code=401)
    if media_type not in ("movie", "tv"):
        return JSONResponse({"error": "invalid_media_type"}, status_code=400)
    detail = tmdb.get_detail(tmdb_id, media_type)
    if detail is None:
        return JSONResponse({"error": "not_found"}, status_code=404)
    return JSONResponse(detail)


@router.get("/suggestions/new", response_class=HTMLResponse)
def my_suggestions(
    request: Request,
    current_user: User = Depends(require_user),
    db: Session = Depends(get_db_dep),
):
    suggestions = db.scalars(
        select(Suggestion)
        .where(Suggestion.suggested_by == current_user.id)
        .options(
            selectinload(Suggestion.watchlist_entries).joinedload(WatchlistEntry.user),
        )
        .order_by(Suggestion.created_at.desc())
    ).unique().all()
    sug_ids = [s.id for s in suggestions]

    entries = db.scalars(
        select(WatchlistEntry).where(
            WatchlistEntry.user_id == current_user.id,
            WatchlistEntry.suggestion_id.in_(sug_ids) if sug_ids else False,
        )
    ).all()
    rating_map = {e.suggestion_id: e for e in entries}

    # Suggestions that other users added to their watchlist cannot be deleted
    locked_ids: set[int] = set()
    if sug_ids:
        locked_ids = set(db.scalars(
            select(WatchlistEntry.suggestion_id).where(
                WatchlistEntry.suggestion_id.in_(sug_ids),
                WatchlistEntry.user_id != current_user.id,
            )
        ).all())

    can_delete_map = {s.id: s.id not in locked_ids for s in suggestions}

    return templates.TemplateResponse(
        "suggestion_new.html",
        {
            "request": request,
            "user": current_user,
            "suggestions": suggestions,
            "rating_map": rating_map,
            "can_delete_map": can_delete_map,
            "genres": tmdb.get_all_genre_names(),
        },
    )


@router.get("/suggestions/add", response_class=HTMLResponse)
def suggestion_add(
    request: Request,
    current_user: User = Depends(require_user),
):
    return RedirectResponse("/suggestions/new", status_code=303)


@router.post("/suggestions")
def suggestion_create(
    request: Request,
    current_user: User = Depends(require_user),
    db: Session = Depends(get_db_dep),
    tmdb_id: int = Form(...),
    media_type: str = Form(...),
    title: str = Form(...),
    poster_path: str = Form(""),
    overview: str = Form(""),
    release_date: str = Form(""),
    rating: int = Form(0),
    comment_body: str = Form(""),
):
    if media_type not in ("movie", "tv"):
        return RedirectResponse("/suggestions/add", status_code=303)

    # Check if already suggested by anyone
    existing = db.scalar(
        select(Suggestion).where(
            Suggestion.tmdb_id == tmdb_id,
            Suggestion.media_type == MediaType(media_type),
        )
    )
    if existing:
        return RedirectResponse(f"/suggestions/{existing.id}?duplicate=1", status_code=303)

    detail = tmdb.get_detail(tmdb_id, media_type) or {}
    final_title = detail.get("title") or title
    final_poster = detail.get("poster_path") or poster_path or None
    final_overview = detail.get("overview") or overview or None
    final_date_str = detail.get("release_date") or release_date or None

    parsed_date: date | None = None
    if final_date_str:
        try:
            parsed_date = date.fromisoformat(final_date_str[:10])
        except ValueError:
            pass

    def _jsondump(v: list) -> str | None:
        return json.dumps(v, ensure_ascii=False) if v else None

    suggestion = Suggestion(
        tmdb_id=tmdb_id,
        media_type=MediaType(media_type),
        title=final_title,
        poster_path=final_poster,
        overview=final_overview,
        release_date=parsed_date,
        suggested_by=current_user.id,
        genres=_jsondump(detail.get("genres", [])),
        origin_country=detail.get("origin_country") or None,
        director=detail.get("director") or None,
        cast_summary=_jsondump(detail.get("cast", [])),
        providers=_jsondump(detail.get("providers", [])),
        episode_count=detail.get("episode_count"),
        season_count=detail.get("season_count"),
        tmdb_rating=detail.get("tmdb_rating"),
    )
    db.add(suggestion)
    db.flush()

    # Auto-create watchlist entry (watched + rating + comentario opcional) para
    # guardar la opinión del sugerente, pero oculta de "Mi watchlist" hasta que
    # se agregue explícitamente desde el feed.
    valid_rating = rating if 1 <= rating <= 10 else None
    clean_comment = comment_body.strip() or None
    entry = WatchlistEntry(
        user_id=current_user.id,
        suggestion_id=suggestion.id,
        status=WatchlistStatus.watched,
        rating=valid_rating,
        comment=clean_comment,
        hidden_from_watchlist=True,
    )
    db.add(entry)

    log_activity(
        db, ActivityAction.suggestion_created,
        user_id=current_user.id,
        target_type="suggestion",
        target_id=suggestion.id,
        detail={"title": final_title, "media_type": media_type},
        session_id=get_session_id(request),
    )
    return RedirectResponse("/suggestions/new", status_code=303)


@router.get("/suggestions/{suggestion_id}", response_class=HTMLResponse)
def suggestion_detail(
    suggestion_id: int,
    request: Request,
    current_user: User = Depends(require_user),
    db: Session = Depends(get_db_dep),
):
    suggestion = db.scalar(
        select(Suggestion)
        .options(
            joinedload(Suggestion.suggester),
            selectinload(Suggestion.watchlist_entries).joinedload(WatchlistEntry.user),
        )
        .where(Suggestion.id == suggestion_id)
    )
    if suggestion is None:
        return RedirectResponse("/feed", status_code=303)

    watchlist_entry = next(
        (e for e in suggestion.watchlist_entries if e.user_id == current_user.id), None
    )
    watched_entries = sorted(
        (e for e in suggestion.watchlist_entries if e.rating is not None),
        key=lambda e: e.updated_at,
        reverse=True,
    )

    is_owner = suggestion.suggested_by == current_user.id
    can_delete = is_owner and not any(
        e.user_id != suggestion.suggested_by for e in suggestion.watchlist_entries
    )

    nav_active = "watchlist" if request.query_params.get("back") == "watchlist" else "feed"

    return templates.TemplateResponse(
        "suggestion_detail.html",
        {
            "request": request,
            "user": current_user,
            "s": suggestion,
            "poster_url": tmdb.poster_url,
            "watchlist_entry": watchlist_entry,
            "watched_entries": watched_entries,
            "is_owner": is_owner,
            "can_delete": can_delete,
            "nav_active": nav_active,
        },
    )


@router.post("/suggestions/{suggestion_id}/delete")
def suggestion_delete(
    suggestion_id: int,
    current_user: User = Depends(require_user),
    db: Session = Depends(get_db_dep),
):
    suggestion = db.get(Suggestion, suggestion_id)
    if suggestion is None:
        return RedirectResponse("/feed", status_code=303)
    if suggestion.suggested_by != current_user.id:
        raise AccessDenied()
    # Block deletion if any other user has it in their watchlist
    locked = db.scalar(
        select(WatchlistEntry.id).where(
            WatchlistEntry.suggestion_id == suggestion_id,
            WatchlistEntry.user_id != current_user.id,
        )
    )
    if locked:
        return RedirectResponse(f"/suggestions/{suggestion_id}?locked=1", status_code=303)
    db.delete(suggestion)
    return RedirectResponse("/suggestions/new", status_code=303)
