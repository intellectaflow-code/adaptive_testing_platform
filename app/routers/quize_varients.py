from fastapi import APIRouter, Depends, HTTPException
from typing import List
from uuid import UUID
import asyncpg

from app.schemas.quizzes import AddToPoolRequest, GenerateRequest, QuizTemplateCreate, QuizTemplateOut
from ..dependencies import get_db, require_teacher

router = APIRouter(prefix="/api/v1/quiz-variants", tags=["Quiz Variants"])

@router.post("/templates", response_model=QuizTemplateOut)
async def create_template(body: QuizTemplateCreate, db = Depends(get_db), user = Depends(require_teacher)):
    row = await db.fetchrow("""
        INSERT INTO quiz_templates (title, total_versions, questions_per_quiz, teacher_id)
        VALUES ($1, $2, $3, $4) RETURNING *
    """, body.title, body.total_versions, body.questions_per_quiz, user['id'])
    return dict(row)

@router.post("/templates/{template_id}/pool")
async def add_questions_to_pool(template_id: UUID, body: AddToPoolRequest, db = Depends(get_db)):
    # Batch insert into the pool
    data = [(template_id, item.question_id, item.is_anchor) for item in body.questions]
    await db.executemany("""
        INSERT INTO template_pool (template_id, question_id, is_anchor)
        VALUES ($1, $2, $3)
        ON CONFLICT DO NOTHING
    """, data)
    return {"message": "Questions added to pool"}

@router.post("/templates/{template_id}/generate")
async def generate_and_assign(template_id: UUID, body: GenerateRequest, db = Depends(get_db)):
    """
    Calls the Supabase RPC/Postgres Function to handle complex 
    randomization and assignment in a single transaction.
    """
    try:
        # We execute the RPC function via standard SQL
        result = await db.fetchval(
            "SELECT generate_quiz_variants($1, $2)", 
            template_id, body.student_ids
        )
        return {"status": "success", "detail": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))