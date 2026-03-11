import json
from fastapi import APIRouter, Depends, HTTPException
from typing import List
import asyncpg

from app.database import get_db
from app.dependencies import get_current_user

from app.schemas.ai_quiz import (
    AIQuizAttemptCreate,
    AIQuizAttemptOut,
    AIQuizSubmit,
    AIQuizAnswerCreate,
    AIExplainRequest
)

from app.services.groq_client import (
    generate_ai_quiz,
    generate_ai_explanation
)

router = APIRouter(prefix="/ai-quiz", tags=["AI Quiz"])


# -------------------------------------------------------
# START AI QUIZ
# -------------------------------------------------------

@router.post("/start")
async def start_ai_quiz(
    body: AIQuizAttemptCreate,
    current_user: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_db),
):
    if current_user["role"] != "student":
        raise HTTPException(status_code=403, detail="Only students can start AI quizzes")

    async with db.transaction():

        # Create attempt
        attempt = await db.fetchrow(
            """
            INSERT INTO public.ai_quiz_attempts
            (student_id, topic, difficulty, total_questions)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            str(current_user["id"]),
            body.topic,
            body.difficulty,
            body.total_questions,
        )

        attempt_id = attempt["id"]

        # Generate questions from AI
        questions = await generate_ai_quiz(
            topic=body.topic,
            difficulty=body.difficulty,
            num_questions=body.total_questions,
        )

        safe_questions = []

        for q in questions:
            row = await db.fetchrow(
                """
                INSERT INTO public.ai_quiz_questions
                (attempt_id, question_text, options, correct_answer)
                VALUES ($1, $2, $3::jsonb, $4)
                RETURNING id
                """,
                attempt_id,
                q["question_text"],
                json.dumps(q["options"]),
                q["correct_answer"],
            )

            safe_questions.append(
                {
                    "question_id": row["id"],
                    "question_text": q["question_text"],
                    "options": q["options"],
                }
            )

    return {
        "attempt_id": attempt_id,
        "questions": safe_questions,
    }


# -------------------------------------------------------
# SUBMIT AI QUIZ
# -------------------------------------------------------

@router.post("/submit")
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

            q = await db.fetchrow(
                """
                SELECT correct_answer, question_text, options
                FROM public.ai_quiz_questions
                WHERE id = $1
                """,
                ans.question_id,
            )

            if not q:
                continue

            is_correct = (
                ans.selected_answer is not None
                and ans.selected_answer == q["correct_answer"]
            )

            if is_correct:
                correct_count += 1

            explanation = await generate_ai_explanation(
                question_text=q["question_text"],
                options=json.loads(q["options"])
                if isinstance(q["options"], str)
                else q["options"],
                correct_answer=q["correct_answer"],
            )

            await db.execute(
                """
                INSERT INTO public.ai_quiz_answers
                (attempt_id, question_id, selected_answer, is_correct, explanation)
                VALUES ($1, $2, $3, $4, $5)
                """,
                body.attempt_id,
                ans.question_id,
                ans.selected_answer,
                is_correct,
                explanation,
            )

        total_questions = len(body.answers)

        await db.execute(
            """
            UPDATE public.ai_quiz_attempts
            SET correct_answers = $1,
                score = $2
            WHERE id = $3
            """,
            correct_count,
            float(correct_count),
            body.attempt_id,
        )

    return {
        "attempt_id": body.attempt_id,
        "correct_answers": correct_count,
        "total_questions": total_questions,
        "score": correct_count,
    }


# -------------------------------------------------------
# AI QUIZ HISTORY
# -------------------------------------------------------

@router.get("/history", response_model=List[AIQuizAttemptOut])
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

    return rows


# -------------------------------------------------------
# GET ANSWERS + EXPLANATIONS
# -------------------------------------------------------

@router.get("/{attempt_id}/answers")
async def get_ai_quiz_answers(
    attempt_id: str,
    current_user: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_db),
):

    rows = await db.fetch(
        """
        SELECT
            q.id as question_id,
            q.question_text,
            q.options,
            a.selected_answer,
            q.correct_answer,
            a.is_correct,
            a.explanation
        FROM public.ai_quiz_answers a
        JOIN public.ai_quiz_questions q
        ON q.id = a.question_id
        WHERE a.attempt_id = $1
        """,
        attempt_id,
    )

    result = []

    for r in rows:
        ans = dict(r)

        if isinstance(ans["options"], str):
            ans["options"] = json.loads(ans["options"])

        result.append(ans)

    return result


# -------------------------------------------------------
# GENERATE EXPLANATION (ON DEMAND)
# -------------------------------------------------------

@router.post("/explain")
async def explain_ai_question(body: AIExplainRequest):

    explanation = await generate_ai_explanation(
        question_text=body.question_text,
        options=body.options,
        correct_answer=body.correct_answer,
    )

    return {
        "explanation": explanation
    }