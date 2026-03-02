import asyncpg
import json
import logging
from typing import Optional

logger = logging.getLogger("quiz.activity")


async def log_activity(
    db: asyncpg.Connection,
    user_id: str,
    action: str,
    metadata: Optional[dict] = None,
    ip_address: Optional[str] = None,
):
    """Write an activity log row. Never raises – logging must not break requests."""
    try:
        await db.execute(
            """
            INSERT INTO public.activity_logs (user_id, action, metadata, ip_address)
            VALUES ($1, $2, $3, $4)
            """,
            user_id,
            action,
            json.dumps(metadata) if metadata else None,
            ip_address,
        )
        logger.debug("activity | user=%s action=%s", user_id, action)
    except Exception as e:
        logger.warning("activity log failed (non-fatal): %s", e)

