from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List
import asyncpg

from app.database import get_db
from app.dependencies import get_current_user
from app.schemas.messaging import MessageCreate, MessageOut

router = APIRouter(prefix="/messages", tags=["Messages"])


@router.post("", response_model=MessageOut, status_code=201)
async def send_message(
    body: MessageCreate,
    current_user: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_db),
):
    # Verify receiver exists
    receiver = await db.fetchrow(
        "SELECT id FROM public.profiles WHERE id = $1 AND is_deleted = false AND is_active = true",
        str(body.receiver_id),
    )
    if not receiver:
        raise HTTPException(status_code=404, detail="Receiver not found")

    row = await db.fetchrow(
        "INSERT INTO public.messages (sender_id, receiver_id, message) VALUES ($1,$2,$3) RETURNING *",
        str(current_user["id"]), str(body.receiver_id), body.message,
    )
    return dict(row)


@router.get("/inbox", response_model=List[MessageOut])
async def inbox(
    skip: int = 0,
    limit: int = 50,
    current_user: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_db),
):
    rows = await db.fetch(
        "SELECT * FROM public.messages WHERE receiver_id = $1 ORDER BY created_at DESC LIMIT $2 OFFSET $3",
        str(current_user["id"]), limit, skip,
    )
    return [dict(r) for r in rows]


@router.get("/sent", response_model=List[MessageOut])
async def sent(
    skip: int = 0,
    limit: int = 50,
    current_user: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_db),
):
    rows = await db.fetch(
        "SELECT * FROM public.messages WHERE sender_id = $1 ORDER BY created_at DESC LIMIT $2 OFFSET $3",
        str(current_user["id"]), limit, skip,
    )
    return [dict(r) for r in rows]


@router.get("/conversation/{user_id}", response_model=List[MessageOut])
async def conversation(
    user_id: str,
    skip: int = 0,
    limit: int = 100,
    current_user: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_db),
):
    me = str(current_user["id"])
    rows = await db.fetch(
        """
        SELECT * FROM public.messages
        WHERE (sender_id = $1 AND receiver_id = $2) OR (sender_id = $2 AND receiver_id = $1)
        ORDER BY created_at ASC
        LIMIT $3 OFFSET $4
        """,
        me, user_id, limit, skip,
    )
    return [dict(r) for r in rows]


@router.post("/{message_id}/read", response_model=MessageOut)
async def mark_read(
    message_id: str,
    current_user: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_db),
):
    row = await db.fetchrow(
        "UPDATE public.messages SET is_read = true WHERE id = $1 AND receiver_id = $2 RETURNING *",
        message_id, str(current_user["id"]),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Message not found")
    return dict(row)


@router.get("/unread/count")
async def unread_count(
    current_user: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_db),
):
    count = await db.fetchval(
        "SELECT COUNT(*) FROM public.messages WHERE receiver_id = $1 AND is_read = false",
        str(current_user["id"]),
    )
    return {"unread_count": count}

