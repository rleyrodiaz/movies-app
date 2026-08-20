from datetime import datetime, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.db import get_db_dep
from app.exceptions import AccessDenied
from app.models.activity_log import ActivityAction
from app.models.club_membership import ClubMembership
from app.models.suggestion import MediaType, Suggestion
from app.models.user import User
from app.models.watchlist import WatchlistEntry, WatchlistStatus
from app.services import tmdb
from app.services.activity_log import log_activity
from app.services.auth import get_current_user, get_session_id, require_user
from app.services.clubs import get_active_club, is_active_club_admin, list_clubs_for_switcher, list_own_clubs
from app.services.suggestion_creation import create_suggestion
from app.services.tz import to_local
from app.services.version import APP_VERSION

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["platform_choices"] = tmdb.PLATFORM_CHOICES
templates.env.globals["app_version"] = APP_VERSION


@router.get("/", response_class=HTMLResponse)
def landing(
    request: Request,
    current_user: User | None = Depends(get_current_user),
    login_error: str = Query(default=""),
):
    if current_user:
        return RedirectResponse("/feed", status_code=303)
    return templates.TemplateResponse(
        "landing.html",
        {"request": request, "user": current_user, "login_error": login_error},
    )


@router.get("/feed", response_class=HTMLResponse)
def feed(
    request: Request,
    current_user: User = Depends(require_user),
    db: Session = Depends(get_db_dep),
    genre: list[str] = Query(default=[]),
    platform: list[str] = Query(default=[]),
    media: str = Query(default=""),
    by: list[str] = Query(default=[]),
    sort: str = Query(default=""),
    status_filter: str = Query(default=""),
    min_rating: str = Query(default="0"),
):
    active_club = get_active_club(current_user, db)

    all_suggestions = db.scalars(
        select(Suggestion)
        .options(joinedload(Suggestion.suggester), selectinload(Suggestion.watchlist_entries))
        .where(Suggestion.club_id == active_club.id)
        .order_by(Suggestion.created_at.desc())
    ).unique().all()

    # "Nuevo desde tu última visita": va en la membresía (por club), no en el
    # usuario — si no, visitar el Feed de un club marcaría como "visto" las
    # novedades de todos tus otros clubes. La marca se "clava" en la
    # medianoche local del día en que avanza (no en "ahora"), así queda fija
    # durante todo ese día: el carrusel se mantiene estable en vez de
    # desaparecer apenas volvés a entrar, y va sumando lo que se agregue más
    # tarde ese mismo día. Recién al otro día vuelve a avanzar.
    membership = db.scalar(
        select(ClubMembership).where(
            ClubMembership.user_id == current_user.id,
            ClubMembership.club_id == active_club.id,
        )
    )
    new_since_last_visit: list[Suggestion] = []
    if membership is not None:
        previous_seen = membership.last_seen_feed_at
        now = datetime.now(timezone.utc)
        if previous_seen:
            new_since_last_visit = [s for s in all_suggestions if s.created_at > previous_seen]
        if previous_seen is None or to_local(previous_seen).date() < to_local(now).date():
            today_start_local = to_local(now).replace(hour=0, minute=0, second=0, microsecond=0)
            membership.last_seen_feed_at = today_start_local.astimezone(timezone.utc)

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
    f_genre = [g.strip() for g in genre if g.strip()]
    f_platform = [p.strip() for p in platform if p.strip()]
    f_sort = sort if sort in ("name", "rating") else ""
    f_status = status_filter if status_filter in ("pending", "watched") else ""
    f_my_platforms = "__mine__" in f_platform and bool(current_user.platforms_list)
    f_platform_specific = [p for p in f_platform if p != "__mine__"]
    f_by: list[int] = []
    for b in by:
        try:
            f_by.append(int(b))
        except (ValueError, TypeError):
            pass
    try:
        f_min_rating = max(0, min(10, int(min_rating)))
    except (ValueError, TypeError):
        f_min_rating = 0

    # Apply filters
    suggestions = list(all_suggestions)
    if f_media:
        suggestions = [s for s in suggestions if s.media_type.value == f_media]
    if f_by:
        suggestions = [s for s in suggestions if s.suggested_by in f_by]
    if f_genre:
        genre_set = set(f_genre)
        suggestions = [s for s in suggestions if genre_set & set(s.genres_list)]
    platform_set = set(f_platform_specific)
    if f_my_platforms:
        platform_set |= set(current_user.platforms_list)
    if platform_set:
        suggestions = [s for s in suggestions if platform_set & set(s.providers_list)]
    if f_min_rating:
        suggestions = [s for s in suggestions if s.avg_rating and s.avg_rating >= f_min_rating]
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

    active_filters = sum([
        bool(f_genre), bool(f_platform), bool(f_media), bool(f_by), bool(f_status), bool(f_min_rating),
    ])

    filter_qs = urlencode(
        {
            "genre": f_genre, "platform": f_platform, "media": f_media, "by": f_by,
            "sort": f_sort, "min_rating": f_min_rating, "status_filter": f_status,
        },
        doseq=True,
    )
    filter_qs_no_status = urlencode(
        {
            "genre": f_genre, "platform": f_platform, "media": f_media, "by": f_by,
            "sort": f_sort, "min_rating": f_min_rating,
        },
        doseq=True,
    )

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
            "f_min_rating": f_min_rating,
            "active_filters": active_filters,
            "filter_qs": filter_qs,
            "filter_qs_no_status": filter_qs_no_status,
            "has_any_suggestions": bool(all_suggestions),
            "total_count": len(all_suggestions),
            "new_since_last_visit": new_since_last_visit,
            "active_club": active_club,
            "is_club_admin": is_active_club_admin(current_user, active_club),
            "all_clubs": list_clubs_for_switcher(current_user, db),
        },
    )


