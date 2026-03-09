
from fastapi import APIRouter, Depends, Query
from typing import List, Optional
import asyncpg
from app.database import get_db
from app.dependencies import require_admin, require_teacher_up

router = APIRouter(prefix="/teacher", tags=["Teacher"])


@router.get("/dashboard")
async def teacher_dashboard(
    current_user: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    teacher_id = str(current_user["id"])

    # 1. Total courses assigned to OR created by this teacher
    total_courses = await db.fetchval(
        """
        SELECT COUNT(DISTINCT c.id) 
        FROM public.courses c
        LEFT JOIN public.course_teachers ct ON ct.course_id = c.id
        WHERE (c.created_by = $1 OR ct.teacher_id = $1) 
        AND c.is_deleted = false
        """,
        teacher_id
    )

    # 2. Total unique students enrolled in this teacher's courses
    total_students = await db.fetchval(
        """
        SELECT COUNT(DISTINCT e.student_id)
        FROM public.enrollments e
        JOIN public.courses c ON c.id = e.course_id
        LEFT JOIN public.course_teachers ct ON ct.course_id = c.id
        WHERE (c.created_by = $1 OR ct.teacher_id = $1)
        AND c.is_deleted = false
        """,
        teacher_id
    )

    # 3. Total quizzes created by this teacher
    total_quizzes = await db.fetchval(
        "SELECT COUNT(*) FROM public.quizzes WHERE created_by = $1 AND is_deleted = false",
        teacher_id
    )

    # 4. Cheating flags in this teacher's quizzes
    cheating_flags = await db.fetchval(
        """
        SELECT COUNT(*) 
        FROM public.quiz_attempts a
        JOIN public.quizzes q ON q.id = a.quiz_id
        WHERE q.created_by = $1 AND a.cheating_flag = true
        """,
        teacher_id
    )

    # 5. Recent attempts for this teacher's quizzes
    recent_activity = await db.fetch(
        """
        SELECT p.full_name, q.title as quiz_title, a.total_score, a.submitted_at
        FROM public.quiz_attempts a
        JOIN public.profiles p ON p.id = a.student_id
        JOIN public.quizzes q ON q.id = a.quiz_id
        WHERE q.created_by = $1
        ORDER BY a.submitted_at DESC
        LIMIT 5
        """,
        teacher_id
    )

    return {
        "courses": total_courses,
        "students": total_students,
        "quizzes": total_quizzes,
        "cheating_flags": cheating_flags,
        "recent_activity": [dict(r) for r in recent_activity]
    }

@router.get("/my-students")
async def get_teacher_students(
    branch: Optional[str] = None,
    current_user: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    teacher_id = str(current_user["id"])
    
    # Query: Get students through the enrollment -> course -> teacher link
    query = """
        SELECT DISTINCT p.id, p.full_name, p.usn, p.branch, p.section, p.role
        FROM public.profiles p
        JOIN public.enrollments e ON e.student_id = p.id
        JOIN public.courses c ON c.id = e.course_id
        LEFT JOIN public.course_teachers ct ON ct.course_id = c.id
        WHERE (c.created_by = $1 OR ct.teacher_id = $1)
        AND p.role = 'student'
        AND p.is_deleted = false
    """
    
    params = [teacher_id]
    if branch:
        query += " AND p.branch = $2"
        params.append(branch)

    rows = await db.fetch(query, *params)
    return [dict(r) for r in rows]