from fastapi import APIRouter, Depends, HTTPException, Request
from typing import List
from datetime import datetime, timezone
import asyncpg

from app.database import get_db
from app.dependencies import get_current_user, require_student, require_teacher_up
from app.schemas.attempts import (
    AnswerSubmit, AttemptStartOut, AttemptOut,
    ProctoringEvent, ManualGradeIn, StudentAnswerOut,
)
from app.services.grading import (
    auto_grade_answer, recalculate_attempt_score, update_question_analytics
)
from app.services.activity import log_activity

from app.services.descriptive_ai import auto_evaluate_descriptive_answers


router = APIRouter(prefix="/attempts", tags=["Quiz Attempts"])




CHEATING_TAB_SWITCH_THRESHOLD = 3
CHEATING_FULLSCREEN_THRESHOLD = 3


async def _get_attempt_or_404(db, attempt_id: str):
    row = await db.fetchrow(
        "SELECT * FROM public.quiz_attempts WHERE id = $1", attempt_id
    )
    if not row:
        raise HTTPException(status_code=404, detail="Attempt not found")
    return row


async def _assert_attempt_owner(attempt: dict, user: dict):
    if str(attempt["student_id"]) != str(user["id"]):
        raise HTTPException(status_code=403, detail="Not your attempt")


# ---- Start attempt ----

@router.post("/start/{quiz_id}", response_model=AttemptStartOut, status_code=201)
async def start_attempt(
    quiz_id: str,
    request: Request,
    current_user: dict = Depends(require_student),
    db: asyncpg.Connection = Depends(get_db),
):
    student_id = str(current_user["id"])

    quiz = await db.fetchrow(
        "SELECT * FROM public.quizzes WHERE id = $1 AND is_deleted = false AND is_published = true",
        quiz_id,
    )
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found or not published")

    # Enrollment check
    enrolled = await db.fetchval(
        "SELECT id FROM public.enrollments WHERE course_id = $1 AND student_id = $2",
        str(quiz["course_id"]), student_id,
    )
    if not enrolled:
        raise HTTPException(status_code=403, detail="Not enrolled in this course")

    # Timing check
    now = datetime.now(timezone.utc)
    if quiz["start_time"] and quiz["start_time"].replace(tzinfo=timezone.utc) > now:
        raise HTTPException(status_code=403, detail="Quiz has not started yet")

    # Check for special permissions
    permission = await db.fetchrow(
        "SELECT * FROM public.quiz_permissions WHERE quiz_id = $1 AND student_id = $2",
        quiz_id, student_id,
    )

    end_time = quiz["end_time"]
    if permission and permission["override_end_time"]:
        end_time = permission["override_end_time"]

    if end_time and end_time.replace(tzinfo=timezone.utc) < now:
        raise HTTPException(status_code=403, detail="Quiz has ended")

    # Attempt count check
    existing_attempts = await db.fetchval(
        "SELECT COUNT(*) FROM public.quiz_attempts WHERE quiz_id = $1 AND student_id = $2",
        quiz_id, student_id,
    )

    max_attempts = quiz["max_attempts"]
    if permission and permission["allowed_attempts"]:
        max_attempts = permission["allowed_attempts"]

    if not quiz["allow_multiple_attempts"] and existing_attempts >= 1:
        raise HTTPException(status_code=409, detail="Multiple attempts not allowed")

    if existing_attempts >= max_attempts:
        raise HTTPException(
            status_code=409,
            detail=f"Maximum attempts ({max_attempts}) reached",
        )

    # Check no in-progress attempt already
    in_progress = await db.fetchrow(
        "SELECT id FROM public.quiz_attempts WHERE quiz_id = $1 AND student_id = $2 AND status = 'in_progress'",
        quiz_id, student_id,
    )
    if in_progress:
        raise HTTPException(
            status_code=409, detail="You already have an in-progress attempt. Submit it first."
        )

    attempt_number = existing_attempts + 1
    ip = request.client.host if request.client else None

    attempt = await db.fetchrow(
        """
        INSERT INTO public.quiz_attempts
          (quiz_id, student_id, attempt_number, started_at, status, ip_address)
        VALUES ($1, $2, $3, now(), 'in_progress', $4)
        RETURNING *
        """,
        quiz_id, student_id, attempt_number, ip,
    )

    await log_activity(db, student_id, "start_quiz_attempt",
                       {"quiz_id": quiz_id, "attempt_id": str(attempt["id"])}, ip)

    extra_time = permission["extra_time_minutes"] if permission else 0
    effective_duration = (quiz["duration_minutes"] or 0) + extra_time

    return {
        "attempt_id": attempt["id"],
        "quiz_id": quiz_id,
        "attempt_number": attempt_number,
        "started_at": attempt["started_at"],
        "duration_minutes": effective_duration or None,
        "end_time_override": end_time,
    }


