import statistics
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
import asyncpg
from uuid import UUID
from datetime import date, datetime, time, timezone

from app.database import get_db
from app.dependencies import get_current_user, require_roles, require_teacher_up, require_student
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

@router.get("/student/{student_id}/dashboard")
async def teacher_student_dashboard(
    student_id: str,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    _: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):

    student_row = await db.fetchrow("""
        SELECT id
        FROM profiles
        WHERE id::text = $1
           OR usn = $1
    """, student_id)

    if not student_row:
        raise HTTPException(
            status_code=404,
            detail="Student not found"
        )

    student_id = str(
        student_row["id"]
    )

    params = [student_id]

    param_idx = 2

    date_filter_attempt = ""
    date_filter_trend = ""

    if start_date:
        start_dt = datetime.combine(
            start_date,
            time.min
        )

        date_filter_attempt += (
            f" AND attempt_date >= ${param_idx}"
        )

        date_filter_trend += (
            f" AND submitted_at >= ${param_idx}"
        )

        params.append(start_dt)
        param_idx += 1

    if end_date:
        end_dt = datetime.combine(
            end_date,
            time.max
        )

        date_filter_attempt += (
            f" AND attempt_date <= ${param_idx}"
        )

        date_filter_trend += (
            f" AND submitted_at <= ${param_idx}"
        )

        params.append(end_dt)
        param_idx += 1

    stats = await db.fetchrow(f"""
        SELECT
            COUNT(*) as tests_taken,
            COALESCE(AVG(score), 0) as avg_score,
            COALESCE(MAX(score), 0) as best_score
        FROM student_attempts_view
        WHERE student_id = $1
        {date_filter_attempt}
    """, *params)

    subjects = await db.fetch(f"""
        SELECT
            subject,
            COUNT(*) as tests_taken,
            AVG(score) as avg_score
        FROM student_attempts_view
        WHERE student_id = $1
        {date_filter_attempt}
        GROUP BY subject
    """, *params)

    trend = await db.fetch(f"""
        SELECT
            quiz,
            total_score,
            submitted_at
        FROM student_score_trend
        WHERE student_id = $1
        {date_filter_trend}
        ORDER BY submitted_at DESC
    """, *params)

    date_filter_attempt_qa = (
        date_filter_attempt.replace(
            "attempt_date",
            "qa.submitted_at"
        )
    )

    attempts = await db.fetch(f"""
        SELECT
            qa.id AS attempt_id,
            q.title AS test_title,
            c.id AS course_id,
            c.name AS subject,
            qa.time_spent_seconds,
            qa.submitted_at AS attempt_date,
            'teacher' AS type,

            COUNT(sa.question_id)
                AS total_questions,

            COUNT(
                CASE
                    WHEN sa.is_correct
                    THEN 1
                END
            ) AS correct_answers

        FROM quiz_attempts qa

        JOIN quizzes q
            ON q.id = qa.quiz_id

        JOIN courses c
            ON c.id = q.course_id

        LEFT JOIN student_answers sa
            ON sa.attempt_id = qa.id

        WHERE qa.student_id = $1
        {date_filter_attempt_qa}

        GROUP BY
            qa.id,
            q.title,
            c.id,
            c.name,
            qa.time_spent_seconds,
            qa.submitted_at

        ORDER BY qa.submitted_at DESC
    """, *params)

    formatted_attempts = []

    for a in attempts:

        correct = (
            a["correct_answers"] or 0
        )

        total = (
            a["total_questions"] or 0
        )

        accuracy = round(
            (correct / total) * 100
        ) if total > 0 else 0

        formatted_attempts.append({
            "attempt_id":
                a["attempt_id"],

            "test_title":
                a["test_title"],

            "subject":
                a["subject"],

            "type":
                a["type"],

            "attempt_date":
                a["attempt_date"],

            "time_spent_seconds":
                a["time_spent_seconds"],

            "correct":
                correct,

            "total_questions":
                total,

            "accuracy":
                accuracy
        })

    rank_row = await db.fetchrow("""
        SELECT ranked.rank
        FROM (
            SELECT
                student_id,

                RANK() OVER (
                    ORDER BY AVG(score) DESC
                ) AS rank

            FROM student_attempts_view

            GROUP BY student_id
        ) ranked

        WHERE ranked.student_id = $1
    """, student_id)

    streak_row = await db.fetchrow("""
        WITH daily AS (
            SELECT DISTINCT
                DATE(attempt_date) AS day

            FROM student_attempts_view

            WHERE student_id = $1
        ),

        numbered AS (
            SELECT
                day,

                ROW_NUMBER() OVER (
                    ORDER BY day DESC
                ) AS rn

            FROM daily
        ),

        streaks AS (
            SELECT
                day,
                rn,

                (
                    day +
                    (rn || ' days')::interval
                )::date AS grp

            FROM numbered
        )

        SELECT COUNT(*) AS streak
        FROM streaks

        WHERE grp = (
            SELECT (
                day +
                (rn || ' days')::interval
            )::date

            FROM streaks

            WHERE day = (
                SELECT MAX(day)
                FROM daily
            )

            LIMIT 1
        )
    """, student_id)

    course_id = None

    if attempts:
        course_id = str(
            attempts[0]["course_id"]
        )

    return {
        "stats": {
            **(
                dict(stats)
                if stats
                else {
                    "tests_taken": 0,
                    "avg_score": 0,
                    "best_score": 0
                }
            ),

            "rank":
                int(rank_row["rank"])
                if rank_row
                else None,

            "streak":
                int(streak_row["streak"])
                if streak_row
                else 0,

            "course_id": course_id,
        },

        "subjects":
            [dict(r) for r in subjects]
            if subjects else [],

        "trend":
            [dict(r) for r in trend]
            if trend else [],

        "attempts":
            formatted_attempts,
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
    current_user: dict = Depends(
        require_roles(
            "student",
            "teacher",
            "hod",
            "admin"
        )
    ),
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
            "score": round((r["avg_score"] or 0),2),
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
    row = await db.fetchrow("""
        SELECT *
        FROM public.class_analytics_summary
        WHERE course_id = $1
        ORDER BY updated_at DESC
        LIMIT 1
    """, course_id)

    if not row:
        return {}

    return {
        "total_students": row["total_students"],
        "total_tests": row["total_tests"],
        "total_assignments": row["total_assignments"],

        "class_average": float(row["avg_score"] or 0),
        "pass_rate": float(row["pass_rate"] or 0),

        "improvement_rate": float(row["improvement_rate"] or 0),
        "consistency_score": float(row["consistency_score"] or 0),
        "engagement_score": float(row["engagement_score"] or 0),

        "on_track_percent": float(row["on_track_percent"] or 0),
        "needs_improvement_percent": float(row["needs_improvement_percent"] or 0),
        "at_risk_percent": float(row["at_risk_percent"] or 0),
    }


@router.get("/course/{course_id}/score-trend")
async def class_score_trend(
    course_id: UUID,
    _: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    rows = await db.fetch("""
        SELECT date, avg_score
        FROM public.test_score_trend
        WHERE course_id = $1
        ORDER BY date
    """, course_id)

    return [dict(r) for r in rows]

@router.get("/course/{course_id}/assignment-trend")
async def assignment_trend(
    course_id: UUID,
    _: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    rows = await db.fetch("""
        SELECT date, avg_score
        FROM public.assignment_score_trend
        WHERE course_id = $1
        ORDER BY date
    """, course_id)

    return [dict(r) for r in rows]

@router.get("/course/{course_id}/comparison-trend")
async def comparison_trend(
    course_id: UUID,
    _: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    rows = await db.fetch("""
        SELECT 
            t.date,
            t.avg_score as test_avg,
            a.avg_score as assignment_avg
        FROM public.test_score_trend t
        LEFT JOIN public.assignment_score_trend a 
        ON t.date = a.date AND t.course_id = a.course_id
        WHERE t.course_id = $1
        ORDER BY t.date
    """, course_id)

    return [dict(r) for r in rows]


@router.get("/course/{course_id}/risk-distribution")
async def risk_distribution(
    course_id: UUID,
    _: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    rows = await db.fetch("""
        SELECT risk_level, COUNT(*) as count
        FROM public.student_risk_levels
        WHERE course_id = $1
        GROUP BY risk_level
    """, course_id)

    result = {
        "on_track": 0,
        "needs_improvement": 0,
        "at_risk": 0
    }

    for r in rows:
        result[r["risk_level"]] = r["count"]

    total = sum(result.values()) or 1

    return {
        "on_track_percent": round(result["on_track"] * 100 / total, 2),
        "needs_improvement_percent": round(result["needs_improvement"] * 100 / total, 2),
        "at_risk_percent": round(result["at_risk"] * 100 / total, 2),
    }

@router.get("/course/{course_id}/assignment-summary")
async def assignment_summary(
    course_id: UUID,
    _: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    row = await db.fetchrow("""
        SELECT 
            COUNT(*) as total_submissions,
            ROUND(AVG(marks_obtained)::numeric, 2) as avg_score,
            COUNT(DISTINCT student_id) as students_submitted
        FROM public.assignment_submissions s
        JOIN public.assignments a ON s.assignment_id = a.id
        WHERE a.course_id = $1
    """, course_id)

    return dict(row) if row else {}





@router.get("/attempt/{attempt_id}/review")
async def get_attempt_review(
    attempt_id: UUID,
    _: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):

    # ── Attempt info ─────────────────────────────────────
    attempt = await db.fetchrow("""
        SELECT
            qa.id,
            qa.student_id,
            qa.quiz_id,
            qa.total_score,
            qa.time_spent_seconds,
            qa.tab_switch_count,
            qa.full_screen_violations,
            qa.cheating_flag,
            qa.status,
            qa.submitted_at,

            q.title,
            q.description,

            c.name AS subject,

            p.full_name,
            p.usn

        FROM quiz_attempts qa

        JOIN quizzes q
            ON q.id = qa.quiz_id

        LEFT JOIN courses c
            ON c.id = q.course_id

        LEFT JOIN profiles p
            ON p.id = qa.student_id

        WHERE qa.id = $1
    """, attempt_id)

    if not attempt:
        raise HTTPException(
            status_code=404,
            detail="Attempt not found"
        )

    # ── Questions + Answers ─────────────────────────────
    rows = await db.fetch("""
        SELECT
            qb.id AS question_id,
            qb.question_text,
            qb.explanation,

            qo.id AS option_id,
            qo.option_text,
            qo.is_correct AS option_correct,

            sa.selected_option_id,
            sa.is_correct

        FROM student_answers sa

        JOIN question_bank qb
            ON qb.id = sa.question_id

        LEFT JOIN question_options qo
            ON qo.question_id = qb.id

        WHERE sa.attempt_id = $1

        ORDER BY qb.id
    """, attempt_id)

    # ── Group questions ─────────────────────────────────
    qmap = {}

    for row in rows:

        qid = str(row["question_id"])

        if qid not in qmap:

            correct_option = None

            qmap[qid] = {
                "question_id":
                    qid,

                "question_text":
                    row["question_text"],

                "selected_answer":
                    str(row["selected_option_id"])
                    if row["selected_option_id"]
                    else None,

                "correct_answer":
                    None,

                "is_correct":
                    row["is_correct"],

                "explanation":
                    row["explanation"],

                "options": [],
            }

        if row["option_id"]:

            opt_id = str(row["option_id"])

            if row["option_correct"]:
                qmap[qid]["correct_answer"] = opt_id

            qmap[qid]["options"].append({
                "id": opt_id,
                "option_text":
                    row["option_text"],
            })

    questions = list(qmap.values())

    # ── Stats ───────────────────────────────────────────
    total = len(questions)

    correct = len([
        q for q in questions
        if q["is_correct"]
    ])

    # ── Final response ──────────────────────────────────
    return {

        "attempt_id":
            str(attempt["id"]),

        "student": {
            "full_name":
                attempt["full_name"],

            "usn":
                attempt["usn"],
        },

        "config": {

            "title":
                attempt["title"],

            "subject":
                attempt["subject"],

            "topic":
                attempt["description"],

            "type":
                "quiz",
        },

        "test_title":
            attempt["title"],

        "subject":
            attempt["subject"],

        "topic":
            attempt["description"],

        "type":
            "quiz",

        "correct":
            correct,

        "total":
            total,

        "questions":
            questions,

        "tabs":
            attempt["tab_switch_count"]
            or 0,

        "timeSpent":
            attempt["time_spent_seconds"]
            or 0,

        "time_spent_seconds":
            attempt["time_spent_seconds"]
            or 0,

        "total_score":
            float(
                attempt["total_score"]
                or 0
            ),

        "status":
            attempt["status"],

        "submitted_at":
            attempt["submitted_at"],

        "cheating_flag":
            attempt["cheating_flag"],

        "full_screen_violations":
            attempt["full_screen_violations"]
            or 0,
    }





@router.get("/quizzes/{quiz_id}/summary")
async def get_quiz_summary(
    quiz_id: UUID,
    _: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):

    # ─────────────────────────────────────────────
    # QUIZ INFO
    # ─────────────────────────────────────────────

    quiz = await db.fetchrow("""
        SELECT
            q.id,
            q.title,
            q.description,
            q.total_marks,
            q.passing_marks,
            q.duration_minutes,
            q.allow_multiple_attempts,
            q.max_attempts,

            c.id   AS course_id,
            c.name AS subject

        FROM quizzes q

        LEFT JOIN courses c
            ON c.id = q.course_id

        WHERE q.id = $1
    """, quiz_id)

    if not quiz:
        raise HTTPException(
            status_code=404,
            detail="Quiz not found"
        )

    # ─────────────────────────────────────────────
    # ENROLLED STUDENTS
    # ─────────────────────────────────────────────

    enrolled_students = await db.fetchval("""
        SELECT COUNT(*)
        FROM enrollments
        WHERE course_id = $1
    """, quiz["course_id"])

    # ─────────────────────────────────────────────
    # BEST ATTEMPT PER STUDENT
    # ─────────────────────────────────────────────

    attempts = await db.fetch("""

        WITH ranked AS (

            SELECT
                qa.id,
                qa.student_id,
                qa.quiz_id,
                qa.attempt_number,

                qa.total_score,
                qa.status,

                qa.time_spent_seconds,
                qa.tab_switch_count,
                qa.full_screen_violations,
                qa.cheating_flag,

                qa.started_at,
                qa.submitted_at,

                p.full_name,
                p.usn,

                ROW_NUMBER() OVER (
                    PARTITION BY qa.student_id
                    ORDER BY
                        qa.total_score DESC,
                        qa.submitted_at DESC
                ) AS rn

            FROM quiz_attempts qa

            JOIN profiles p
                ON p.id = qa.student_id

            WHERE qa.quiz_id = $1
            AND qa.status IN (
                'submitted',
                'evaluated'
            )
        )

        SELECT *
        FROM ranked
        WHERE rn = 1

    """, quiz_id)

    # ─────────────────────────────────────────────
    # ALL ATTEMPTS
    # ─────────────────────────────────────────────

    all_attempts = await db.fetch("""
        SELECT
            qa.id,
            qa.student_id,
            qa.attempt_number,
            qa.total_score,
            qa.status,
            qa.time_spent_seconds,
            qa.cheating_flag,
            qa.tab_switch_count,
            qa.full_screen_violations,
            qa.submitted_at,

            p.full_name,
            p.usn

        FROM quiz_attempts qa

        JOIN profiles p
            ON p.id = qa.student_id

        WHERE qa.quiz_id = $1
    """, quiz_id)

    # ─────────────────────────────────────────────
    # BASIC STATS
    # ─────────────────────────────────────────────

    students_attempted = len(attempts)

    submitted = students_attempted

    pending = max(
        enrolled_students - submitted,
        0
    )

    scores = [
        float(a["total_score"] or 0)
        for a in attempts
    ]

    avg_score = round(
        statistics.mean(scores),
        1
    ) if scores else 0

    median_score = round(
        statistics.median(scores),
        1
    ) if scores else 0

    std_deviation = round(
        statistics.stdev(scores),
        1
    ) if len(scores) > 1 else 0

    highest_score = max(scores) if scores else 0
    lowest_score  = min(scores) if scores else 0

    pass_marks = float(
        quiz["passing_marks"] or 0
    )

    passed = len([
        s for s in scores
        if s >= pass_marks
    ])

    failed = students_attempted - passed

    completion_rate = round(
        (submitted / enrolled_students) * 100,
        1
    ) if enrolled_students else 0

    # ─────────────────────────────────────────────
    # TIME ANALYTICS
    # ─────────────────────────────────────────────

    times = [
        a["time_spent_seconds"] or 0
        for a in attempts
    ]

    avg_time = round(
        statistics.mean(times) / 60
    ) if times else 0

    fastest_time = round(
        min(times) / 60
    ) if times else 0

    slowest_time = round(
        max(times) / 60
    ) if times else 0

    # ─────────────────────────────────────────────
    # PROCTORING ANALYTICS
    # ─────────────────────────────────────────────

    cheating_flags = len([
        a for a in attempts
        if a["cheating_flag"]
    ])

    total_tab_switches = sum([
        a["tab_switch_count"] or 0
        for a in attempts
    ])

    total_fullscreen_violations = sum([
        a["full_screen_violations"] or 0
        for a in attempts
    ])

    avg_tab_switches = round(
        total_tab_switches / students_attempted,
        1
    ) if students_attempted else 0

    # ─────────────────────────────────────────────
    # LEADERBOARD
    # ─────────────────────────────────────────────

    leaderboard = sorted(
        [
            {
                "student_id":
                    str(a["student_id"]),

                "full_name":
                    a["full_name"],

                "usn":
                    a["usn"],

                "score":
                    round(
                        float(a["total_score"] or 0),
                        1
                    ),

                "attempt_number":
                    a["attempt_number"],

                "time_spent_seconds":
                    a["time_spent_seconds"],

                "cheating_flag":
                    a["cheating_flag"],
            }
            for a in attempts
        ],
        key=lambda x: (
            -x["score"],
            x["time_spent_seconds"] or 999999
        )
    )

    for i, row in enumerate(
        leaderboard,
        start=1
    ):
        row["rank"] = i

    # ─────────────────────────────────────────────
    # DISTRIBUTION
    # ─────────────────────────────────────────────

    total_marks = float(
        quiz["total_marks"] or 100
    )

    distribution = {

        f"0-{int(total_marks * 0.2)}": 0,

        f"{int(total_marks * 0.2) + 1}-{int(total_marks * 0.4)}": 0,

        f"{int(total_marks * 0.4) + 1}-{int(total_marks * 0.6)}": 0,

        f"{int(total_marks * 0.6) + 1}-{int(total_marks * 0.8)}": 0,

        f"{int(total_marks * 0.8) + 1}-{int(total_marks)}": 0,
    }

    for score in scores:

        if score <= total_marks * 0.2:

            key = f"0-{int(total_marks * 0.2)}"

        elif score <= total_marks * 0.4:

            key = f"{int(total_marks * 0.2) + 1}-{int(total_marks * 0.4)}"

        elif score <= total_marks * 0.6:

            key = f"{int(total_marks * 0.4) + 1}-{int(total_marks * 0.6)}"

        elif score <= total_marks * 0.8:

            key = f"{int(total_marks * 0.6) + 1}-{int(total_marks * 0.8)}"

        else:

            key = f"{int(total_marks * 0.8) + 1}-{int(total_marks)}"

        distribution[key] += 1

    # ─────────────────────────────────────────────
    # IMPROVEMENT
    # ─────────────────────────────────────────────

    attempt_map = {}

    for a in all_attempts:

        sid = str(a["student_id"])

        attempt_map.setdefault(
            sid,
            []
        ).append(a)

    improvement_students = []

    for sid, arr in attempt_map.items():

        if len(arr) < 2:
            continue

        arr = sorted(
            arr,
            key=lambda x:
                x["attempt_number"]
        )

        first_score = float(
            arr[0]["total_score"] or 0
        )

        best_score = max([
            float(x["total_score"] or 0)
            for x in arr
        ])

        improvement_students.append({

            "student_id":
                sid,

            "full_name":
                arr[0]["full_name"],

            "usn":
                arr[0]["usn"],

            "first_score":
                first_score,

            "best_score":
                best_score,

            "improvement":
                round(
                    best_score - first_score,
                    1
                ),
        })

    improvement_students = sorted(
        improvement_students,
        key=lambda x:
            x["improvement"],
        reverse=True
    )[:10]

    # ─────────────────────────────────────────────
    # PASS / FAIL LOGIC
    # ─────────────────────────────────────────────

    total_marks = float(
        quiz["total_marks"] or 0
    )

    # if passing marks explicitly set
    # use it
    # else default = 50% of total marks

    pass_marks = (

        float(quiz["passing_marks"])

        if quiz["passing_marks"] is not None

        else round(total_marks * 0.5, 1)

    )

    passed = len([

        s for s in scores

        if float(s or 0) >= pass_marks

    ])

    failed = max(
        students_attempted - passed,
        0
    )

    pass_rate = round(

        (passed / students_attempted) * 100,

        1

    ) if students_attempted else 0

    # ─────────────────────────────────────────────
    # SUSPICIOUS STUDENTS
    # ─────────────────────────────────────────────

    suspicious_students = [
        {
            "student_id":
                str(a["student_id"]),

            "full_name":
                a["full_name"],

            "usn":
                a["usn"],

            "score":
                float(a["total_score"] or 0),

            "tab_switches":
                a["tab_switch_count"],

            "violations":
                a["full_screen_violations"],
        }
        for a in attempts
        if (
            a["cheating_flag"]
            or
            (a["tab_switch_count"] or 0) > 5
            or
            (a["full_screen_violations"] or 0) > 3
        )
    ]

    topic_analytics = await db.fetch("""

        SELECT

            qb.topic,

            COUNT(sa.id) AS total_answers,

            ROUND(
                AVG(
                    (
                        COALESCE(
                            sa.score_awarded,
                            0
                        )
                        /
                        NULLIF(
                            qb.marks,
                            0
                        )
                    ) * 100
                ),
                1
            ) AS accuracy

        FROM student_answers sa

        JOIN question_bank qb
            ON qb.id = sa.question_id

        JOIN quiz_attempts qa
            ON qa.id = sa.attempt_id

        WHERE qa.quiz_id = $1

        GROUP BY qb.topic

        ORDER BY accuracy ASC

    """, quiz_id)

    hardest_questions_raw = await db.fetch("""

        SELECT

            qb.id,
            qb.question_text,
            qb.topic,
            qb.difficulty,

            COUNT(sa.id) AS total_attempts,

            SUM(
                CASE
                    WHEN COALESCE(
                        sa.score_awarded,
                        0
                    ) < qb.marks
                    THEN 1
                    ELSE 0
                END
            ) AS incorrect_count,

            ROUND(
                AVG(
                    (
                        COALESCE(
                            sa.score_awarded,
                            0
                        )
                        /
                        NULLIF(
                            qb.marks,
                            0
                        )
                    ) * 100
                ),
                1
            ) AS accuracy

        FROM student_answers sa

        JOIN question_bank qb
            ON qb.id = sa.question_id

        JOIN quiz_attempts qa
            ON qa.id = sa.attempt_id

        WHERE qa.quiz_id = $1

        GROUP BY
            qb.id,
            qb.question_text,
            qb.topic,
            qb.difficulty

        ORDER BY accuracy ASC

        LIMIT 5

    """, quiz_id)

    hardest_questions = [
        dict(x)
        for x in hardest_questions_raw
    ]


    insights = []

    if pass_rate < 50:

        insights.append(
            "Pass rate is low. Students struggled with this quiz."
        )

    if avg_tab_switches > 3:

        insights.append(
            "Students showed unusually high tab switching behavior."
        )

    if cheating_flags > 0:

        insights.append(
            f"{cheating_flags} students were flagged for suspicious activity."
        )

    if std_deviation > 20:

        insights.append(
            "Large score variance detected across students."
        )

    if topic_analytics:

        weakest_topic = dict(
            topic_analytics[0]
        )

        insights.append(
            f"Weakest topic: {weakest_topic['topic']} ({weakest_topic['accuracy']}% accuracy)"
        )

    if hardest_questions:

        hardest = hardest_questions[0]

        insights.append(
            f"Hardest question accuracy was only {hardest['accuracy']}%."
        )

    if improvement_students:

        insights.append(
            f"{len(improvement_students)} students improved across multiple attempts."
        )

    

    # ─────────────────────────────────────────────
    # FINAL RESPONSE
    # ─────────────────────────────────────────────

    return {

        "quiz": {

            "id":
                str(quiz["id"]),

            "title":
                quiz["title"],

            "subject":
                quiz["subject"],

            "description":
                quiz["description"],

            "total_marks":
                float(
                    quiz["total_marks"] or 0
                ),

            "passing_marks":
                float(
                    quiz["passing_marks"] or 0
                ),

            "duration_minutes":
                quiz["duration_minutes"],

            "allow_multiple_attempts":
                quiz["allow_multiple_attempts"],

            "max_attempts":
                quiz["max_attempts"],
        },

        "stats": {

            "enrolled_students":
                enrolled_students,

            "students_attempted":
                students_attempted,

            "submitted":
                submitted,

            "pending":
                pending,

            "completion_rate":
                completion_rate,

            "total_attempts":
                len(all_attempts),

            "avg_attempts_per_student":
                round(
                    len(all_attempts) / students_attempted,
                    1
                ) if students_attempted else 0,

            "average_score":
                avg_score,

            "median_score":
                median_score,

            "std_deviation":
                std_deviation,

            "highest_score":
                highest_score,

            "lowest_score":
                lowest_score,

            "passed":
                passed,

            "failed":
                failed,

            "pass_rate":
                pass_rate,

            "cheating_flags":
                cheating_flags,

            "total_tab_switches":
                total_tab_switches,

            "total_fullscreen_violations":
                total_fullscreen_violations,

            "avg_tab_switches":
                avg_tab_switches,

            "avg_time_minutes":
                avg_time,

            "fastest_time_minutes":
                fastest_time,

            "slowest_time_minutes":
                slowest_time,
        },

        "leaderboard":
            leaderboard,

        "distribution":
            distribution,

        "improvement_students":
            improvement_students,

        "suspicious_students":
            suspicious_students,

        # ─────────────────────────────
        # ADD THESE
        # ─────────────────────────────

        "topic_analytics": [
            dict(x)
            for x in topic_analytics
        ],

        "hardest_questions":
            hardest_questions,

        "insights":
            insights,
    }