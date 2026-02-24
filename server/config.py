import os
from pathlib import Path
from pydantic_settings import BaseSettings
from functools import lru_cache

_ENV_FILE = Path(__file__).parent / ".env"


class Settings(BaseSettings):
    supabase_url: str
    supabase_key: str          # service_role key (bypasses RLS)
    bot_token: str
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 30
    server_url: str = "http://localhost:8000"
    webhook_path: str = "/webhook/telegram"
    github_repo: str = ""  # "owner/repo" for GitHub Releases

    model_config = {"env_file": str(_ENV_FILE), "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
