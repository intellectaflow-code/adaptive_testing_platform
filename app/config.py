from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import List


class Settings(BaseSettings):
    # ── Supabase ──────────────────────────────────
    supabase_url: str = "https://ewnmflcmgzazuylkyhjf.supabase.co"
    supabase_jwt_secret: str = "6fd2db10-f4c7-476b-b127-c2d81a51c32b"
    database_url: str = "postgresql://postgres.ewnmflcmgzazuylkyhjf:C77Cd7z%21XMJe%2FJp@aws-1-ap-south-1.pooler.supabase.com:6543/postgres"
    supabase_service_role_key: str = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImV3bm1mbGNtZ3phenV5bGt5aGpmIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MjE2MzMyNSwiZXhwIjoyMDg3NzM5MzI1fQ.vIeEdFxxnusAlOAHHB0A-bri0Khcywjsjqt2xWscsog"

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