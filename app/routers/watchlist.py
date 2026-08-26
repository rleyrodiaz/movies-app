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
from app.models.club import Club
from app.models.reminder import PersonalReminder
from app.models.suggestion import MediaType, Suggestion
from app.models.user import User
from app.models.watchlist import WatchlistEntry, WatchlistStatus
from app.services import tmdb
from app.services.activity_log import log_activity
from app.services.auth import get_session_id, require_user
from app.services.clubs import get_active_club, is_active_club_admin, list_clubs_for_switcher, list_own_clubs
from app.services.suggestion_creation import create_suggestion
from app.services.version import APP_VERSION

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["platform_choices"] = tmdb.PLATFORM_CHOICES
templates.env.globals["app_version"] = APP_VERSION


@router.get("/watchlist", response_class=HTMLResponse)
def watchlist_page(
    request: Request,
    current_user: User = Depends(require_user),
    db: Session = Depends(get_db_dep),
    genre: list[str] = Query(default=[]),
    platform: list[str] = Query(default=[]),
    media: str = Query(default=""),
    by: list[str] = Query(default=[]),
    sort: str = Query(default=""),
    status_filter: str = Query(default=""),
):
    active_club = get_active_club(current_user, db)

    all_entries = db.scalars(
        select(WatchlistEntry)
        .join(Suggestion, WatchlistEntry.suggestion_id == Suggestion.id)
        .options(
            joinedload(WatchlistEntry.suggestion).options(
                joinedload(Suggestion.suggester),
                selectinload(Suggestion.watchlist_entries).joinedload(WatchlistEntry.user),
            )
        )
        .where(
            WatchlistEntry.user_id == current_user.id,
            WatchlistEntry.hidden_from_watchlist.is_(False),
            Suggestion.club_id == active_club.id,
        )
        .order_by(WatchlistEntry.updated_at.desc())
    ).unique().all()

    # Los recordatorios son privados y no tienen club propio — solo tiene sentido
    # mostrarlos cuando estás parado en un club del que sos miembro de verdad
    # (para el superadmin viendo un club ajeno, no son "suyos" en ese contexto).
    if any(m.club_id == active_club.id for m in current_user.memberships):
        all_reminders = db.scalars(
            select(PersonalReminder)
            .where(PersonalReminder.user_id == current_user.id)
            .order_by(PersonalReminder.created_at.desc())
        ).all()
    else:
        all_reminders = []

    # Build filter option data from all entries + reminders
    all_genres: list[str] = sorted({g for e in all_entries for g in e.suggestion.genres_list})
    all_platforms: list[str] = sorted(
        {p for e in all_entries for p in e.suggestion.providers_list}
        | {p for r in all_reminders for p in r.providers_list}
    )
    suggesters: dict[int, User] = {}
    for e in all_entries:
        s = e.suggestion
        if s.suggester and s.suggested_by not in suggesters:
            suggesters[s.suggested_by] = s.suggester

    # Normalize filters
    f_media = media if media in ("movie", "tv") else ""
    f_genre = [g.strip() for g in genre if g.strip()]
    f_platform = [p.strip() for p in platform if p.strip()]
    f_sort = sort if sort in ("name", "rating") else ""
    f_status = status_filter if status_filter in ("pending", "watched") else ""
    f_by: list[int] = []
    for b in by:
        try:
            f_by.append(int(b))
        except (ValueError, TypeError):
            pass

    # Apply filters
    entries = list(all_entries)
    if f_status:
        entries = [e for e in entries if e.status.value == f_status]
    if f_media:
        entries = [e for e in entries if e.suggestion.media_type.value == f_media]
    if f_by:
        entries = [e for e in entries if e.suggestion.suggested_by in f_by]
    if f_genre:
        genre_set = set(f_genre)
        entries = [e for e in entries if genre_set & set(e.suggestion.genres_list)]
    f_my_platforms = "__mine__" in f_platform and bool(current_user.platforms_list)
    f_platform_specific = [p for p in f_platform if p != "__mine__"]
    platform_set = set(f_platform_specific)
    if f_my_platforms:
        platform_set |= set(current_user.platforms_list)
    if platform_set:
        entries = [e for e in entries if platform_set & set(e.suggestion.providers_list)]

    # Sort
    if f_sort == "name":
        entries = sorted(entries, key=lambda e: e.suggestion.title.lower())
    elif f_sort == "rating":
        entries = sorted(entries, key=lambda e: e.suggestion.tmdb_rating or 0, reverse=True)

    active_filters = sum([bool(f_genre), bool(f_platform), bool(f_media), bool(f_by), bool(f_status)])

    reminders = list(all_reminders)
    if platform_set:
        reminders = [r for r in reminders if platform_set & set(r.providers_list)]

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
            "active_club": active_club,
            "is_club_admin": is_active_club_admin(current_user, active_club),
            "all_clubs": list_clubs_for_switcher(current_user, db),
            "user_clubs": list_own_clubs(current_user, db),
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

    active_club = get_active_club(current_user, db)

    # Si ya es una sugerencia pública en este club, se agrega normalmente como
    # pendiente en vez de crear un recordatorio privado duplicado.
    existing = db.scalar(
        select(Suggestion).where(
            Suggestion.tmdb_id == tmdb_id,
            Suggestion.media_type == MediaType(media_type),
            Suggestion.club_id == active_club.id,
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
            club_id=active_club.id,
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
    if already:
        club_name = None
        if already.created_in_club_id:
            club = db.get(Club, already.created_in_club_id)
            club_name = club.name if club else None
        return JSONResponse({"status": "duplicate", "club_name": club_name})

    parsed_date: date | None = None
    if release_date:
        try:
            parsed_date = date.fromisoformat(release_date[:10])
        except ValueError:
            pass
    detail = tmdb.get_detail(tmdb_id, media_type) or {}
    reminder = PersonalReminder(
        user_id=current_user.id,
        created_in_club_id=active_club.id,
        tmdb_id=tmdb_id,
        media_type=MediaType(media_type),
        title=title,
        poster_path=poster_path or None,
        overview=overview or None,
        release_date=parsed_date,
        tmdb_rating=detail.get("tmdb_rating"),
        providers=json.dumps(detail.get("providers", []), ensure_ascii=False) if detail.get("providers") else None,
    )
    db.add(reminder)
    db.flush()
    log_activity(
        db, ActivityAction.reminder_created,
        user_id=current_user.id,
        club_id=active_club.id,
        target_type="reminder",
        target_id=reminder.id,
        detail={"title": title, "media_type": media_type},
        session_id=get_session_id(request),
    )
    return JSONResponse({"status": "created"})


@router.get("/watchlist/reminders/json", response_class=JSONResponse)
def reminders_json(
    current_user: User = Depends(require_user),
    db: Session = Depends(get_db_dep),
):
    """Lista de recordatorios del usuario, para refrescar la pantalla de
    Recordatorios en el lugar (sin recargar toda la página) tras agregar uno."""
    active_club = get_active_club(current_user, db)
    if not any(m.club_id == active_club.id for m in current_user.memberships):
        return JSONResponse([])

    reminders = db.scalars(
        select(PersonalReminder)
        .where(PersonalReminder.user_id == current_user.id)
        .order_by(PersonalReminder.created_at.desc())
    ).all()
    return JSONResponse([
        {
            "id": r.id,
            "tmdb_id": r.tmdb_id,
            "title": r.title,
            "poster_path": r.poster_path or "",
            "media_type": r.media_type.value,
            "year": r.release_date.year if r.release_date else None,
            "overview": r.overview or "",
            "tmdb_rating": r.tmdb_rating,
            "providers_list": r.providers_list,
        }
        for r in reminders
    ])


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

    active_club = get_active_club(current_user, db)
    if suggestion.club_id != active_club.id:
        return RedirectResponse("/watchlist", status_code=303)

    entry = db.scalar(
        select(WatchlistEntry).where(
            WatchlistEntry.user_id == current_user.id,
            WatchlistEntry.suggestion_id == suggestion_id,
        )
    )

    # Si ya tiene una calificación guardada, este endpoint (el toggle simple
    # de "pendiente") no la toca — evita que un tap accidental en el corazón
    # pise el status de una entrada ya calificada. Editar o borrar una
    # calificación hecha se hace por /rate o /remove.
    if entry and entry.hidden_from_watchlist:
        return RedirectResponse(f"/suggestions/{suggestion_id}", status_code=303)

    if entry and entry.status == WatchlistStatus(status) and not entry.hidden_from_watchlist:
        db.delete(entry)
        action = ActivityAction.watchlist_removed
    else:
        if entry:
            entry.status = WatchlistStatus(status)
            entry.hidden_from_watchlist = status == "watched"
        else:
            db.add(WatchlistEntry(
                user_id=current_user.id,
                suggestion_id=suggestion_id,
                status=WatchlistStatus(status),
                hidden_from_watchlist=status == "watched",
            ))
        action = ActivityAction.watchlist_added

    log_activity(
        db, action,
        user_id=current_user.id,
        club_id=active_club.id,
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
    clean_watched_on = None
    if watched_on.strip():
        try:
            clean_watched_on = date.fromisoformat(watched_on.strip())
        except ValueError:
            clean_watched_on = None
    clean_comment = comment.strip() or None
    valid_rating = rating if 1 <= rating <= 10 else None
    suggestion = entry.suggestion if entry else db.get(Suggestion, suggestion_id)

    active_club = get_active_club(current_user, db)
    if suggestion and suggestion.club_id != active_club.id:
        return RedirectResponse("/watchlist", status_code=303)

    if entry:
        entry.watched_on = clean_watched_on
        entry.comment = clean_comment
        if valid_rating is not None:
            entry.rating = valid_rating
            entry.status = WatchlistStatus.watched
            entry.hidden_from_watchlist = True
    else:
        if suggestion and valid_rating is not None:
            db.add(WatchlistEntry(
                user_id=current_user.id,
                suggestion_id=suggestion_id,
                status=WatchlistStatus.watched,
                rating=valid_rating,
                watched_on=clean_watched_on,
                comment=clean_comment,
                hidden_from_watchlist=True,
            ))

    if suggestion and valid_rating is not None:
        log_activity(
            db, ActivityAction.watchlist_rated,
            user_id=current_user.id,
            club_id=suggestion.club_id,
            target_type="suggestion",
            target_id=suggestion_id,
            detail={"title": suggestion.title, "media_type": suggestion.media_type.value},
            session_id=get_session_id(request),
        )
    return RedirectResponse("/watchlist", status_code=303)


@router.post("/watchlist/{suggestion_id}/remove", response_class=JSONResponse)
def watchlist_remove(
    request: Request,
    suggestion_id: int,
    current_user: User = Depends(require_user),
    db: Session = Depends(get_db_dep),
):
    """Borra por completo la entrada de watchlist del usuario para esta
    sugerencia (pendiente o ya calificada) — a diferencia de POST
    /watchlist/{suggestion_id}, que solo saca de pendientes."""
    entry = db.scalar(
        select(WatchlistEntry).where(
            WatchlistEntry.user_id == current_user.id,
            WatchlistEntry.suggestion_id == suggestion_id,
        )
    )
    if entry is None:
        return JSONResponse({"status": "not_found"}, status_code=404)

    suggestion = entry.suggestion
    db.delete(entry)
    log_activity(
        db, ActivityAction.watchlist_removed,
        user_id=current_user.id,
        club_id=suggestion.club_id,
        target_type="suggestion",
        target_id=suggestion_id,
        detail={"title": suggestion.title, "media_type": suggestion.media_type.value},
        session_id=get_session_id(request),
    )
    return JSONResponse({"status": "removed"})


@router.post("/watchlist/reminders/{reminder_id}/rate")
def reminder_promote(
    request: Request,
    reminder_id: int,
    rating: int = Form(0),
    comment: str = Form(""),
    club_ids: list[int] = Form(default=[]),
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

    active_club = get_active_club(current_user, db)

    # Solo se puede publicar en clubes propios (todos, si es superadmin) — se
    # ignora cualquier id ajeno. Si no llega ninguno válido, se usa el club activo.
    my_club_ids = {c.id for c in list_own_clubs(current_user, db)}
    target_ids = [cid for cid in dict.fromkeys(club_ids) if cid in my_club_ids] or [active_club.id]

    clean_comment = comment.strip() or None
    last_suggestion_id: int | None = None
    for club_id in target_ids:
        # Puede haberse sugerido públicamente mientras estaba en tus recordatorios.
        # En ese caso no se pierde tu calificación: se aplica sobre la sugerencia existente.
        existing = db.scalar(
            select(Suggestion).where(
                Suggestion.tmdb_id == reminder.tmdb_id,
                Suggestion.media_type == reminder.media_type,
                Suggestion.club_id == club_id,
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
                entry.rating = rating
                entry.comment = clean_comment
                entry.status = WatchlistStatus.watched
                entry.hidden_from_watchlist = True
            else:
                db.add(WatchlistEntry(
                    user_id=current_user.id,
                    suggestion_id=existing.id,
                    status=WatchlistStatus.watched,
                    rating=rating,
                    comment=clean_comment,
                    hidden_from_watchlist=True,
                ))
            log_activity(
                db, ActivityAction.watchlist_rated,
                user_id=current_user.id,
                club_id=club_id,
                target_type="suggestion",
                target_id=existing.id,
                detail={"title": existing.title, "media_type": existing.media_type.value},
                session_id=get_session_id(request),
            )
            last_suggestion_id = existing.id
        else:
            new_suggestion = create_suggestion(
                db, current_user.id, club_id, reminder.tmdb_id, reminder.media_type.value, reminder.title,
                poster_path=reminder.poster_path or "",
                overview=reminder.overview or "",
                release_date=reminder.release_date.isoformat() if reminder.release_date else "",
                rating=rating,
                comment=comment,
                session_id=get_session_id(request),
            )
            last_suggestion_id = new_suggestion.id

    db.delete(reminder)
    return RedirectResponse(f"/suggestions/{last_suggestion_id}?duplicate=1", status_code=303)


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
