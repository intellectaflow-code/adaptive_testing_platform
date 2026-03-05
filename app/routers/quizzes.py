from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
from datetime import datetime, timezone
import asyncpg
from pydantic import BaseModel
from app.services.grok_client import generate_ai_quiz

from app.database import get_db
from app.dependencies import get_current_user, require_teacher_up, require_admin_or_hod
from app.schemas.quizzes import (
    QuizCreate, QuizUpdate, QuizOut,
    QuizQuestionAdd, QuizPermissionCreate, QuizPermissionOut,
)
from app.services.activity import log_activity
from app.schemas.ai_quiz import (
    AIQuizAttemptCreate,
    AIQuizAttemptOut,
    AIQuizSubmit,
    AIQuizAnswerCreate
)
router = APIRouter(prefix="/quizzes", tags=["Quizzes"])


async def _get_quiz_or_404(db, quiz_id: str):
    row = await db.fetchrow(
        "SELECT * FROM public.quizzes WHERE id = $1 AND is_deleted = false", quiz_id
    )
    if not row:
        raise HTTPException(status_code=404, detail="Quiz not found")
    return row


async def _assert_quiz_ownership(db, quiz_id: str, user: dict):
    """Teacher must own the quiz; admin/hod bypass."""
    if user["role"] in ("admin", "hod"):
        return
    quiz = await _get_quiz_or_404(db, quiz_id)
    if str(quiz["created_by"]) != str(user["id"]):
        raise HTTPException(status_code=403, detail="Not the quiz owner")


async def _enrich_quiz(db, row: dict) -> dict:
    q = dict(row)
    count = await db.fetchval(
        "SELECT COUNT(*) FROM public.quiz_questions WHERE quiz_id = $1", str(q["id"])
    )
    q["question_count"] = count
    return q

@router.post("/ai/start")
async def start_ai_quiz(
    body: AIQuizAttemptCreate,
    current_user: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_db),
):

    if current_user["role"] != "student":
        raise HTTPException(status_code=403, detail="Only students can start AI quizzes")

    async with db.transaction():

        row = await db.fetchrow(
            """
            INSERT INTO public.ai_quiz_attempts
            (student_id, topic, difficulty, total_questions)
            VALUES ($1,$2,$3,$4)
            RETURNING *
            """,
            str(current_user["id"]),
            body.topic,
            body.difficulty,
            body.total_questions,
        )

        attempt_id = row["id"]

        questions = await generate_ai_quiz(
            topic=body.topic,
            difficulty=body.difficulty,
            num_questions=body.total_questions,
        )

        # store generated questions
        for q in questions:
            await db.execute(
                """
                INSERT INTO public.ai_quiz_answers
                (attempt_id, question_text, correct_answer)
                VALUES ($1,$2,$3)
                """,
                attempt_id,
                q["question_text"],
                q["correct_answer"],
            )

    # remove correct answers before sending to frontend
    safe_questions = []
    for q in questions:
        safe_questions.append({
            "question_text": q["question_text"],
            "options": q["options"]
        })

    return {
        "attempt_id": attempt_id,
        "questions": safe_questions
    }


@router.post("/ai/submit")
async def submit_ai_quiz(
    body: AIQuizSubmit,
    current_user: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_db),
):

    attempt = await db.fetchrow(
        """
        SELECT * FROM public.ai_quiz_attempts
        WHERE id = $1 AND student_id = $2
        """,
        body.attempt_id,
        str(current_user["id"]),
    )

    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")

    correct_count = 0

    async with db.transaction():

        for ans in body.answers:

            if ans.is_correct:
                correct_count += 1

            await db.execute(
                """
                INSERT INTO public.ai_quiz_answers
                (attempt_id, question_text, selected_answer, correct_answer, is_correct)
                VALUES ($1,$2,$3,$4,$5)
                """,
                body.attempt_id,
                ans.question_text,
                ans.selected_answer,
                ans.correct_answer,
                ans.is_correct,
            )

        total_questions = len(body.answers)
        score = correct_count

        await db.execute(
            """
            UPDATE public.ai_quiz_attempts
            SET correct_answers = $1,
                score = $2
            WHERE id = $3
            """,
            correct_count,
            score,
            body.attempt_id,
        )

    return {
        "attempt_id": body.attempt_id,
        "correct_answers": correct_count,
        "total_questions": total_questions,
        "score": score
    }