# ---- Submit answer ----

@router.post("/{attempt_id}/answers")
async def submit_answer(
    attempt_id: str,
    body: AnswerSubmit,
    current_user: dict = Depends(require_student),
    db: asyncpg.Connection = Depends(get_db),
):
    attempt = await _get_attempt_or_404(db, attempt_id)
    await _assert_attempt_owner(attempt, current_user)

    if attempt["status"] != "in_progress":
        raise HTTPException(status_code=409, detail="Attempt is not in progress")

    question_id = str(body.question_id)
    quiz_id = str(attempt["quiz_id"])

    # Verify question belongs to this quiz
    in_quiz = await db.fetchval(
        "SELECT id FROM public.quiz_questions WHERE quiz_id = $1 AND question_id = $2",
        quiz_id, question_id,
    )
    if not in_quiz:
        raise HTTPException(status_code=400, detail="Question not in this quiz")

    # Auto-grade
    grading = await auto_grade_answer(
        db, attempt_id, question_id,
        str(body.selected_option_id) if body.selected_option_id else None,
        body.answer_text,
    )

    # Upsert answer (allow re-answering during attempt)
    existing = await db.fetchrow(
        "SELECT id FROM public.student_answers WHERE attempt_id = $1 AND question_id = $2",
        attempt_id, question_id,
    )
    if existing:
        answer = await db.fetchrow(
            """
            UPDATE public.student_answers SET
              selected_option_id = $3, answer_text = $4, time_spent_seconds = $5,
              score_awarded = $6, is_correct = $7
            WHERE attempt_id = $1 AND question_id = $2
            RETURNING *
            """,
            attempt_id, question_id,
            str(body.selected_option_id) if body.selected_option_id else None,
            body.answer_text, body.time_spent_seconds,
            grading["score_awarded"], grading["is_correct"],
        )
    else:
        answer = await db.fetchrow(
            """
            INSERT INTO public.student_answers
              (attempt_id, question_id, selected_option_id, answer_text,
               time_spent_seconds, score_awarded, is_correct)
            VALUES ($1,$2,$3,$4,$5,$6,$7)
            RETURNING *
            """,
            attempt_id, question_id,
            str(body.selected_option_id) if body.selected_option_id else None,
            body.answer_text, body.time_spent_seconds,
            grading["score_awarded"], grading["is_correct"],
        )

    await update_question_analytics(
        db, question_id, quiz_id, grading["is_correct"], body.time_spent_seconds
    )

    return {**dict(answer), "message": "Answer recorded"}


# ---- Proctoring events ----

