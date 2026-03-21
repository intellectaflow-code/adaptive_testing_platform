from fastapi import APIRouter, Depends, HTTPException
import asyncpg

from app.database import get_db
from app.dependencies import get_current_user
from app.schemas.settings import SettingsOut, SettingsUpdate

router = APIRouter(prefix="/settings", tags=["Settings"])


@router.get("/me", response_model=SettingsOut)
async def get_settings(
    current_user: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_db),
):
    row = await db.fetchrow(
        "SELECT * FROM public.user_settings WHERE user_id = $1",
        current_user["id"],
    )
    if not row:
        # Auto-create with defaults on first access
        row = await db.fetchrow(
            """
            INSERT INTO public.user_settings (user_id)
            VALUES ($1)
            RETURNING *
            """,
            current_user["id"],
        )
    return dict(row)


@router.put("/me", response_model=SettingsOut)
async def update_settings(
    body: SettingsUpdate,
    current_user: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_db),
):
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    set_clause = ", ".join(
        f"{k} = ${i + 2}" for i, k in enumerate(updates.keys())
    )
    values = list(updates.values())

    row = await db.fetchrow(
        f"""
        INSERT INTO public.user_settings (user_id)
        VALUES ($1)
        ON CONFLICT (user_id) DO UPDATE
        SET {set_clause}, updated_at = now()
        RETURNING *
        """,
        current_user["id"], *values,
    )
    return dict(row)