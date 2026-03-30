from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
import asyncpg

from app.database import get_db
from app.dependencies import require_admin, require_admin_or_hod
from app.services.supabase_client import get_supabase

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
    current_user: dict = Depends(require_admin_or_hod),
    db: asyncpg.Connection = Depends(get_db),
):
    enrolled = 0
    skipped = 0

    async with db.transaction():

        # 🔥 Get course branch
        course = await db.fetchrow(
            "SELECT branch FROM public.courses WHERE id = $1",
            course_id
        )
        if not course:
            raise HTTPException(404, "Course not found")

        # 🔥 If HOD → restrict by branch
        if current_user["role"] == "hod":
            if course["branch"] != current_user["branch"]:
                raise HTTPException(403, "You can only manage your branch")

        for sid in student_ids:
            try:
                # 🔥 Check student branch (only for HOD)
                if current_user["role"] == "hod":
                    student = await db.fetchrow(
                        "SELECT branch FROM public.profiles WHERE id = $1",
                        sid
                    )
                    if not student or student["branch"] != current_user["branch"]:
                        skipped += 1
                        continue

                await db.execute(
                    """
                    INSERT INTO public.enrollments (course_id, student_id)
                    VALUES ($1, $2)
                    ON CONFLICT DO NOTHING
                    """,
                    course_id, sid
                )
                enrolled += 1
            except Exception:
                skipped += 1

    return {"enrolled": enrolled, "skipped": skipped}


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

@router.post("/bulk-create-students")
async def bulk_create_students(
    students: List[dict],
    db: asyncpg.Connection = Depends(get_db),
):
    async with db.transaction():
        for s in students:
            await db.execute(
                """
                INSERT INTO profiles (id, email, full_name, role, branch, usn, section)
                VALUES (gen_random_uuid(), $1, $2, 'student', $3, $4, $5)
                ON CONFLICT DO NOTHING
                """,
                s["email"], s["full_name"], s["branch"], s["usn"], s["section"]
            )
    return {"message": "Students uploaded"}

@router.post("/assign-teacher")
async def assign_teacher(
    course_id: str,
    teacher_id: str,
    current_user: dict = Depends(require_admin_or_hod),
    db: asyncpg.Connection = Depends(get_db),
):
    # Get course + teacher
    course = await db.fetchrow("SELECT branch FROM courses WHERE id = $1", course_id)
    teacher = await db.fetchrow("SELECT branch FROM profiles WHERE id = $1", teacher_id)

    if not course or not teacher:
        raise HTTPException(404, "Course or teacher not found")

    # 🔥 HOD restriction
    if current_user["role"] == "hod":
        if course["branch"] != current_user["branch"] or teacher["branch"] != current_user["branch"]:
            raise HTTPException(403, "Only your branch allowed")

    await db.execute(
        """
        INSERT INTO course_teachers (course_id, teacher_id)
        VALUES ($1, $2)
        ON CONFLICT DO NOTHING
        """,
        course_id, teacher_id
    )

    return {"message": "Teacher assigned"}

@router.post("/create-teacher")
async def create_teacher(
    body: dict,
    current_user: dict = Depends(require_admin_or_hod),
    db: asyncpg.Connection = Depends(get_db),
):
    # 🔥 HOD can only create in their branch
    branch = body.get("branch")

    if current_user["role"] == "hod":
        branch = current_user["branch"]

    # create auth user (if using supabase)
    supabase = get_supabase()

    res = supabase.auth.admin.create_user({
        "email": body["email"],
        "password": body["password"],
        "email_confirm": True,
    })

    user = res.user

    await db.execute(
        """
        INSERT INTO public.profiles (id, email, full_name, role, branch)
        VALUES ($1, $2, $3, 'teacher', $4)
        """,
        user.id,
        body["email"],
        body.get("full_name"),
        branch,
    )

    return {"message": "Teacher created"}