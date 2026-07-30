import subprocess
from datetime import datetime, timezone


def _compute_version() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            capture_output=True, text=True, timeout=5, check=True,
        )
        count = result.stdout.strip()
    except Exception:
        count = "0"
    yy = datetime.now(timezone.utc).strftime("%y")
    return f"v{yy}-{count}"


# Se calcula una sola vez al arrancar el proceso (no en cada request).
APP_VERSION = _compute_version()