@router.get("/ai/history")
async def get_ai_quiz_history(
    current_user: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_db),
):

    rows = await db.fetch(
        """
        SELECT *
        FROM public.ai_quiz_attempts
        WHERE student_id = $1
        ORDER BY created_at DESC
        """,
        str(current_user["id"]),
    )

    return [dict(r) for r in rows]

@router.get("/ai/{attempt_id}/answers")
async def get_ai_quiz_answers(
    attempt_id: str,
    current_user: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_db),
):

    rows = await db.fetch(
        """
        SELECT *
        FROM public.ai_quiz_answers
        WHERE attempt_id = $1
        """,
        attempt_id,
    )

    return [dict(r) for r in rows]

@router.post("", response_model=QuizOut, status_code=201)
async def create_quiz(
    body: QuizCreate,
    current_user: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    async with db.transaction():
        quiz = await db.fetchrow(
            """
            INSERT INTO public.quizzes
              (course_id, created_by, title, description, total_marks, passing_marks,
               duration_minutes, start_time, end_time, randomize_questions,
               randomize_options, allow_multiple_attempts, max_attempts, show_results_immediately)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
            RETURNING *
            """,
            str(body.course_id), str(current_user["id"]),
            body.title, body.description, body.total_marks, body.passing_marks,
            body.duration_minutes, body.start_time, body.end_time,
            body.randomize_questions, body.randomize_options,
            body.allow_multiple_attempts, body.max_attempts, body.show_results_immediately,
        )
        quiz_id = str(quiz["id"])

        for i, qq in enumerate(body.questions):
            await db.execute(
                """
                INSERT INTO public.quiz_questions (quiz_id, question_id, question_order, marks_override)
                VALUES ($1, $2, $3, $4)
                """,
                quiz_id, str(qq.question_id), qq.question_order or (i + 1), qq.marks_override,
            )

    await log_activity(db, str(current_user["id"]), "create_quiz", {"quiz_id": quiz_id})
    return await _enrich_quiz(db, quiz)


@router.get("", response_model=List[QuizOut])
async def list_quizzes(
    course_id: Optional[str] = Query(None),
    published_only: bool = Query(False),
    skip: int = 0,
    limit: int = 50,
    current_user: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_db),
):
    where_parts = ["q.is_deleted = false", "q.is_archived = false"]
    params: list = []
    idx = 1

    if course_id:
        where_parts.append(f"q.course_id = ${idx}"); params.append(course_id); idx += 1

    if current_user["role"] == "student":
        # Students only see published quizzes for their enrolled courses
        where_parts.append("q.is_published = true")
        where_parts.append(
            f"EXISTS(SELECT 1 FROM public.enrollments e WHERE e.course_id = q.course_id AND e.student_id = ${idx})"
        )
        params.append(str(current_user["id"])); idx += 1

    elif current_user["role"] == "teacher":
        where_parts.append(f"q.created_by = ${idx}"); params.append(str(current_user["id"])); idx += 1
        if published_only:
            where_parts.append("q.is_published = true")
    else:
        if published_only:
            where_parts.append("q.is_published = true")

    where = " AND ".join(where_parts)
    rows = await db.fetch(
        f"""
        SELECT q.* FROM public.quizzes q
        WHERE {where}
        ORDER BY q.created_at DESC
        LIMIT ${idx} OFFSET ${idx+1}
        """,
        *params, limit, skip,
    )
    result = []
    for r in rows:
        result.append(await _enrich_quiz(db, r))
    return result


@router.get("/{quiz_id}", response_model=QuizOut)
async def get_quiz(
    quiz_id: str,
    current_user: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_db),
):
    quiz = await _get_quiz_or_404(db, quiz_id)
    if current_user["role"] == "student" and not quiz["is_published"]:
        raise HTTPException(status_code=403, detail="Quiz is not published")
    return await _enrich_quiz(db, quiz)


@router.put("/{quiz_id}", response_model=QuizOut)
async def update_quiz(
    quiz_id: str,
    body: QuizUpdate,
    current_user: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    await _assert_quiz_ownership(db, quiz_id, current_user)
    quiz = await _get_quiz_or_404(db, quiz_id)

    if quiz["is_published"]:
        raise HTTPException(status_code=409, detail="Cannot edit a published quiz. Unpublish first.")

    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    set_clause = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(updates.keys()))
    row = await db.fetchrow(
        f"UPDATE public.quizzes SET {set_clause}, updated_at = now() WHERE id = $1 RETURNING *",
        quiz_id, *updates.values(),
    )
    return await _enrich_quiz(db, row)


