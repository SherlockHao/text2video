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

    # LLM
    QWEN_API_KEY: str = ""
    QWEN_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    QWEN_MODEL: str = "qwen3.5-plus"
    LLM_PROVIDER: str = "qwen"

    # Image Generation (Jimeng)
    JIMENG_AK: str = ""
    JIMENG_SK: str = ""

    # Video Generation
    KLING_API_KEY: str = ""
    KLING_BASE_URL: str = ""
    SEEDANCE2_API_KEY: str = ""
    SEEDANCE2_BASE_URL: str = ""

    # TTS
    ELEVENLABS_API_KEY: str = ""
    ELEVENLABS_BASE_URL: str = "https://api.elevenlabs.io"

    # OSS Storage
    OSS_ACCESS_KEY_ID: str = ""
    OSS_ACCESS_KEY_SECRET: str = ""
    OSS_BUCKET: str = ""
    OSS_ENDPOINT: str = ""
    OSS_CDN_DOMAIN: str = ""

    # Feature Flags
    MULTIMODAL_MODE: bool = False

    # Task Settings
    MAX_CONCURRENT_TASKS_PER_PROJECT: int = 5
    MAX_TASK_RETRIES: int = 3


settings = Settings()
