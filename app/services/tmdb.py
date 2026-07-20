import httpx

from app.config import get_settings

TMDB_BASE = "https://api.themoviedb.org/3"
POSTER_BASE = "https://image.tmdb.org/t/p"

_genre_cache: dict[str, dict[int, str]] = {}


def poster_url(path: str | None, size: str = "w500") -> str | None:
    if not path:
        return None
    return f"{POSTER_BASE}/{size}{path}"


def _params(**extra) -> dict:
    return {"api_key": get_settings().tmdb_api_key, "language": "es-AR", **extra}


def _get_genre_map(media_type: str) -> dict[int, str]:
    cached = _genre_cache.get(media_type)
    if cached is not None:
        return cached
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(f"{TMDB_BASE}/genre/{media_type}/list", params=_params())
            resp.raise_for_status()
        genre_map = {g["id"]: g["name"] for g in resp.json().get("genres", [])}
    except httpx.HTTPError:
        genre_map = {}
    _genre_cache[media_type] = genre_map
    return genre_map


def _genre_id_for_name(media_type: str, name: str) -> int | None:
    for gid, gname in _get_genre_map(media_type).items():
        if gname == name:
            return gid
    return None


def get_all_genre_names() -> list[str]:
    names = set(_get_genre_map("movie").values()) | set(_get_genre_map("tv").values())
    return sorted(names)


def _search_person_id(name: str) -> int | None:
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(f"{TMDB_BASE}/search/person", params=_params(query=name))
            resp.raise_for_status()
        results = resp.json().get("results", [])
        return results[0]["id"] if results else None
    except httpx.HTTPError:
        return None


def _get_content_credits(tmdb_id: int, media_type: str) -> dict:
    """Devuelve reparto y directores (una sola llamada, detalle + créditos)."""
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(
                f"{TMDB_BASE}/{media_type}/{tmdb_id}",
                params=_params(append_to_response="credits"),
            )
            resp.raise_for_status()
        d = resp.json()
    except httpx.HTTPError:
        return {"cast": [], "directors": []}

    cast = [p["name"] for p in d.get("credits", {}).get("cast", [])[:10] if p.get("name")]
    directors = [
        p["name"]
        for p in d.get("credits", {}).get("crew", [])
        if p.get("job") == "Director" and p.get("name")
    ]
    if media_type == "tv":
        directors += [c["name"] for c in d.get("created_by", []) if c.get("name")]
    return {"cast": cast, "directors": directors}


def _to_result_item(r: dict, media_type: str) -> dict | None:
    title = r.get("title") or r.get("name")
    if not title:
        return None
    genre_map = _get_genre_map(media_type)
    genre_names = [genre_map.get(gid) for gid in r.get("genre_ids", []) if genre_map.get(gid)]
    return {
        "tmdb_id": r["id"],
        "media_type": media_type,
        "title": title,
        "poster_path": r.get("poster_path") or "",
        "poster_url_sm": poster_url(r.get("poster_path"), "w92"),
        "release_date": r.get("release_date") or r.get("first_air_date") or "",
        "overview": (r.get("overview") or "")[:300],
        "tmdb_rating": round(r["vote_average"], 1) if r.get("vote_average") else None,
        "genres": genre_names,
    }


def _apply_person_filters(items: list[dict], director: str, actor: str, limit: int = 20) -> list[dict]:
    if not (director or actor):
        return items
    filtered = []
    for item in items[:limit]:
        credits = _get_content_credits(item["tmdb_id"], item["media_type"])
        if director and not any(director.lower() in d.lower() for d in credits["directors"]):
            continue
        if actor and not any(actor.lower() in c.lower() for c in credits["cast"]):
            continue
        filtered.append(item)
    return filtered


def search_multi(
    query: str,
    genre: str = "",
    min_rating: float = 0,
    director: str = "",
    actor: str = "",
) -> list[dict]:
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(
                f"{TMDB_BASE}/search/multi",
                params=_params(query=query, include_adult="false"),
            )
            resp.raise_for_status()
        raw_results = resp.json().get("results", [])
    except httpx.HTTPError:
        return []

    items = []
    for r in raw_results:
        if r.get("media_type") not in ("movie", "tv"):
            continue
        item = _to_result_item(r, r["media_type"])
        if item:
            items.append(item)

    if genre:
        items = [i for i in items if genre in i["genres"]]
    if min_rating:
        items = [i for i in items if i["tmdb_rating"] and i["tmdb_rating"] >= min_rating]

    items = _apply_person_filters(items, director, actor)

    return items[:12]


def discover(
    genre: str = "",
    min_rating: float = 0,
    director: str = "",
    actor: str = "",
) -> list[dict]:
    """Explora contenido usando solo filtros, sin texto de título."""
    director_id = _search_person_id(director) if director else None
    if director and director_id is None:
        return []
    actor_id = _search_person_id(actor) if actor else None
    if actor and actor_id is None:
        return []

    results: list[dict] = []
    for media_type in ("movie", "tv"):
        genre_id = _genre_id_for_name(media_type, genre) if genre else None
        if genre and genre_id is None:
            continue

        params = _params(sort_by="popularity.desc", include_adult="false")
        params["vote_count.gte"] = 20
        if genre_id:
            params["with_genres"] = genre_id
        if min_rating:
            params["vote_average.gte"] = min_rating
        if actor_id:
            params["with_cast"] = actor_id
        if director_id:
            # with_people matches cast o crew; se confirma "director" abajo con los créditos
            params["with_people"] = director_id

        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(f"{TMDB_BASE}/discover/{media_type}", params=params)
                resp.raise_for_status()
            raw_results = resp.json().get("results", [])
        except httpx.HTTPError:
            raw_results = []

        for r in raw_results[:15]:
            item = _to_result_item(r, media_type)
            if item:
                results.append(item)

    if director:
        results = _apply_person_filters(results, director, "")

    results.sort(key=lambda i: i["tmdb_rating"] or 0, reverse=True)
    return results[:12]


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
