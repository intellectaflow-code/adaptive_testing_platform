from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
import asyncpg
from uuid import UUID
from datetime import date, datetime, time, timezone

from app.database import get_db
from app.dependencies import get_current_user, require_teacher_up, require_student
from app.schemas.analytics import (
    StudentPerformanceOut, LeaderboardEntry

)

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get("/student/dashboard")
async def student_dashboard(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    current_user: dict = Depends(require_student),
    db: asyncpg.Connection = Depends(get_db),
):
    student_id = str(current_user["id"])

    params = [student_id]
    param_idx = 2

    date_filter_attempt = ""
    date_filter_trend = ""

    # ✅ Ensure we cover the full day for the end date
    if start_date:
        start_dt = datetime.combine(start_date, time.min)  # 00:00:00
        date_filter_attempt += f" AND attempt_date >= ${param_idx}"
        date_filter_trend  += f" AND submitted_at >= ${param_idx}"
        params.append(start_dt)
        param_idx += 1

    if end_date:
        end_dt = datetime.combine(end_date, time.max)  # 23:59:59.999999
        date_filter_attempt += f" AND attempt_date <= ${param_idx}"
        date_filter_trend  += f" AND submitted_at <= ${param_idx}"
        params.append(end_dt)
        param_idx += 1

    stats = await db.fetchrow(f"""
        SELECT 
            COUNT(*) as tests_taken,
            COALESCE(AVG(score), 0) as avg_score,
            COALESCE(MAX(score), 0) as best_score
        FROM student_attempts_view
        WHERE student_id = $1 {date_filter_attempt}
    """, *params)

    subjects = await db.fetch(f"""
        SELECT subject,
            COUNT(*) as tests_taken,
            AVG(score) as avg_score
        FROM student_attempts_view
        WHERE student_id = $1 {date_filter_attempt}
        GROUP BY subject
    """, *params)

    trend = await db.fetch(f"""
        SELECT quiz, total_score, submitted_at
        FROM student_score_trend
        WHERE student_id = $1 {date_filter_trend}
        ORDER BY submitted_at DESC
    """, *params)
    date_filter_attempt_qa = date_filter_attempt.replace("attempt_date", "qa.submitted_at")
    attempts = await db.fetch(f"""
        SELECT 
            qa.id AS attempt_id,
            q.title AS test_title,
            c.name AS subject,
            qa.time_spent_seconds,
            qa.submitted_at AS attempt_date,
            'teacher' AS type,
            COUNT(sa.question_id) AS total_questions,
            COUNT(CASE WHEN sa.is_correct THEN 1 END) AS correct_answers
        FROM quiz_attempts qa
        JOIN quizzes q ON q.id = qa.quiz_id
        JOIN courses c ON c.id = q.course_id
        LEFT JOIN student_answers sa ON sa.attempt_id = qa.id
        WHERE qa.student_id = $1 
        {date_filter_attempt_qa}
        GROUP BY qa.id, q.title, c.name, qa.time_spent_seconds, qa.submitted_at
        ORDER BY qa.submitted_at DESC
    """, *params)

        # ✅ Process attempts FIRST
    formatted_attempts = []

    for a in attempts:
            correct = a["correct_answers"] or 0
            total = a["total_questions"] or 0

            accuracy = round((correct / total) * 100) if total > 0 else 0

            formatted_attempts.append({
                "attempt_id": a["attempt_id"],
                "test_title": a["test_title"],
                "subject": a["subject"],
                "type": a["type"],
                "attempt_date": a["attempt_date"],
                "time_spent_seconds": a["time_spent_seconds"],
                "correct": correct,
                "total_questions": total,
                "accuracy": accuracy
            })

    rank_row = await db.fetchrow("""
        SELECT ranked.rank
        FROM (
            SELECT student_id,
                RANK() OVER (ORDER BY AVG(score) DESC) AS rank
            FROM student_attempts_view
            GROUP BY student_id
        ) ranked
        WHERE ranked.student_id = $1
    """, student_id)

    # ── Streak: count consecutive days (up to today) with at least one attempt ──
    streak_row = await db.fetchrow("""
        WITH daily AS (
            SELECT DISTINCT DATE(attempt_date) AS day
            FROM student_attempts_view
            WHERE student_id = $1
        ),
        numbered AS (
            SELECT day,
                ROW_NUMBER() OVER (ORDER BY day DESC) AS rn
            FROM daily
        ),
        streaks AS (
            SELECT day, rn,
                (day + (rn || ' days')::interval)::date AS grp
            FROM numbered
        )
        SELECT COUNT(*) AS streak
        FROM streaks
        WHERE grp = (
            SELECT (day + (rn || ' days')::interval)::date
            FROM streaks
            WHERE day = (SELECT MAX(day) FROM daily)
            LIMIT 1
        )
    """, student_id)

    # ✅ THEN return
    return {
        "stats": {
            **(dict(stats) if stats else {"tests_taken": 0, "avg_score": 0, "best_score": 0}),
            "rank":   int(rank_row["rank"])   if rank_row   else None,
            "streak": int(streak_row["streak"]) if streak_row else 0,
        },
        "subjects":  [dict(r) for r in subjects]  if subjects  else [],
        "trend":     [dict(r) for r in trend]      if trend      else [],
        "attempts":  formatted_attempts,
    }


