import asyncpg
import logging
from typing import Optional
from app.config import get_settings

logger = logging.getLogger("quiz.db")

_pool: Optional[asyncpg.Pool] = None


async def create_pool() -> asyncpg.Pool:
    settings = get_settings()
    logger.info("Connecting to database...")
    try:
        pool = await asyncpg.create_pool(
            dsn=settings.database_url,
            min_size=2,          # small for dev
            max_size=5,          # small for dev
            command_timeout=30,
            statement_cache_size=0,
            server_settings={"application_name": "quiz_platform_dev"},
        )
        # Quick health check
        async with pool.acquire() as conn:
            version = await conn.fetchval("SELECT version()")
            logger.info("✅ DB connected: %s", version[:40])
        return pool
    except Exception as e:
        logger.error("❌ DB connection failed: %s", e)
        logger.error("   Check DATABASE_URL in your .env file")
        raise


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await create_pool()
    return _pool


async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("DB pool closed.")


async def get_db() -> asyncpg.Connection:
    """FastAPI dependency – yields a connection from the pool."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn

