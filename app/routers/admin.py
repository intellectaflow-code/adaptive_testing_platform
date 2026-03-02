from fastapi import APIRouter, Depends, Query
from typing import List, Optional
import asyncpg

from app.database import get_db
from app.dependencies import require_admin, require_admin_or_hod

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/activity-logs")
async def get_activity_logs(
    user_id: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    skip: int = 0,
    limit: int = 100,
    _: dict = Depends(require_admin),
    db: asyncpg.Connection = Depends(get_db),
):
    where_parts = ["1=1"]
    params: list = []
    idx = 1

    if user_id:
        where_parts.append(f"user_id = ${idx}"); params.append(user_id); idx += 1
    if action:
        where_parts.append(f"action ILIKE ${idx}"); params.append(f"%{action}%"); idx += 1

    where = " AND ".join(where_parts)
    rows = await db.fetch(
        f"SELECT * FROM public.activity_logs WHERE {where} ORDER BY created_at DESC LIMIT ${idx} OFFSET ${idx+1}",
        *params, limit, skip,
    )
    return [dict(r) for r in rows]


@router.get("/dashboard")
async def admin_dashboard(
    _: dict = Depends(require_admin_or_hod),
    db: asyncpg.Connection = Depends(get_db),
):
    """Platform-wide stats."""
    total_students = await db.fetchval(
        "SELECT COUNT(*) FROM public.profiles WHERE role = 'student' AND is_deleted = false"
    )
    total_teachers = await db.fetchval(
        "SELECT COUNT(*) FROM public.profiles WHERE role = 'teacher' AND is_deleted = false"
    )
    total_courses = await db.fetchval(
        "SELECT COUNT(*) FROM public.courses WHERE is_deleted = false"
    )
    total_quizzes = await db.fetchval(
        "SELECT COUNT(*) FROM public.quizzes WHERE is_deleted = false"
    )
    total_attempts = await db.fetchval(
        "SELECT COUNT(*) FROM public.quiz_attempts"
    )
    total_questions = await db.fetchval(
        "SELECT COUNT(*) FROM public.question_bank WHERE is_deleted = false"
    )
    active_quizzes = await db.fetchval(
        """
        SELECT COUNT(*) FROM public.quizzes
        WHERE is_published = true AND is_deleted = false AND is_archived = false
        AND (end_time IS NULL OR end_time > now())
        """
    )
    cheating_flags = await db.fetchval(
        "SELECT COUNT(*) FROM public.quiz_attempts WHERE cheating_flag = true"
    )

    return {
        "students": total_students,
        "teachers": total_teachers,
        "courses": total_courses,
        "quizzes": total_quizzes,
        "active_quizzes": active_quizzes,
        "total_attempts": total_attempts,
        "total_questions": total_questions,
        "cheating_flags": cheating_flags,
    }


@router.get("/cheating-report")
async def cheating_report(
    quiz_id: Optional[str] = Query(None),
    _: dict = Depends(require_admin_or_hod),
    db: asyncpg.Connection = Depends(get_db),
):
    where = "a.cheating_flag = true"
    params: list = []
    if quiz_id:
        where += " AND a.quiz_id = $1"
        params.append(quiz_id)

    rows = await db.fetch(
        f"""
        SELECT
            p.full_name, p.usn,
            q.title as quiz_title,
            a.tab_switch_count, a.full_screen_violations,
            a.total_score, a.submitted_at, a.id as attempt_id
        FROM public.quiz_attempts a
        JOIN public.profiles p ON p.id = a.student_id
        JOIN public.quizzes q ON q.id = a.quiz_id
        WHERE {where}
        ORDER BY a.submitted_at DESC
        """,
        *params,
    )
    return [dict(r) for r in rows]


@router.post("/bulk-enroll")
async def bulk_enroll(
    course_id: str,
    student_ids: List[str],
    _: dict = Depends(require_admin_or_hod),
    db: asyncpg.Connection = Depends(get_db),
):
    """Enroll multiple students at once."""
    enrolled = 0
    skipped = 0
    async with db.transaction():
        for sid in student_ids:
            try:
                await db.execute(
                    "INSERT INTO public.enrollments (course_id, student_id) VALUES ($1, $2)",
                    course_id, sid,
                )
                enrolled += 1
            except Exception:
                skipped += 1
    return {"enrolled": enrolled, "skipped_duplicates": skipped}


@router.get("/students/{student_id}/full-report")
async def student_full_report(
    student_id: str,
    _: dict = Depends(require_admin_or_hod),
    db: asyncpg.Connection = Depends(get_db),
):
    """Full student academic report."""
    profile = await db.fetchrow(
        "SELECT id, full_name, usn, branch, section FROM public.profiles WHERE id = $1 AND is_deleted = false",
        student_id,
    )
    if not profile:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Student not found")

    enrollments = await db.fetch(
        """
        SELECT c.name as course_name, c.code, c.semester, c.branch, e.enrolled_at
        FROM public.enrollments e
        JOIN public.courses c ON c.id = e.course_id
        WHERE e.student_id = $1 AND c.is_deleted = false
        """,
        student_id,
    )

    performance = await db.fetch(
        """
        SELECT c.name as course_name, sps.*
        FROM public.student_performance_summary sps
        JOIN public.courses c ON c.id = sps.course_id
        WHERE sps.student_id = $1
        ORDER BY sps.average_score DESC
        """,
        student_id,
    )

    attempts = await db.fetch(
        """
        SELECT q.title as quiz_title, a.attempt_number, a.total_score,
               a.status, a.submitted_at, a.cheating_flag, a.tab_switch_count
        FROM public.quiz_attempts a
        JOIN public.quizzes q ON q.id = a.quiz_id
        WHERE a.student_id = $1
        ORDER BY a.submitted_at DESC
        LIMIT 50
        """,
        student_id,
    )

    return {
        "profile": dict(profile),
        "enrollments": [dict(r) for r in enrollments],
        "performance_summary": [dict(r) for r in performance],
        "recent_attempts": [dict(r) for r in attempts],
    }