@router.get("/attempt/{attempt_id}")
async def get_attempt_details(
    attempt_id: UUID,
    current_user: dict = Depends(require_student),
    db: asyncpg.Connection = Depends(get_db),
):
    student_id = str(current_user["id"])

    # =========================
    # 1. FETCH ATTEMPT SUMMARY
    # =========================
    attempt = await db.fetchrow("""
        SELECT qa.id, qa.total_score, qa.time_spent_seconds, qa.tab_switch_count,
               q.title, c.name AS subject
        FROM quiz_attempts qa
        JOIN quizzes q ON q.id = qa.quiz_id
        JOIN courses c ON c.id = q.course_id
        WHERE qa.id = $1 AND qa.student_id = $2
    """, str(attempt_id), student_id)

    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")

    # =========================
    # 2. FETCH QUESTIONS + ANSWERS
    # =========================
    rows = await db.fetch("""
        SELECT 
            qb.id AS question_id,
            qb.question_text,
            qb.explanation,

            qo.id AS option_id,
            qo.option_text,
            qo.is_correct,

            sa.selected_option_id,
            sa.is_correct AS user_correct

        FROM student_answers sa
        JOIN question_bank qb ON qb.id = sa.question_id
        JOIN question_options qo ON qo.question_id = qb.id

        WHERE sa.attempt_id = $1
        ORDER BY qb.id
    """, str(attempt_id))

    # =========================
    # 3. TRANSFORM DATA
    # =========================
    questions_map = {}

    for r in rows:
        qid = str(r["question_id"])

        if qid not in questions_map:
            questions_map[qid] = {
                "question_text": r["question_text"],
                "correct_answer": None,
                "selected_answer": str(r["selected_option_id"]) if r["selected_option_id"] else None,
                "is_correct": r["user_correct"],
                "explanation": r["explanation"],
                "options": []
            }

        # identify correct option
        if r["is_correct"]:
            questions_map[qid]["correct_answer"] = str(r["option_id"])

        questions_map[qid]["options"].append({
            "id": str(r["option_id"]),
            "option_text": r["option_text"]
        })

    questions = list(questions_map.values())

    # =========================
    # 4. RETURN FINAL RESPONSE
    # =========================
    return {
        "score": float(attempt["total_score"] or 0),
        "time_spent_seconds": attempt["time_spent_seconds"] or 0,
        "tabs": attempt["tab_switch_count"] or 0,
        "config": {
            "title": attempt["title"],
            "subject": attempt["subject"],
            "type": "teacher"
        },
        "questions": questions,
        "correct": sum(1 for q in questions if q["is_correct"]),
        "total": len(questions),
    }

