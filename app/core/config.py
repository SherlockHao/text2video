from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    PROJECT_NAME: str = "text2video"
    VERSION: str = "0.1.0"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@db:5432/text2video"
    REDIS_URL: str = "redis://redis:6379/0"

    ALLOWED_ORIGINS: str = "http://localhost:3000"
    STORAGE_ROOT: str = "./storage"


settings = Settings()
