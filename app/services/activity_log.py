import json

from sqlalchemy.orm import Session

from app.models.activity_log import ActivityAction, ActivityLog


def log_activity(
    db: Session,
    action: ActivityAction,
    user_id: int | None = None,
    target_type: str | None = None,
    target_id: int | None = None,
    detail: dict | str | None = None,
    session_id: str | None = None,
) -> None:
    detail_str = json.dumps(detail, ensure_ascii=False) if isinstance(detail, dict) else detail
    db.add(ActivityLog(
        user_id=user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=detail_str,
        session_id=session_id,
    ))
