from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    secret_key: str
    tmdb_api_key: str
    invitation_expiry_days: int = 7
    session_max_age_days: int = 30
    resend_api_key: str = ""
    email_from: str = "onboarding@resend.dev"
    visit_notify_to: str = ""
    visit_email_rate_limit: bool = True

    model_config = {"env_file": ".env"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
