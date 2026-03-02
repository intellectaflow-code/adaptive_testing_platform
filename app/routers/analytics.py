from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
import asyncpg

from app.database import get_db
from app.dependencies import get_current_user, require_teacher_up, require_student
from app.schemas.analytics import (
    QuestionAnalyticsOut, StudentPerformanceOut,
    AIGeneratedQuestionCreate, AIGeneratedQuestionOut,
)

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get("/questions/{question_id}", response_model=List[QuestionAnalyticsOut])
async def question_analytics(
    question_id: str,
    _: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    rows = await db.fetch(
        "SELECT * FROM public.question_analytics WHERE question_id = $1 ORDER BY updated_at DESC",
        question_id,
    )
    return [dict(r) for r in rows]


@router.get("/quiz/{quiz_id}/questions", response_model=List[QuestionAnalyticsOut])
async def quiz_question_analytics(
    quiz_id: str,
    _: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    rows = await db.fetch(
        "SELECT * FROM public.question_analytics WHERE quiz_id = $1 ORDER BY difficulty_index",
        quiz_id,
    )
    return [dict(r) for r in rows]


@router.get("/quiz/{quiz_id}/summary")
async def quiz_summary(
    quiz_id: str,
    current_user: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    """Aggregate stats for a quiz."""
    row = await db.fetchrow(
        """
        SELECT
          COUNT(DISTINCT a.student_id)            AS unique_students,
          COUNT(*)                                  AS total_attempts,
          AVG(a.total_score)                        AS avg_score,
          MAX(a.total_score)                        AS max_score,
          MIN(a.total_score)                        AS min_score,
          STDDEV(a.total_score)                     AS stddev_score,
          AVG(a.time_spent_seconds)                 AS avg_time_seconds,
          SUM(CASE WHEN a.cheating_flag THEN 1 ELSE 0 END) AS cheating_flags,
          COUNT(*) FILTER (WHERE a.status = 'submitted')  AS submitted_count,
          COUNT(*) FILTER (WHERE a.status = 'evaluated')  AS evaluated_count
        FROM public.quiz_attempts a
        WHERE a.quiz_id = $1
        """,
        quiz_id,
    )
    quiz = await db.fetchrow(
        "SELECT title, passing_marks, total_marks FROM public.quizzes WHERE id = $1", quiz_id
    )
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")

    stats = dict(row)
    # Pass rate
    if quiz["passing_marks"] and stats["total_attempts"]:
        pass_count = await db.fetchval(
            "SELECT COUNT(*) FROM public.quiz_attempts WHERE quiz_id = $1 AND total_score >= $2",
            quiz_id, quiz["passing_marks"],
        )
        stats["pass_rate"] = round(pass_count / stats["total_attempts"] * 100, 2)
    else:
        stats["pass_rate"] = None

    stats["quiz_title"] = quiz["title"]
    stats["passing_marks"] = quiz["passing_marks"]
    stats["total_marks"] = quiz["total_marks"]
    return stats


@router.get("/student/{student_id}/performance", response_model=List[StudentPerformanceOut])
async def student_performance(
    student_id: str,
    current_user: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_db),
):
    if current_user["role"] == "student" and str(current_user["id"]) != student_id:
        raise HTTPException(status_code=403, detail="Cannot view another student's performance")

    rows = await db.fetch(
        "SELECT * FROM public.student_performance_summary WHERE student_id = $1 ORDER BY last_updated DESC",
        student_id,
    )
    return [dict(r) for r in rows]


@router.get("/course/{course_id}/leaderboard")
async def course_leaderboard(
    course_id: str,
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_db),
):
    rows = await db.fetch(
        """
        SELECT
            p.full_name, p.usn,
            sps.quizzes_taken, sps.average_score,
            sps.highest_score, sps.lowest_score
        FROM public.student_performance_summary sps
        JOIN public.profiles p ON p.id = sps.student_id
        WHERE sps.course_id = $1
        ORDER BY sps.average_score DESC NULLS LAST
        LIMIT $2
        """,
        course_id, limit,
    )
    return [dict(r) for r in rows]


@router.get("/course/{course_id}/overview")
async def course_analytics_overview(
    course_id: str,
    current_user: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    """High level course analytics."""
    quizzes = await db.fetchval(
        "SELECT COUNT(*) FROM public.quizzes WHERE course_id = $1 AND is_deleted = false", course_id
    )
    students = await db.fetchval(
        "SELECT COUNT(*) FROM public.enrollments WHERE course_id = $1", course_id
    )
    attempts = await db.fetchval(
        """
        SELECT COUNT(*) FROM public.quiz_attempts a
        JOIN public.quizzes q ON q.id = a.quiz_id
        WHERE q.course_id = $1
        """,
        course_id,
    )
    avg_score = await db.fetchval(
        """
        SELECT AVG(a.total_score) FROM public.quiz_attempts a
        JOIN public.quizzes q ON q.id = a.quiz_id
        WHERE q.course_id = $1 AND a.status IN ('submitted','evaluated')
        """,
        course_id,
    )
    return {
        "total_quizzes": quizzes,
        "total_students": students,
        "total_attempts": attempts,
        "average_score": round(float(avg_score), 2) if avg_score else None,
    }


# ---- AI Generated Questions ----

@router.post("/ai-questions", response_model=AIGeneratedQuestionOut, status_code=201)
async def create_ai_question(
    body: AIGeneratedQuestionCreate,
    current_user: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    row = await db.fetchrow(
        """
        INSERT INTO public.ai_generated_questions
          (course_id, generated_text, syllabus_reference, difficulty)
        VALUES ($1,$2,$3,$4) RETURNING *
        """,
        str(body.course_id), body.generated_text,
        body.syllabus_reference, body.difficulty,
    )
    return dict(row)


@router.get("/ai-questions", response_model=List[AIGeneratedQuestionOut])
async def list_ai_questions(
    course_id: Optional[str] = Query(None),
    approved: Optional[bool] = Query(None),
    skip: int = 0,
    limit: int = 50,
    _: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    where_parts = ["1=1"]
    params: list = []
    idx = 1
    if course_id:
        where_parts.append(f"course_id = ${idx}"); params.append(course_id); idx += 1
    if approved is not None:
        where_parts.append(f"approved = ${idx}"); params.append(approved); idx += 1

    where = " AND ".join(where_parts)
    rows = await db.fetch(
        f"SELECT * FROM public.ai_generated_questions WHERE {where} ORDER BY created_at DESC LIMIT ${idx} OFFSET ${idx+1}",
        *params, limit, skip,
    )
    return [dict(r) for r in rows]


@router.post("/ai-questions/{ai_q_id}/approve", response_model=AIGeneratedQuestionOut)
async def approve_ai_question(
    ai_q_id: str,
    current_user: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    row = await db.fetchrow(
        "UPDATE public.ai_generated_questions SET approved = true, approved_by = $2 WHERE id = $1 RETURNING *",
        ai_q_id, str(current_user["id"]),
    )
    if not row:
        raise HTTPException(status_code=404, detail="AI question not found")
    return dict(row)

