import json
from datetime import date

from sqlalchemy.orm import Session

from app.models.activity_log import ActivityAction
from app.models.suggestion import MediaType, Suggestion
from app.models.watchlist import WatchlistEntry, WatchlistStatus
from app.services import tmdb
from app.services.activity_log import log_activity


def _jsondump(v: list) -> str | None:
    return json.dumps(v, ensure_ascii=False) if v else None


def create_suggestion(
    db: Session,
    user_id: int,
    club_id: int,
    tmdb_id: int,
    media_type: str,
    title: str,
    poster_path: str = "",
    overview: str = "",
    release_date: str = "",
    rating: int = 0,
    comment: str = "",
    session_id: str | None = None,
) -> Suggestion:
    """Crea una Suggestion pública con datos frescos de TMDB, junto con la
    calificación y comentario de quien la sugiere (entrada de watchlist oculta,
    igual que el resto de las sugerencias propias)."""
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

    suggestion = Suggestion(
        tmdb_id=tmdb_id,
        media_type=MediaType(media_type),
        title=final_title,
        poster_path=final_poster,
        overview=final_overview,
        release_date=parsed_date,
        suggested_by=user_id,
        club_id=club_id,
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

    valid_rating = rating if 1 <= rating <= 10 else None
    clean_comment = comment.strip() or None
    entry = WatchlistEntry(
        user_id=user_id,
        suggestion_id=suggestion.id,
        status=WatchlistStatus.watched,
        rating=valid_rating,
        comment=clean_comment,
        hidden_from_watchlist=True,
    )
    db.add(entry)

    log_activity(
        db, ActivityAction.suggestion_created,
        user_id=user_id,
        club_id=club_id,
        target_type="suggestion",
        target_id=suggestion.id,
        detail={"title": final_title, "media_type": media_type},
        session_id=session_id,
    )
    return suggestion
