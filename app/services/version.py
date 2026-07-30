import os
import subprocess


def _compute_version() -> str:
    env_sha = os.environ.get("RENDER_GIT_COMMIT")
    if env_sha:
        return f"v{env_sha[:7]}"
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=7", "HEAD"],
            capture_output=True, text=True, timeout=5, check=True,
        )
        return f"v{result.stdout.strip()}"
    except Exception:
        return "v?"


# Se calcula una sola vez al arrancar el proceso (no en cada request). Mismo
# mecanismo en local y en Render, para poder comparar los dos hashes a simple
# vista y confirmar si Render tiene el mismo código que hay en local.
APP_VERSION = _compute_version()
