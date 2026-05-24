from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # App
    APP_NAME: str = "Geolvix GIS Ingestion Service"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://user:password@localhost:5432/geolvix"

    # Security — token compartilhado com o Core Service
    INTERNAL_API_TOKEN: str = "change-me-in-production"

    # Limits
    MAX_FILE_SIZE_MB: int = 10
    GEOMETRY_SIMPLIFY_TOLERANCE: float = 0.00001  # graus (~1m na equatorial)

    # CORS — Core Service e Web Frontend
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:8080"]

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
