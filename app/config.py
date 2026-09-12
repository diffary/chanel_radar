"""Application settings. Everything secret comes from the environment (or .env)."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # SQLite default lets the app boot locally / in tests without Postgres.
    DATABASE_URL: str = "sqlite+aiosqlite:///./dev.db"
    GEMINI_API_KEY: str | None = None
    COLLECT_SECRET: str = "change-me"


settings = Settings()
