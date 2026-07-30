import os
import subprocess
from datetime import datetime, timezone

from sqlalchemy import select

from app.db import get_db
from app.models.app_version import AppVersionCommit


def _current_commit_sha() -> str:
    env_sha = os.environ.get("RENDER_GIT_COMMIT")
    if env_sha:
        return env_sha
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5, check=True,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def _compute_version() -> str:
    sha = _current_commit_sha()
    yy = datetime.now(timezone.utc).strftime("%y")
    try:
        with get_db() as db:
            row = db.scalar(select(AppVersionCommit).where(AppVersionCommit.commit_sha == sha))
            if row is None:
                row = AppVersionCommit(commit_sha=sha)
                db.add(row)
                db.flush()
            return f"v{yy}-{row.id}"
    except Exception:
        return f"v{yy}-?"


# Se calcula una sola vez al arrancar el proceso (no en cada request). El
# número sube de a uno solo cuando llega un commit nuevo a producción, sin
# depender de cuánto historial de git haya disponible en tiempo de ejecución.
APP_VERSION = _compute_version()