@router.get("/suggestions/search")
def tmdb_search(
    request: Request,
    q: str = "",
    genre: list[str] = Query(default=[]),
    min_rating: float = Query(default=0.0),
    director: str = "",
    actor: str = "",
    current_user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db_dep),
):
    if current_user is None:
        return JSONResponse({"error": "not_authenticated"}, status_code=401)
    active_club = get_active_club(current_user, db)

    q = q.strip()
    genres = [g.strip() for g in genre if g.strip()]
    director = director.strip()
    actor = actor.strip()
    has_filters = bool(genres or min_rating or director or actor)

    if len(q) >= 2:
        results = tmdb.search_multi(q, genres=genres, min_rating=min_rating, director=director, actor=actor)
    elif has_filters:
        results = tmdb.discover(genres=genres, min_rating=min_rating, director=director, actor=actor)
    else:
        return JSONResponse([])

    if results:
        tmdb_ids = [r["tmdb_id"] for r in results]
        existing = db.scalars(
            select(Suggestion)
            .options(joinedload(Suggestion.suggester))
            .where(Suggestion.tmdb_id.in_(tmdb_ids), Suggestion.club_id == active_club.id)
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
    active_club = get_active_club(current_user, db)

    suggestions = db.scalars(
        select(Suggestion)
        .where(Suggestion.suggested_by == current_user.id, Suggestion.club_id == active_club.id)
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
    user_clubs = list_own_clubs(current_user, db)

    return templates.TemplateResponse(
        "suggestion_new.html",
        {
            "request": request,
            "user": current_user,
            "suggestions": suggestions,
            "rating_map": rating_map,
            "can_delete_map": can_delete_map,
            "genres": tmdb.get_all_genre_names(),
            "active_club": active_club,
            "user_clubs": user_clubs,
            "is_club_admin": is_active_club_admin(current_user, active_club),
            "all_clubs": list_clubs_for_switcher(current_user, db),
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
    club_ids: list[int] = Form(default=[]),
):
    if media_type not in ("movie", "tv"):
        return RedirectResponse("/suggestions/add", status_code=303)

    active_club = get_active_club(current_user, db)

    # Solo se puede sugerir a clubes propios (todos, si es superadmin) — se
    # ignora cualquier id ajeno.
    my_club_ids = {c.id for c in list_own_clubs(current_user, db)}
    target_ids = [cid for cid in dict.fromkeys(club_ids) if cid in my_club_ids] or [active_club.id]

    active_result_id: int | None = None
    active_was_existing = False
    for club_id in target_ids:
        # Se respeta lo que ya exista en ese club — no se duplica ni se pisa.
        existing = db.scalar(
            select(Suggestion).where(
                Suggestion.tmdb_id == tmdb_id,
                Suggestion.media_type == MediaType(media_type),
                Suggestion.club_id == club_id,
            )
        )
        if existing:
            result_id, was_existing = existing.id, True
        else:
            new_suggestion = create_suggestion(
                db, current_user.id, club_id, tmdb_id, media_type, title,
                poster_path=poster_path,
                overview=overview,
                release_date=release_date,
                rating=rating,
                comment=comment_body,
                session_id=get_session_id(request),
            )
            result_id, was_existing = new_suggestion.id, False

        if club_id == active_club.id:
            active_result_id, active_was_existing = result_id, was_existing

    if active_result_id is not None and active_was_existing:
        return RedirectResponse(f"/suggestions/{active_result_id}?duplicate=1", status_code=303)
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

    active_club = get_active_club(current_user, db)
    if suggestion.club_id != active_club.id:
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

    qp = request.query_params
    back_feed_qs = urlencode(
        {
            "genre": qp.getlist("genre"), "platform": qp.getlist("platform"),
            "media": qp.get("media", ""), "by": qp.getlist("by"),
            "sort": qp.get("sort", ""), "min_rating": qp.get("min_rating", ""),
            "status_filter": qp.get("status_filter", ""),
        },
        doseq=True,
    )

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
            "back_feed_qs": back_feed_qs,
            "active_club": active_club,
            "is_club_admin": is_active_club_admin(current_user, active_club),
            "all_clubs": list_clubs_for_switcher(current_user, db),
        },
    )


@router.get("/suggestions/{suggestion_id}/json", response_class=JSONResponse)
def suggestion_detail_json(
    suggestion_id: int,
    current_user: User = Depends(require_user),
    db: Session = Depends(get_db_dep),
):
    """Detalle de una sugerencia para el modal del feed (mismo criterio de
    acceso y permisos que la página suggestion_detail.html)."""
    suggestion = db.scalar(
        select(Suggestion)
        .options(
            joinedload(Suggestion.suggester),
            selectinload(Suggestion.watchlist_entries).joinedload(WatchlistEntry.user),
        )
        .where(Suggestion.id == suggestion_id)
    )
    if suggestion is None:
        return JSONResponse({"error": "not_found"}, status_code=404)

    active_club = get_active_club(current_user, db)
    if suggestion.club_id != active_club.id:
        return JSONResponse({"error": "not_found"}, status_code=404)

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

    return JSONResponse({
        "id": suggestion.id,
        "title": suggestion.title,
        "poster_path": suggestion.poster_path or "",
        "backdrop_path": suggestion.backdrop_path or "",
        "media_type": suggestion.media_type.value,
        "year": suggestion.release_date.year if suggestion.release_date else None,
        "overview": suggestion.overview or "",
        "genres": suggestion.genres_list,
        "country": suggestion.origin_country or "",
        "director": suggestion.director or "",
        "cast": suggestion.cast_list,
        "providers": suggestion.providers_list,
        "season_count": suggestion.season_count,
        "episode_count": suggestion.episode_count,
        "runtime_minutes": suggestion.runtime_minutes,
        "tmdb_rating": suggestion.tmdb_rating,
        "avg_rating": suggestion.avg_rating,
        "rating_count": suggestion.rating_count,
        "suggester_name": suggestion.suggester.display_name,
        "created_at": suggestion.created_at.strftime("%d/%m/%Y"),
        "is_owner": is_owner,
        "can_delete": can_delete,
        "watchlist_status": watchlist_entry.status.value if watchlist_entry else None,
        "watched_entries": [
            {
                "user": e.user.display_name,
                "rating": e.rating,
                "comment": e.comment or "",
                "watched_on": e.watched_on.isoformat() if e.watched_on else "",
            }
            for e in watched_entries
        ],
    })


@router.post("/suggestions/{suggestion_id}/delete")
def suggestion_delete(
    request: Request,
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

    title, media_type = suggestion.title, suggestion.media_type.value
    club_id = suggestion.club_id
    db.delete(suggestion)
    log_activity(
        db, ActivityAction.suggestion_deleted,
        user_id=current_user.id,
        club_id=club_id,
        target_type="suggestion",
        target_id=suggestion_id,
        detail={"title": title, "media_type": media_type},
        session_id=get_session_id(request),
    )
    if request.query_params.get("back") == "watchlist":
        return RedirectResponse("/watchlist", status_code=303)
    qp = request.query_params
    feed_qs = {
        "genre": qp.getlist("genre"), "platform": qp.getlist("platform"),
        "media": qp.get("media", ""), "by": qp.getlist("by"),
        "sort": qp.get("sort", ""), "min_rating": qp.get("min_rating", ""),
        "status_filter": qp.get("status_filter", ""),
    }
    query = f"?{urlencode(feed_qs, doseq=True)}"
    return RedirectResponse(f"/feed{query}", status_code=303)
