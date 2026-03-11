from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
import asyncpg
from pydantic import BaseModel
from app.services.groq_client import generate_ai_quiz

from app.database import get_db
from app.dependencies import get_current_user, require_teacher_up
from app.schemas.questions import (
    QuestionCreate, QuestionUpdate, QuestionOut,
)
from app.services.activity import log_activity

router = APIRouter(prefix="/questions", tags=["Question Bank"])


async def _get_question_or_404(db, question_id: str):
    row = await db.fetchrow(
        "SELECT * FROM public.question_bank WHERE id = $1 AND is_deleted = false",
        question_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Question not found")
    return row


async def _fetch_options(db, question_id: str):
    rows = await db.fetch(
        "SELECT * FROM public.question_options WHERE question_id = $1", question_id
    )
    return [dict(r) for r in rows]


async def _fetch_tags(db, question_id: str):
    rows = await db.fetch(
        "SELECT tag FROM public.question_tags WHERE question_id = $1", question_id
    )
    return [r["tag"] for r in rows]


async def _enrich_question(db, question: dict) -> dict:
    question_dict = dict(question)
    q_id = question_dict['id']

    # New Logic: Check if linked to any published quiz
    is_published = await db.fetchval("""
        SELECT EXISTS (
            SELECT 1 
            FROM public.quiz_questions qq
            JOIN public.quizzes q ON qq.quiz_id = q.id
            WHERE qq.question_id = $1 AND q.is_published = true
        )
    """, q_id)

    # Attach the flag so the Frontend can see it
    question_dict['is_locked'] = is_published
    question_dict["options"] = await _fetch_options(db, str(question_dict["id"]))
    question_dict["tags"] = await _fetch_tags(db, str(question_dict["id"]))
    return question_dict



@router.post("", response_model=QuestionOut, status_code=201)
async def create_question(
    body: QuestionCreate,
    current_user: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    async with db.transaction():
        q = await db.fetchrow(
            """
            INSERT INTO public.question_bank
              (course_id, created_by, question_text, question_type, difficulty,
               topic, marks, negative_marks, explanation, media_url)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            RETURNING *
            """,
            str(body.course_id), str(current_user["id"]),
            body.question_text, body.question_type, body.difficulty,
            body.topic, body.marks, body.negative_marks,
            body.explanation, body.media_url,
        )
        q_id = str(q["id"])

        for opt in body.options:
            await db.execute(
                "INSERT INTO public.question_options (question_id, option_text, media_url, is_correct) VALUES ($1,$2,$3,$4)",
                q_id, opt.option_text, opt.media_url, opt.is_correct,
            )

        for tag in body.tags:
            await db.execute(
                "INSERT INTO public.question_tags (question_id, tag) VALUES ($1,$2)",
                q_id, tag.lower().strip(),
            )

    await log_activity(db, str(current_user["id"]), "create_question", {"question_id": q_id})
    return await _enrich_question(db, q)


@router.get("", response_model=List[QuestionOut])
async def list_questions(
    course_id: Optional[str] = Query(None),
    difficulty: Optional[str] = Query(None),
    topic: Optional[str] = Query(None),
    question_type: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    skip: int = 0,
    limit: int = 50,
    current_user: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    where_parts = ["q.is_deleted = false", "q.is_active = true", "q.created_by = $1"]
    params: list = [str(current_user["id"])]
    idx = 2

    if course_id:
        where_parts.append(f"q.course_id = ${idx}"); params.append(course_id); idx += 1
    if difficulty:
        where_parts.append(f"q.difficulty = ${idx}"); params.append(difficulty); idx += 1
    if topic:
        where_parts.append(f"q.topic ILIKE ${idx}"); params.append(f"%{topic}%"); idx += 1
    if question_type:
        where_parts.append(f"q.question_type = ${idx}"); params.append(question_type); idx += 1

    tag_join = ""
    if tag:
        tag_join = "JOIN public.question_tags qt ON qt.question_id = q.id"
        where_parts.append(f"qt.tag = ${idx}"); params.append(tag.lower()); idx += 1

    where = " AND ".join(where_parts)
    rows = await db.fetch(
        f"""
        SELECT DISTINCT q.* FROM public.question_bank q {tag_join}
        WHERE {where}
        ORDER BY q.created_at DESC
        LIMIT ${idx} OFFSET ${idx+1}
        """,
        *params, limit, skip,
    )

    result = []
    for row in rows:
        result.append(await _enrich_question(db, row))
    return result



@router.get("/{question_id}", response_model=QuestionOut)
async def get_question(
    question_id: str,
    _: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    q = await _get_question_or_404(db, question_id)
    return await _enrich_question(db, q)

@router.put("/{question_id}", response_model=QuestionOut)
async def update_question(
    question_id: str,
    body: QuestionUpdate,
    current_user: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    # FIX: Assign the result to q
    q = await _get_question_or_404(db, question_id)
    
    # Check if locked
    if q.get('is_published'):
        raise HTTPException(status_code=403, detail="Cannot edit a published question.")

    updates = body.model_dump(exclude_none=True, exclude={"options", "tags"})

    if updates:
        set_clause = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(updates.keys()))
        await db.execute(
            f"""
            UPDATE public.question_bank
            SET {set_clause}, updated_at = now(), version = version + 1
            WHERE id = $1
            """,
            question_id, *updates.values(),
        )

    # Handle Options
    if body.options is not None:
        async with db.transaction():
            await db.execute(
                "DELETE FROM public.question_options WHERE question_id = $1", question_id
            )
            for opt in body.options:
                await db.execute(
                    "INSERT INTO public.question_options (question_id, option_text, media_url, is_correct) VALUES ($1,$2,$3,$4)",
                    question_id, opt.option_text, opt.media_url, opt.is_correct,
                )

    # Handle Tags
    if body.tags is not None:
        async with db.transaction():
            await db.execute(
                "DELETE FROM public.question_tags WHERE question_id = $1", question_id
            )
            for tag in body.tags:
                await db.execute(
                    "INSERT INTO public.question_tags (question_id, tag) VALUES ($1,$2)",
                    question_id, tag.lower().strip(),
                )

    # Final fetch to return updated data
    final_q = await _get_question_or_404(db, question_id)
    return await _enrich_question(db, final_q)


@router.delete("/{question_id}", status_code=204)
async def delete_question(
    question_id: str,
    current_user: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    await db.execute(
        "UPDATE public.question_bank SET is_deleted = true, updated_at = now() WHERE id = $1",
        question_id,
    )
    await log_activity(db, str(current_user["id"]), "delete_question", {"question_id": question_id})


@router.post("/{question_id}/duplicate", response_model=QuestionOut, status_code=201)
async def duplicate_question(
    question_id: str,
    current_user: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    """Duplicate a question (useful for variations)."""
    original = await _enrich_question(db, await _get_question_or_404(db, question_id))

    async with db.transaction():
        new_q = await db.fetchrow(
            """
            INSERT INTO public.question_bank
              (course_id, created_by, question_text, question_type, difficulty,
               topic, marks, negative_marks, explanation, media_url)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) RETURNING *
            """,
            str(original["course_id"]), str(current_user["id"]),
            f"[Copy] {original['question_text']}", original["question_type"],
            original["difficulty"], original["topic"], original["marks"],
            original["negative_marks"], original["explanation"], original["media_url"],
        )
        new_id = str(new_q["id"])
        for opt in original["options"]:
            await db.execute(
                "INSERT INTO public.question_options (question_id, option_text, media_url, is_correct) VALUES ($1,$2,$3,$4)",
                new_id, opt["option_text"], opt.get("media_url"), opt["is_correct"],
            )
        for tag in original["tags"]:
            await db.execute(
                "INSERT INTO public.question_tags (question_id, tag) VALUES ($1,$2)",
                new_id, tag,
            )

    return await _enrich_question(db, new_q)

