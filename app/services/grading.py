import asyncpg
import logging
from typing import Optional
from decimal import Decimal

logger = logging.getLogger("quiz.grading")


async def auto_grade_answer(
    db: asyncpg.Connection,
    attempt_id: str,
    question_id: str,
    selected_option_id: Optional[str],
    answer_text: Optional[str],
) -> dict:
    """
    Auto-grades MCQ single, MCQ multiple, and true/false questions.
    Short / descriptive are left with is_correct=None, score=0 (needs manual grading).

    Returns: {"is_correct": bool|None, "score_awarded": Decimal}
    """
    question = await db.fetchrow(
        """
        SELECT question_type, marks, negative_marks
        FROM public.question_bank
        WHERE id = $1 AND is_deleted = false
        """,
        question_id,
    )
    if not question:
        logger.warning("grading: question %s not found", question_id)
        return {"is_correct": None, "score_awarded": Decimal("0")}

    q_type   = question["question_type"]
    marks    = Decimal(str(question["marks"]))
    neg      = Decimal(str(question["negative_marks"] or 0))

    # ── mcq_single / true_false ──────────────────────────────────────────────
    if q_type in ("mcq_single", "true_false"):
        if not selected_option_id:
            logger.debug("grading: no option selected for %s – 0 marks", question_id)
            return {"is_correct": False, "score_awarded": Decimal("0")}

        option = await db.fetchrow(
            "SELECT is_correct FROM public.question_options WHERE id = $1",
            selected_option_id,
        )
        if not option:
            return {"is_correct": False, "score_awarded": Decimal("0")}

        if option["is_correct"]:
            logger.debug("grading: correct – +%s marks", marks)
            return {"is_correct": True, "score_awarded": marks}
        else:
            deduction = max(Decimal("0"), neg)
            logger.debug("grading: wrong – -%s marks", deduction)
            return {"is_correct": False, "score_awarded": -deduction}

    # ── mcq_multiple ─────────────────────────────────────────────────────────
    elif q_type == "mcq_multiple":
        # Each option is submitted as a separate student_answer row.
        # Award partial credit per correct option.
        if not selected_option_id:
            return {"is_correct": False, "score_awarded": Decimal("0")}

        option = await db.fetchrow(
            "SELECT is_correct FROM public.question_options WHERE id = $1",
            selected_option_id,
        )
        if not option:
            return {"is_correct": False, "score_awarded": Decimal("0")}

        if option["is_correct"]:
            correct_count = await db.fetchval(
                "SELECT COUNT(*) FROM public.question_options WHERE question_id=$1 AND is_correct=true",
                question_id,
            )
            partial = marks / Decimal(str(max(correct_count, 1)))
            return {"is_correct": True, "score_awarded": partial}
        else:
            return {"is_correct": False, "score_awarded": Decimal("0")}

    # ── short / descriptive → manual grading ─────────────────────────────────
    logger.debug("grading: type=%s needs manual grading", q_type)
    return {"is_correct": None, "score_awarded": Decimal("0")}


async def recalculate_attempt_score(
    db: asyncpg.Connection,
    attempt_id: str,
) -> Decimal:
    """Sum all score_awarded rows for an attempt and save to quiz_attempts."""
    total = await db.fetchval(
        "SELECT COALESCE(SUM(score_awarded), 0) FROM public.student_answers WHERE attempt_id = $1",
        attempt_id,
    )
    total = Decimal(str(total))
    await db.execute(
        "UPDATE public.quiz_attempts SET total_score = $1 WHERE id = $2",
        total, attempt_id,
    )
    logger.debug("recalculated score for attempt %s → %s", attempt_id, total)
    return total


async def update_question_analytics(
    db: asyncpg.Connection,
    question_id: str,
    quiz_id: str,
    is_correct: Optional[bool],
    time_spent: Optional[int],
):
    """Upsert running analytics after each answer is saved."""
    try:
        await db.execute(
            """
            INSERT INTO public.question_analytics
                (question_id, quiz_id, total_attempts, correct_count,
                 incorrect_count, average_time_seconds)
            VALUES ($1, $2, 1,
                CASE WHEN $3 = true  THEN 1 ELSE 0 END,
                CASE WHEN $3 = false THEN 1 ELSE 0 END,
                COALESCE($4, 0))
            ON CONFLICT (question_id, quiz_id) DO UPDATE SET
                total_attempts       = question_analytics.total_attempts + 1,
                correct_count        = question_analytics.correct_count
                                       + CASE WHEN $3 = true  THEN 1 ELSE 0 END,
                incorrect_count      = question_analytics.incorrect_count
                                       + CASE WHEN $3 = false THEN 1 ELSE 0 END,
                average_time_seconds = (
                    question_analytics.average_time_seconds
                    * question_analytics.total_attempts
                    + COALESCE($4, 0)
                ) / (question_analytics.total_attempts + 1),
                updated_at = now()
            """,
            question_id, quiz_id, is_correct, time_spent,
        )
    except Exception as e:
        logger.warning("question_analytics update failed (non-fatal): %s", e)