@router.get("/leaderboard", response_model=List[LeaderboardEntry])
async def get_leaderboard(
    course_id: UUID,
    current_user: dict = Depends(require_student),
    db: asyncpg.Connection = Depends(get_db),
):
    user_id = current_user["id"]

    rows = await db.fetch("""
        SELECT student_id, full_name, avg_score, rank
        FROM public.course_leaderboard_view
        WHERE course_id = $1
        ORDER BY rank ASC
    """, course_id)

    result = []

    for r in rows:
        name = r["full_name"] or ""

        initials = "".join([n[0].upper() for n in name.split()[:2]]) if name else "?"

        result.append({
            "rank": r["rank"],
            "student_id": r["student_id"],
            "name": name,
            "score": round((r["avg_score"] or 0) * 100, 2),
            "isMe": r["student_id"] == user_id,
            "initials": initials
        })

    return result

@router.get("/course/{course_id}/student-performance")
async def teacher_student_performance(
    course_id: UUID,
    _: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    # Mapping your view 'teacher_student_performance'
    # Columns: student_id, student (full_name), usn, course_id, attempts, average_score, highest_score, improvement
    rows = await db.fetch(
        """
        SELECT 
            student_id, 
            student AS full_name, 
            usn, 
            attempts, 
            average_score, 
            highest_score, 
            improvement
        FROM public.teacher_student_performance
        WHERE course_id = $1
        ORDER BY average_score DESC
        """,
        course_id
    )
    return [dict(r) for r in rows]

@router.get("/student/{student_id}/score-trend")
async def score_trend(
    student_id: str,
    current_user: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_db),
):

    if current_user["role"] == "student" and str(current_user["id"]) != student_id:
        raise HTTPException(status_code=403, detail="Cannot view another student's data")

    rows = await db.fetch(
        """
        SELECT
            q.title as quiz,
            a.total_score,
            a.submitted_at
        FROM public.quiz_attempts a
        JOIN public.quizzes q ON q.id = a.quiz_id
        WHERE a.student_id = $1
        AND a.status IN ('submitted','evaluated')
        ORDER BY a.submitted_at
        """,
        student_id,
    )

    return [dict(r) for r in rows]
@router.get("/course/{course_id}/weak-students")
async def weak_students(
    course_id: UUID,
    _: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    # Mapping your view 'weak_students'
    # Columns: full_name, usn, course_id, avg_score
    rows = await db.fetch(
        """
        SELECT full_name, usn, avg_score
        FROM public.weak_students
        WHERE course_id = $1
        ORDER BY avg_score ASC
        """,
        course_id
    )
    return [dict(r) for r in rows]

@router.get("/course/{course_id}/top-performers")
async def top_performers(
    course_id: UUID,
    limit: int = Query(5, ge=1, le=50),
    _: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    # Mapping your view 'top_performers'
    # Columns: full_name, usn, course_id, avg_score, highest_score
    rows = await db.fetch(
        """
        SELECT full_name, usn, avg_score, highest_score
        FROM public.top_performers
        WHERE course_id = $1
        ORDER BY avg_score DESC
        LIMIT $2
        """,
        course_id, limit
    )
    return [dict(r) for r in rows]


@router.get("/course/{course_id}/class-summary")
async def class_summary(
    course_id: UUID,
    _: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    # Aggregating directly from quiz_attempts linked to your quizzes table
    row = await db.fetchrow(
        """
        SELECT 
            COUNT(DISTINCT qa.student_id) as total_students,
            COUNT(qa.id) as total_attempts,
            ROUND(AVG(qa.total_score)::numeric, 2) as class_average,
            MAX(qa.total_score) as highest_score,
            MIN(qa.total_score) as lowest_score
        FROM public.quiz_attempts qa
        JOIN public.quizzes q ON q.id = qa.quiz_id
        WHERE q.course_id = $1 AND qa.status = 'submitted'
        """,
        course_id
    )
    return dict(row) if row else {}


@router.get("/course/{course_id}/score-trend")
async def class_score_trend(
    course_id: UUID,
    _: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    rows = await db.fetch(
        """
        SELECT 
            DATE(a.submitted_at) as date,
            ROUND(AVG(a.total_score)::numeric, 2) as avg_score
        FROM public.quiz_attempts a
        JOIN public.quizzes q ON q.id = a.quiz_id
        WHERE q.course_id = $1
        AND a.status IN ('submitted','evaluated')
        GROUP BY DATE(a.submitted_at)
        ORDER BY DATE(a.submitted_at)
        """,
        course_id
    )

    return [dict(r) for r in rows]