import httpx

from app.config import get_settings

TMDB_BASE = "https://api.themoviedb.org/3"
POSTER_BASE = "https://image.tmdb.org/t/p"


def poster_url(path: str | None, size: str = "w500") -> str | None:
    if not path:
        return None
    return f"{POSTER_BASE}/{size}{path}"


def _params(**extra) -> dict:
    return {"api_key": get_settings().tmdb_api_key, "language": "es-AR", **extra}


def search_multi(query: str) -> list[dict]:
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(
                f"{TMDB_BASE}/search/multi",
                params=_params(query=query, include_adult="false"),
            )
            resp.raise_for_status()
        results = resp.json().get("results", [])
        return [
            {
                "tmdb_id": r["id"],
                "media_type": r["media_type"],
                "title": r.get("title") or r.get("name", ""),
                "poster_path": r.get("poster_path") or "",
                "poster_url_sm": poster_url(r.get("poster_path"), "w92"),
                "release_date": r.get("release_date") or r.get("first_air_date") or "",
                "overview": (r.get("overview") or "")[:300],
                "tmdb_rating": round(r["vote_average"], 1) if r.get("vote_average") else None,
            }
            for r in results
            if r.get("media_type") in ("movie", "tv")
            and (r.get("title") or r.get("name"))
        ][:10]
    except httpx.HTTPError:
        return []


def get_detail(tmdb_id: int, media_type: str) -> dict | None:
    try:
        with httpx.Client(timeout=8.0) as client:
            resp = client.get(
                f"{TMDB_BASE}/{media_type}/{tmdb_id}",
                params=_params(append_to_response="credits,watch/providers"),
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
        d = resp.json()

        # Reparto: primeros 3 actores
        cast = [
            p["name"]
            for p in d.get("credits", {}).get("cast", [])[:3]
            if p.get("name")
        ]

        # Plataformas para Argentina (flatrate = suscripción, luego rent/buy)
        wp_ar = d.get("watch/providers", {}).get("results", {}).get("AR", {})
        providers: list[str] = []
        seen: set[str] = set()
        for tier in ("flatrate", "rent", "buy"):
            for p in wp_ar.get(tier, []):
                name = p.get("provider_name", "")
                if name and name not in seen:
                    providers.append(name)
                    seen.add(name)

        # Géneros
        genres = [g["name"] for g in d.get("genres", []) if g.get("name")]

        # País de origen
        if media_type == "movie":
            countries = d.get("production_countries", [])
            origin = countries[0].get("name") if countries else None
            episode_count = None
        else:
            countries = d.get("origin_country", [])
            origin = countries[0] if countries else None
            episode_count = d.get("number_of_episodes")
            season_count = d.get("number_of_seasons")

        raw_rating = d.get("vote_average")
        tmdb_rating = round(raw_rating, 1) if raw_rating else None

        return {
            "title": d.get("title") or d.get("name", ""),
            "poster_path": d.get("poster_path") or "",
            "overview": d.get("overview") or "",
            "release_date": d.get("release_date") or d.get("first_air_date") or "",
            "genres": genres,
            "origin_country": origin,
            "cast": cast,
            "providers": providers,
            "episode_count": episode_count,
            "season_count": season_count if media_type == "tv" else None,
            "tmdb_rating": tmdb_rating,
        }
    except httpx.HTTPError:
        return None
