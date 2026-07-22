from datetime import datetime, timedelta, timezone

# Argentina no observa horario de verano desde 2009, así que un offset fijo alcanza.
LOCAL_TZ = timezone(timedelta(hours=-3))


def to_local(dt: datetime) -> datetime:
    """Convierte un datetime (naive = UTC, o aware) a hora local (UTC-3)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(LOCAL_TZ)
