from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
import asyncpg

from app.database import get_db
from app.dependencies import get_current_user, require_teacher_up
from app.schemas.messaging import AnnouncementCreate, AnnouncementUpdate, AnnouncementOut

router = APIRouter(prefix="/announcements", tags=["Announcements"])


@router.post("", response_model=AnnouncementOut, status_code=201)
async def create_announcement(
    body: AnnouncementCreate,
    current_user: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    row = await db.fetchrow(
        """
        WITH inserted AS (
            INSERT INTO public.announcements (course_id, created_by, title, message)
            VALUES ($1, $2, $3, $4)
            RETURNING *
        )
        SELECT 
            i.*,
            p.full_name AS teacher_name,
            c.name AS course_name
        FROM inserted i
        LEFT JOIN public.profiles p ON i.created_by = p.id
        LEFT JOIN public.courses c ON i.course_id = c.id
        """,
        str(body.course_id) if body.course_id else None,
        str(current_user["id"]),
        body.title,
        body.message,
    )
    return dict(row)

@router.get("", response_model=List[AnnouncementOut])
async def list_announcements(
    course_id: Optional[str] = Query(None),
    active_only: bool = Query(True),
    skip: int = 0,
    limit: int = 50,
    current_user: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_db),
):
    where_parts = []
    params = []
    
    # 1. Role-Based Visibility Filtering
    if current_user["role"] == "student":
        # Students see: Announcements for their enrolled courses OR Global (NULL)
        where_parts.append(
            f"""(a.course_id IN (
                SELECT course_id FROM public.enrollments WHERE student_id = ${len(params) + 1}
            ) OR a.course_id IS NULL)"""
        )
        params.append(str(current_user["id"]))
    else:
        # Teachers/HODs see: ONLY what they created
        where_parts.append(f"a.created_by = ${len(params) + 1}")
        params.append(str(current_user["id"]))

    # 2. Specific Course Filtering (if requested)
    if course_id:
        where_parts.append(f"a.course_id = ${len(params) + 1}")
        params.append(course_id)

    # 3. Active Status Filtering
    if active_only:
        where_parts.append("a.is_active = true")

    # Construct Query
    where_clause = " WHERE " + " AND ".join(where_parts) if where_parts else ""
    
    # Add Pagination Params
    params.append(limit)
    limit_idx = len(params)
    params.append(skip)
    skip_idx = len(params)

    query = f"""
    SELECT 
        a.*,
        c.name AS course_name,
        p.full_name AS teacher_name
    FROM public.announcements a
    LEFT JOIN public.courses c ON a.course_id = c.id
    LEFT JOIN public.profiles p ON a.created_by = p.id
    {where_clause}
    ORDER BY a.created_at DESC
    LIMIT ${limit_idx} OFFSET ${skip_idx}
    """
    
    rows = await db.fetch(query, *params)
    return [dict(r) for r in rows]

@router.get("/{announcement_id}", response_model=AnnouncementOut)
async def get_announcement(
    announcement_id: str,
    _: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_db),
):
    row = await db.fetchrow(
        """
        SELECT 
            a.*,
            p.full_name AS teacher_name,
            c.name AS course_name
        FROM public.announcements a
        LEFT JOIN public.profiles p ON a.created_by = p.id
        LEFT JOIN public.courses c ON a.course_id = c.id
        WHERE a.id = $1
        """,
        announcement_id
    )
    if not row:
        raise HTTPException(status_code=404, detail="Announcement not found")
    return dict(row)


@router.put("/{announcement_id}", response_model=AnnouncementOut)
async def update_announcement(
    announcement_id: str,
    body: AnnouncementUpdate,
    current_user: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    set_clause = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(updates.keys()))
    row = await db.fetchrow(
        f"""
        WITH updated AS (
            UPDATE public.announcements
            SET {set_clause}
            WHERE id = $1 AND created_by = ${len(updates)+2}
            RETURNING *
        )
        SELECT 
            u.*,
            p.full_name AS teacher_name,
            c.name AS course_name
        FROM updated u
        LEFT JOIN public.profiles p ON u.created_by = p.id
        LEFT JOIN public.courses c ON u.course_id = c.id
        """,
        announcement_id,
        *updates.values(),
        str(current_user["id"]),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Announcement not found or not your announcement")
    return dict(row)


@router.delete("/{announcement_id}", status_code=204)
async def delete_announcement(
    announcement_id: str,
    current_user: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    await db.execute(
        "DELETE FROM public.announcements WHERE id = $1 AND created_by = $2",
        announcement_id, str(current_user["id"]),
    )

