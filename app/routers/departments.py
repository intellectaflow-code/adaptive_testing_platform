from fastapi import APIRouter, Depends
import asyncpg

from app.database import get_db

router = APIRouter(prefix="/departments", tags=["Departments"])


@router.get("")
async def get_departments(db: asyncpg.Connection = Depends(get_db)):
    rows = await db.fetch("""
        SELECT id, name, code
        FROM departments
        ORDER BY name
    """)
    return [dict(r) for r in rows]