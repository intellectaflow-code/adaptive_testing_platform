import json
import re
import asyncpg

# USE EXISTING WORKING CLIENT
from app.services.groq_client import client


async def evaluate_descriptive_answer(
    question_text: str,
    student_answer: str,
    max_marks: float,
):
    prompt = f"""
You are a strict but fair university evaluator.

Question:
{question_text}

Maximum Marks:
{max_marks}

Student Answer:
{student_answer}

Evaluate based on:
1. Correctness
2. Completeness
3. Relevance
4. Clarity

Return ONLY JSON:

{{
  "score": number
}}
"""

    response = await client.chat.completions.create(
        model="llama-3.1-8b-instant",
        max_tokens=120,
        temperature=0.2,
        messages=[
            {
                "role": "system",
                "content": "Return only valid JSON."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
    )

    content = response.choices[0].message.content.strip()

    # Clean markdown
    content = re.sub(r"^```(?:json)?", "", content).strip()
    content = re.sub(r"```$", "", content).strip()

    # Extract JSON
    match = re.search(
        r"\{.*\}",
        content,
        re.DOTALL
    )

    if match:
        content = match.group(0)

    data = json.loads(content)

    score = float(data.get("score", 0))

    if score < 0:
        score = 0

    if score > max_marks:
        score = max_marks

    return score


async def auto_evaluate_assignment(
    db: asyncpg.Connection,
    submission_id: str
):
    rows = await db.fetch(
        """
        SELECT
            ans.id,
            ans.answer_text,
            qb.question_text,
            taq.marks

        FROM public.student_assignment_answers ans

        JOIN public.question_bank qb
          ON qb.id = ans.question_id

        JOIN public.student_assignment_submissions s
          ON s.id = ans.submission_id

        JOIN public.teacher_assignment_questions taq
          ON taq.assignment_id = s.assignment_id
         AND taq.question_id = ans.question_id

        WHERE ans.submission_id = $1
        """,
        submission_id
    )

    total = 0

    for row in rows:
        try:
            score = await evaluate_descriptive_answer(
                question_text=row["question_text"],
                student_answer=row["answer_text"] or "",
                max_marks=float(row["marks"]),
            )

            total += score

            await db.execute(
                """
                UPDATE public.student_assignment_answers
                SET
                    score_awarded = $1,
                    evaluated_at = now()
                WHERE id = $2
                """,
                score,
                row["id"]
            )

        except Exception as e:
            print("AI Evaluation Error:", e)

            await db.execute(
                """
                UPDATE public.student_assignment_answers
                SET
                    score_awarded = 0,
                    evaluated_at = now()
                WHERE id = $1
                """,
                row["id"]
            )

    await db.execute(
        """
        UPDATE public.student_assignment_submissions
        SET
            total_score = $1,
            status = 'evaluated',
            updated_at = now()
        WHERE id = $2
        """,
        total,
        submission_id
    )