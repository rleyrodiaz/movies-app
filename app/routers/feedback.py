from fastapi import APIRouter, BackgroundTasks, Depends, Form
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db_dep
from app.models.app_feedback import AppFeedback
from app.models.user import User
from app.services.auth import require_user
from app.services.emails import send_feedback_notification

router = APIRouter()


@router.get("/feedback/mine", response_class=JSONResponse)
def my_feedback_draft(
    current_user: User = Depends(require_user),
    db: Session = Depends(get_db_dep),
):
    draft = db.scalar(
        select(AppFeedback).where(
            AppFeedback.user_id == current_user.id, AppFeedback.checked.is_(False)
        )
    )
    return JSONResponse({"text": draft.text if draft else ""})


@router.post("/feedback", response_class=JSONResponse)
def save_feedback_draft(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_user),
    db: Session = Depends(get_db_dep),
    text: str = Form(""),
):
    clean_text = text.strip()
    draft = db.scalar(
        select(AppFeedback).where(
            AppFeedback.user_id == current_user.id, AppFeedback.checked.is_(False)
        )
    )
    if not clean_text:
        if draft:
            db.delete(draft)
        return JSONResponse({"ok": True})

    if draft:
        draft.text = clean_text
    else:
        db.add(AppFeedback(user_id=current_user.id, text=clean_text))
        # Solo se avisa por email cuando nace una entrada nueva — no en cada
        # edición mientras la persona sigue puliendo lo que escribió.
        background_tasks.add_task(send_feedback_notification, current_user.display_name, clean_text)
    return JSONResponse({"ok": True})