@router.delete("/{quiz_id}", status_code=204)
async def delete_quiz(
    quiz_id: str,
    current_user: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    await _assert_quiz_ownership(db, quiz_id, current_user)
    await db.execute(
        "UPDATE public.quizzes SET is_deleted = true, updated_at = now() WHERE id = $1", quiz_id
    )


# ---- Publish / Archive ----

@router.post("/{quiz_id}/publish", response_model=QuizOut)
async def publish_quiz(
    quiz_id: str,
    current_user: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    await _assert_quiz_ownership(db, quiz_id, current_user)
    q_count = await db.fetchval(
        "SELECT COUNT(*) FROM public.quiz_questions WHERE quiz_id = $1", quiz_id
    )
    if q_count == 0:
        raise HTTPException(status_code=400, detail="Cannot publish a quiz with no questions")

    row = await db.fetchrow(
        "UPDATE public.quizzes SET is_published = true, updated_at = now() WHERE id = $1 RETURNING *",
        quiz_id,
    )
    await log_activity(db, str(current_user["id"]), "publish_quiz", {"quiz_id": quiz_id})
    return await _enrich_quiz(db, row)


@router.post("/{quiz_id}/unpublish", response_model=QuizOut)
async def unpublish_quiz(
    quiz_id: str,
    current_user: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    await _assert_quiz_ownership(db, quiz_id, current_user)
    row = await db.fetchrow(
        "UPDATE public.quizzes SET is_published = false, updated_at = now() WHERE id = $1 RETURNING *",
        quiz_id,
    )
    return await _enrich_quiz(db, row)


@router.post("/{quiz_id}/archive", response_model=QuizOut)
async def archive_quiz(
    quiz_id: str,
    current_user: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    await _assert_quiz_ownership(db, quiz_id, current_user)
    row = await db.fetchrow(
        "UPDATE public.quizzes SET is_archived = true, is_published = false, updated_at = now() WHERE id = $1 RETURNING *",
        quiz_id,
    )
    return await _enrich_quiz(db, row)


# ---- Questions management ----

@router.get("/{quiz_id}/questions")
async def get_quiz_questions(
    quiz_id: str,
    current_user: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_db),
):
    quiz = await _get_quiz_or_404(db, quiz_id)

    if current_user["role"] == "student":
        if not quiz["is_published"]:
            raise HTTPException(status_code=403, detail="Quiz not available")
        # Check enrollment
        enrolled = await db.fetchval(
            "SELECT id FROM public.enrollments WHERE course_id = $1 AND student_id = $2",
            str(quiz["course_id"]), str(current_user["id"]),
        )
        if not enrolled:
            raise HTTPException(status_code=403, detail="Not enrolled in this course")

        order_clause = "ORDER BY RANDOM()" if quiz["randomize_questions"] else "ORDER BY qq.question_order"
        rows = await db.fetch(
            f"""
            SELECT qb.id, qb.question_text, qb.question_type, qb.difficulty,
                   qb.topic, COALESCE(qq.marks_override, qb.marks) as marks,
                   qb.negative_marks, qb.media_url, qq.question_order
            FROM public.quiz_questions qq
            JOIN public.question_bank qb ON qb.id = qq.question_id
            WHERE qq.quiz_id = $1 AND qb.is_deleted = false
            {order_clause}
            """,
            quiz_id,
        )
        result = []
        for r in rows:
            q = dict(r)
            # Fetch options without answers
            opts = await db.fetch(
                "SELECT id, option_text, media_url FROM public.question_options WHERE question_id = $1",
                str(q["id"]),
            )
            if quiz["randomize_options"]:
                import random
                opts = list(opts)
                random.shuffle(opts)
            q["options"] = [dict(o) for o in opts]
            result.append(q)
        return result

    # Teacher / Admin sees full question data
    rows = await db.fetch(
        """
        SELECT qb.*, qq.question_order, qq.marks_override, qq.id as quiz_question_id
        FROM public.quiz_questions qq
        JOIN public.question_bank qb ON qb.id = qq.question_id
        WHERE qq.quiz_id = $1 AND qb.is_deleted = false
        ORDER BY qq.question_order
        """,
        quiz_id,
    )
    result = []
    for r in rows:
        q = dict(r)
        q["options"] = [dict(o) for o in await db.fetch(
            "SELECT * FROM public.question_options WHERE question_id = $1", str(q["id"])
        )]
        q["tags"] = [row["tag"] for row in await db.fetch(
            "SELECT tag FROM public.question_tags WHERE question_id = $1", str(q["id"])
        )]
        result.append(q)
    return result


@router.post("/{quiz_id}/questions", status_code=201)
async def add_question_to_quiz(
    quiz_id: str,
    body: QuizQuestionAdd,
    current_user: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    await _assert_quiz_ownership(db, quiz_id, current_user)
    quiz = await _get_quiz_or_404(db, quiz_id)
    if quiz["is_published"]:
        raise HTTPException(status_code=409, detail="Unpublish quiz before editing questions")

    # Auto order
    max_order = await db.fetchval(
        "SELECT COALESCE(MAX(question_order), 0) FROM public.quiz_questions WHERE quiz_id = $1", quiz_id
    )
    try:
        row = await db.fetchrow(
            "INSERT INTO public.quiz_questions (quiz_id, question_id, question_order, marks_override) VALUES ($1,$2,$3,$4) RETURNING *",
            quiz_id, str(body.question_id), body.question_order or (max_order + 1), body.marks_override,
        )
    except asyncpg.UniqueViolationError:
        raise HTTPException(status_code=409, detail="Question already in quiz")
    return dict(row)


@router.delete("/{quiz_id}/questions/{question_id}", status_code=204)
async def remove_question_from_quiz(
    quiz_id: str,
    question_id: str,
    current_user: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    await _assert_quiz_ownership(db, quiz_id, current_user)
    quiz = await _get_quiz_or_404(db, quiz_id)
    if quiz["is_published"]:
        raise HTTPException(status_code=409, detail="Unpublish quiz before editing questions")
    await db.execute(
        "DELETE FROM public.quiz_questions WHERE quiz_id = $1 AND question_id = $2",
        quiz_id, question_id,
    )


# ---- Permissions ----

@router.post("/{quiz_id}/permissions", response_model=QuizPermissionOut, status_code=201)
async def grant_permission(
    quiz_id: str,
    body: QuizPermissionCreate,
    current_user: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    await _get_quiz_or_404(db, quiz_id)
    row = await db.fetchrow(
        """
        INSERT INTO public.quiz_permissions
          (quiz_id, student_id, extra_time_minutes, allowed_attempts, override_end_time, granted_by)
        VALUES ($1,$2,$3,$4,$5,$6)
        ON CONFLICT (quiz_id, student_id) DO UPDATE SET
          extra_time_minutes = EXCLUDED.extra_time_minutes,
          allowed_attempts = EXCLUDED.allowed_attempts,
          override_end_time = EXCLUDED.override_end_time,
          granted_by = EXCLUDED.granted_by,
          granted_at = now()
        RETURNING *
        """,
        quiz_id, str(body.student_id), body.extra_time_minutes,
        body.allowed_attempts, body.override_end_time, str(current_user["id"]),
    )
    return dict(row)


@router.get("/{quiz_id}/permissions", response_model=List[QuizPermissionOut])
async def list_permissions(
    quiz_id: str,
    current_user: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    rows = await db.fetch(
        "SELECT * FROM public.quiz_permissions WHERE quiz_id = $1", quiz_id
    )
    return [dict(r) for r in rows]


@router.delete("/{quiz_id}/permissions/{student_id}", status_code=204)
async def revoke_permission(
    quiz_id: str,
    student_id: str,
    current_user: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    await db.execute(
        "DELETE FROM public.quiz_permissions WHERE quiz_id = $1 AND student_id = $2",
        quiz_id, student_id,
    )


# ---- Results ----

@router.get("/{quiz_id}/results")
async def get_quiz_results(
    quiz_id: str,
    current_user: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    """Full leaderboard / results for a quiz."""
    rows = await db.fetch(
        """
        SELECT
            p.full_name, p.usn, a.attempt_number,
            a.total_score, a.status, a.submitted_at,
            a.tab_switch_count, a.full_screen_violations,
            a.cheating_flag, a.time_spent_seconds, a.id as attempt_id
        FROM public.quiz_attempts a
        JOIN public.profiles p ON p.id = a.student_id
        WHERE a.quiz_id = $1
        ORDER BY a.total_score DESC NULLS LAST, a.submitted_at ASC
        """,
        quiz_id,
    )
    return [dict(r) for r in rows]

