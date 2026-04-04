from fastapi import APIRouter, Depends, HTTPException, status, Request
from typing import List, Optional
import asyncpg

from app.database import get_db
from app.dependencies import get_current_user, require_admin, require_admin_or_hod
from app.schemas.profiles import ProfileCreate, ProfileUpdate, ProfileOut, ProfileAdminUpdate, DepartmentOut
from app.services.activity import log_activity

router = APIRouter(prefix="/profiles", tags=["Profiles"])
@router.get("/departments", response_model=List[DepartmentOut])
async def list_departments(
    db: asyncpg.Connection = Depends(get_db),
):
    rows = await db.fetch(
        "SELECT id, name, code FROM public.departments ORDER BY name"
    )
    return [dict(r) for r in rows]

@router.get("/me", response_model=ProfileOut)
async def get_my_profile(current_user: dict = Depends(get_current_user)):
    return current_user


@router.put("/me", response_model=ProfileOut)
async def update_my_profile(
    body: ProfileUpdate,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_db),
):
    updates = body.model_dump(exclude_none=True)

    if current_user.get("role") == "teacher":
        updates.pop("usn", None)
    # 3. For students: Convert empty strings to None to prevent UniqueViolation
    elif "usn" in updates and updates["usn"].strip() == "":
        updates["usn"] = None

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    set_clause = ", ".join(
        f"{k} = ${i + 2}" for i, k in enumerate(updates.keys())
    )
    values = list(updates.values())
    try:
        row = await db.fetchrow(
            f"""
            UPDATE public.profiles
            SET {set_clause}, updated_at = now()
            WHERE id = $1 AND is_deleted = false
            RETURNING *
            """,
            current_user["id"], *values,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Profile not found")

        await log_activity(db, str(current_user["id"]), "update_profile",
                            request.client.host if request.client else None)
        return dict(row)
    
    except asyncpg.exceptions.UniqueViolationError:
        raise HTTPException(
            status_code=400, 
            detail="The USN provided is already registered to another user."
        )

# ---- Admin endpoints ----
@router.get("", response_model=List[ProfileOut])
async def list_profiles(
    role: Optional[str] = None,
    branch: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    current_user: dict = Depends(require_admin_or_hod),
    db: asyncpg.Connection = Depends(get_db),
):
    where_parts = ["is_deleted = false"]
    params = []
    idx = 1

    # 🔒 HOD restriction
    if current_user["role"] == "hod":
        where_parts.append(f"branch = ${idx}")
        params.append(current_user["branch"])
        idx += 1

    # Filters
    if role:
        where_parts.append(f"role = ${idx}")
        params.append(role)
        idx += 1

    if branch:
        where_parts.append(f"branch = ${idx}")
        params.append(branch)
        idx += 1

    where = " AND ".join(where_parts)

    rows = await db.fetch(
        f"""
        SELECT * FROM public.profiles
        WHERE {where}
        ORDER BY full_name
        LIMIT ${idx} OFFSET ${idx+1}
        """,
        *params, limit, skip,
    )

    return [dict(r) for r in rows]

@router.get("/{user_id}", response_model=ProfileOut)
async def get_profile(
    user_id: str,
    _: dict = Depends(require_admin_or_hod),
    db: asyncpg.Connection = Depends(get_db),
):
    row = await db.fetchrow(
        "SELECT * FROM public.profiles WHERE id = $1 AND is_deleted = false", user_id
    )
    if not row:
        raise HTTPException(status_code=404, detail="Profile not found")
    return dict(row)


@router.put("/{user_id}", response_model=ProfileOut)
async def admin_update_profile(
    user_id: str,
    body: ProfileAdminUpdate,
    admin: dict = Depends(require_admin),
    db: asyncpg.Connection = Depends(get_db),
):
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    set_clause = ", ".join(f"{k} = ${i + 2}" for i, k in enumerate(updates.keys()))
    values = list(updates.values())

    row = await db.fetchrow(
        f"UPDATE public.profiles SET {set_clause}, updated_at = now() WHERE id = $1 AND is_deleted = false RETURNING *",
        user_id, *values,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Profile not found")

    await log_activity(db, str(admin["id"]), "admin_update_profile", {"target": user_id})
    return dict(row)


@router.delete("/{user_id}", status_code=204)
async def soft_delete_profile(
    user_id: str,
    admin: dict = Depends(require_admin),
    db: asyncpg.Connection = Depends(get_db),
):
    result = await db.execute(
        "UPDATE public.profiles SET is_deleted = true, is_active = false, updated_at = now() WHERE id = $1",
        user_id,
    )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Profile not found")
    await log_activity(db, str(admin["id"]), "delete_profile", {"target": user_id})