@router.post("/{attempt_id}/proctoring")
async def record_proctoring_event(
    attempt_id: str,
    body: ProctoringEvent,
    current_user: dict = Depends(require_student),
    db: asyncpg.Connection = Depends(get_db),
):
    attempt = await _get_attempt_or_404(db, attempt_id)
    await _assert_attempt_owner(attempt, current_user)

    if attempt["status"] != "in_progress":
        raise HTTPException(status_code=409, detail="Attempt is not in progress")

    if body.event_type == "tab_switch":
        new_val = attempt["tab_switch_count"] + body.count
        cheating = new_val >= CHEATING_TAB_SWITCH_THRESHOLD
        await db.execute(
            "UPDATE public.quiz_attempts SET tab_switch_count = $1, cheating_flag = cheating_flag OR $2 WHERE id = $3",
            new_val, cheating, attempt_id,
        )
    elif body.event_type == "fullscreen_exit":
        new_val = attempt["full_screen_violations"] + body.count
        cheating = new_val >= CHEATING_FULLSCREEN_THRESHOLD
        await db.execute(
            "UPDATE public.quiz_attempts SET full_screen_violations = $1, cheating_flag = cheating_flag OR $2 WHERE id = $3",
            new_val, cheating, attempt_id,
        )
    else:
        raise HTTPException(status_code=400, detail="Unknown event_type")

    return {"detail": "Proctoring event recorded"}


# ---- Submit attempt ----
@router.post("/{attempt_id}/submit", response_model=AttemptOut)
async def submit_attempt(
    attempt_id: str,
    time_spent_seconds: int = 0,
    current_user: dict = Depends(require_student),
    db: asyncpg.Connection = Depends(get_db),
):
    attempt = await _get_attempt_or_404(db, attempt_id)
    await _assert_attempt_owner(attempt, current_user)

    if attempt["status"] != "in_progress":
        raise HTTPException(status_code=409, detail="Attempt already submitted")

    # ----------------------------------------
    # AI evaluate short + descriptive answers
    # ----------------------------------------
    await auto_evaluate_descriptive_answers(db, attempt_id)

    # ----------------------------------------
    # Recalculate total after AI grading
    # ----------------------------------------
    total_score = await recalculate_attempt_score(db, attempt_id)

    # ----------------------------------------
    # Submit attempt
    # ----------------------------------------
    row = await db.fetchrow(
        """
        UPDATE public.quiz_attempts
        SET
          status = 'submitted',
          submitted_at = now(),
          total_score = $2,
          time_spent_seconds = $3
        WHERE id = $1
        RETURNING *
        """,
        attempt_id,
        total_score,
        time_spent_seconds,
    )

    # ----------------------------------------
    # Update student performance summary
    # ----------------------------------------
    await _update_performance_summary(
        db,
        str(current_user["id"]),
        str(attempt["quiz_id"])
    )

    # ----------------------------------------
    # Activity log
    # ----------------------------------------
    await log_activity(
        db,
        str(current_user["id"]),
        "submit_quiz_attempt",
        {
            "attempt_id": attempt_id,
            "score": str(total_score)
        }
    )

    return dict(row)

async def _update_performance_summary(db, student_id: str, quiz_id: str):
    """Upsert student_performance_summary after each attempt submission."""
    course_id = await db.fetchval(
        "SELECT course_id FROM public.quizzes WHERE id = $1", quiz_id
    )
    if not course_id:
        return

    await db.execute(
        """
        INSERT INTO public.student_performance_summary
          (student_id, course_id, quizzes_taken, average_score, highest_score, lowest_score)
        SELECT
          $1, $2,
          COUNT(*),
          AVG(a.total_score),
          MAX(a.total_score),
          MIN(a.total_score)
        FROM public.quiz_attempts a
        JOIN public.quizzes q ON q.id = a.quiz_id
        WHERE a.student_id = $1 AND q.course_id = $2 AND a.status IN ('submitted','evaluated')
        ON CONFLICT (student_id, course_id) DO UPDATE SET
          quizzes_taken = EXCLUDED.quizzes_taken,
          average_score = EXCLUDED.average_score,
          highest_score = EXCLUDED.highest_score,
          lowest_score  = EXCLUDED.lowest_score,
          last_updated  = now()
        """,
        student_id, str(course_id),
    )


# ---- View results ----

@router.get("/{attempt_id}", response_model=AttemptOut)
async def get_attempt(
    attempt_id: str,
    current_user: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_db),
):
    attempt = await _get_attempt_or_404(db, attempt_id)

    if current_user["role"] == "student":
        await _assert_attempt_owner(attempt, current_user)
        # Check if results are visible
        quiz = await db.fetchrow(
            "SELECT show_results_immediately FROM public.quizzes WHERE id = $1",
            str(attempt["quiz_id"]),
        )
        if not quiz["show_results_immediately"] and attempt["status"] != "evaluated":
            raise HTTPException(status_code=403, detail="Results not yet available")

    return dict(attempt)


