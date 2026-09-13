from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", extra="ignore")

    env: str = "development"
    secret_key: str = "development-only-secret-change-me"
    database_url: str = "sqlite+aiosqlite:///./data/study.db"
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: str = "http://localhost:3000,http://localhost:5173"
    access_token_minutes: int = 60

    def get_cors_origins(self) -> list[str]:
        """将逗号分隔的字符串转成列表，供 FastAPI CORSMiddleware 使用。"""
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

