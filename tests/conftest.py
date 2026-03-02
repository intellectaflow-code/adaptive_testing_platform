"""
conftest.py – shared pytest fixtures for the quiz platform API.

Run tests:
    pytest tests/ -v
"""
import asyncio
import pytest
import asyncpg
import os
from httpx import AsyncClient, ASGITransport
from dotenv import load_dotenv

load_dotenv()

# ── Override settings for tests ───────────────────────────────────────────────
os.environ.setdefault("APP_ENV", "testing")
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
os.environ.setdefault("DATABASE_URL", os.getenv("DATABASE_URL", ""))

from app.main import app
from app.config import get_settings


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def client():
    """Async HTTP client that talks directly to the ASGI app (no network)."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        yield c


# ── Helpers ───────────────────────────────────────────────────────────────────

def auth_header(token: str) -> dict:
    """Build an Authorization header dict."""
    return {"Authorization": f"Bearer {token}"}