@router.get("/{attempt_id}/answers")
async def get_attempt_answers(
    attempt_id: str,
    current_user: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_db),
):
    attempt = await _get_attempt_or_404(db, attempt_id)

    if current_user["role"] == "student":
        await _assert_attempt_owner(attempt, current_user)

        quiz = await db.fetchrow(
            "SELECT show_results_immediately FROM public.quizzes WHERE id = $1",
            str(attempt["quiz_id"]),
        )

        if not quiz["show_results_immediately"]:
            raise HTTPException(status_code=403, detail="Detailed results not yet available")

    rows = await db.fetch(
        """
        SELECT
            sa.question_id,
            sa.selected_option_id AS selected_answer,
            sa.is_correct,
            qb.question_text,
            qb.explanation,
            qo.id AS option_id,
            qo.option_text,
            qo.is_correct AS option_correct
        FROM public.student_answers sa
        JOIN public.question_bank qb ON qb.id = sa.question_id
        JOIN public.question_options qo ON qo.question_id = qb.id
        WHERE sa.attempt_id = $1
        ORDER BY qb.id
        """,
        attempt_id
    )

    question_map = {}

    for r in rows:
        qid = str(r["question_id"])

        if qid not in question_map:
            question_map[qid] = {
                "question_text": r["question_text"],
                "selected_answer": str(r["selected_answer"]) if r["selected_answer"] else None,
                "correct_answer": None,
                "is_correct": r["is_correct"],
                "options": [],
                "explanation": r["explanation"]
            }

        question_map[qid]["options"].append({
            "id": str(r["option_id"]),
            "option_text": r["option_text"]
        })

        if r["option_correct"]:
            question_map[qid]["correct_answer"] = str(r["option_id"])

    return list(question_map.values())

    # ---- Manual grading ----

@router.post("/{attempt_id}/grade", response_model=List[StudentAnswerOut])
async def manual_grade(
        attempt_id: str,
        grades: List[ManualGradeIn],
        current_user: dict = Depends(require_teacher_up),
        db: asyncpg.Connection = Depends(get_db),
    ):
        attempt = await _get_attempt_or_404(db, attempt_id)
        if attempt["status"] not in ("submitted", "evaluated"):
            raise HTTPException(status_code=409, detail="Cannot grade an in-progress attempt")

        async with db.transaction():
            for g in grades:
                await db.execute(
                    """
                    UPDATE public.student_answers SET
                    score_awarded = $2, is_correct = $3,
                    evaluated_by = $4, evaluated_at = now()
                    WHERE id = $1 AND attempt_id = $5
                    """,
                    str(g.answer_id), g.score_awarded, g.is_correct,
                    str(current_user["id"]), attempt_id,
                )

            total = await recalculate_attempt_score(db, attempt_id)
            await db.execute(
                "UPDATE public.quiz_attempts SET status = 'evaluated', total_score = $1 WHERE id = $2",
                total, attempt_id,
            )

        await _update_performance_summary(db, str(attempt["student_id"]), str(attempt["quiz_id"]))

        rows = await db.fetch(
            "SELECT * FROM public.student_answers WHERE attempt_id = $1", attempt_id
        )
        return [dict(r) for r in rows]


# ---- My attempts ----

@router.get("/my/history", response_model=List[AttemptOut])
async def my_attempt_history(
    quiz_id: str = None,
    current_user: dict = Depends(require_student),
    db: asyncpg.Connection = Depends(get_db),
):
    where = "student_id = $1"
    params: list = [str(current_user["id"])]
    if quiz_id:
        where += " AND quiz_id = $2"
        params.append(quiz_id)

    rows = await db.fetch(
        f"SELECT * FROM public.quiz_attempts WHERE {where} ORDER BY created_at DESC",
        *params,
    )
    return [dict(r) for r in rows]

