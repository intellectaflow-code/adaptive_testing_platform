import os
import json
import re
import asyncpg
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

client = AsyncOpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1",
)


async def evaluate_descriptive_answer(
    question_text: str,
    topic: str,
    difficulty: str,
    student_answer: str,
    max_marks: float,
):
    prompt = f"""
You are a strict but fair university evaluator.

Question:
{question_text}

Topic:
{topic}

Difficulty:
{difficulty}

Maximum Marks:
{max_marks}

Student Answer:
{student_answer}

Evaluate based on:
1. Correctness
2. Completeness
3. Relevance
4. Clarity

Return ONLY valid JSON:

{{
  "score": number,
  "feedback": "short feedback"
}}
"""

    response = await client.chat.completions.create(
        model="llama-3.1-8b-instant",
        max_tokens=300,
        messages=[
            {
                "role": "system",
                "content": "You are a fair academic evaluator. Return ONLY valid JSON."
            },
            {
                "role": "user",
                "content": prompt
            },
        ],
        temperature=0.2,
    )

    content = response.choices[0].message.content.strip()

    # Strip markdown fences
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)

    # Extract JSON object
    json_match = re.search(r"\{.*\}", content, re.DOTALL)
    if json_match:
        content = json_match.group(0)

    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"AI returned invalid JSON: {e}\nRaw: {content[:300]}")

    score = float(data.get("score", 0))
    feedback = data.get("feedback", "")

    if score < 0:
        score = 0

    if score > max_marks:
        score = max_marks

    return {
        "score": score,
        "feedback": feedback
    }


async def auto_evaluate_descriptive_answers(
    db: asyncpg.Connection,
    attempt_id: str
):
    """
    Auto evaluate all short/descriptive answers
    for one attempt.
    """

    rows = await db.fetch(
        """
        SELECT
            sa.id AS answer_id,
            sa.answer_text,
            qb.id AS question_id,
            qb.question_text,
            qb.question_type,
            qb.topic,
            qb.difficulty,
            qb.marks

        FROM public.student_answers sa
        JOIN public.question_bank qb
            ON qb.id = sa.question_id

        WHERE sa.attempt_id = $1
          AND qb.question_type IN ('short', 'descriptive')
          AND sa.answer_text IS NOT NULL
          AND TRIM(sa.answer_text) <> ''
        """,
        attempt_id
    )

    for row in rows:
        try:
            result = await evaluate_descriptive_answer(
                question_text=row["question_text"],
                topic=row["topic"] or "",
                difficulty=row["difficulty"] or "medium",
                student_answer=row["answer_text"],
                max_marks=float(row["marks"]),
            )

            await db.execute(
                """
                UPDATE public.student_answers
                SET
                    score_awarded = $1,
                    is_correct = CASE
                        WHEN $1 >= (
                            SELECT marks * 0.4
                            FROM public.question_bank
                            WHERE id = $2
                        )
                        THEN TRUE
                        ELSE FALSE
                    END,
                    evaluated_at = NOW()
                WHERE id = $3
                """,
                result["score"],
                str(row["question_id"]),
                str(row["answer_id"])
            )

        except Exception:
            await db.execute(
                """
                UPDATE public.student_answers
                SET
                    score_awarded = 0,
                    is_correct = FALSE,
                    evaluated_at = NOW()
                WHERE id = $1
                """,
                str(row["answer_id"])
            )