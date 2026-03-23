from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import List, Optional


class Settings(BaseSettings):
    # ── Supabase ──────────────────────────────────
    supabase_url: str = "https://ewnmflcmgzazuylkyhjf.supabase.co"
    supabase_jwt_secret: str = ""
    database_url: str = ""
    supabase_service_role_key: str = ""
    GROQ_API_KEY:str = ""   

    google_project_id: Optional[str] = None
    google_bucket_name: Optional[str] = None
    google_location: Optional[str] = None

    # ── App ───────────────────────────────────────
    app_env: str = "development"
    debug: bool = True
    secret_key: str = "dev-secret-key"
    allowed_origins: str = "*"

    @property
    def is_dev(self) -> bool:
        return self.app_env == "development"

    @property
    def cors_origins(self) -> List[str]:
        if self.allowed_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.allowed_origins.split(",")]

    class Config:
        env_file = ".env"
        case_sensitive = False
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()