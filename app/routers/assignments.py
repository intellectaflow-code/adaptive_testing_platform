# app/routers/assignments.py

from fastapi import APIRouter, Depends, HTTPException
import asyncpg

from app.database import get_db
from app.dependencies import require_teacher_up, require_student
from app.schemas.assignments import (
    TeacherAssignmentCreate,
    TeacherAssignmentResponse,
    StudentAssignmentAnswerEvaluate,
)

router = APIRouter(prefix="/assignments", tags=["Assignments"])


# =====================================================
# 1. CREATE ASSIGNMENT
# POST /assignments
# =====================================================
@router.post("/", response_model=TeacherAssignmentResponse)
async def create_assignment(
    payload: TeacherAssignmentCreate,
    current_user: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    row = await db.fetchrow(
        """
        INSERT INTO public.teacher_assignments (
            course_id, teacher_id, title, description,
            total_marks, passing_marks,
            start_time, due_time,
            allow_late_submission, published
        )
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
        RETURNING *
        """,
        payload.course_id,
        current_user["id"],
        payload.title,
        payload.description,
        payload.total_marks,
        payload.passing_marks,
        payload.start_time,
        payload.due_time,
        payload.allow_late_submission,
        payload.published,
    )

    return dict(row)


# =====================================================
# 2. LIST MY ASSIGNMENTS
# GET /assignments/my
# =====================================================
@router.get("/my")
async def list_my_assignments(
    current_user: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    rows = await db.fetch(
        """
        SELECT *
        FROM public.teacher_assignments
        WHERE teacher_id = $1
        ORDER BY created_at DESC
        """,
        current_user["id"],
    )

    return [dict(r) for r in rows]


# =====================================================
# 3. GET ASSIGNMENT DETAILS
# GET /assignments/{id}
# =====================================================
@router.get("/{assignment_id}")
async def get_assignment(
    assignment_id: str,
    current_user: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    assignment = await db.fetchrow(
        """
        SELECT *
        FROM public.teacher_assignments
        WHERE id = $1
        """,
        assignment_id,
    )

    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    questions = await db.fetch(
        """
        SELECT
            taq.*,
            qb.question_text,
            qb.question_type
        FROM public.teacher_assignment_questions taq
        JOIN public.question_bank qb
            ON qb.id = taq.question_id
        WHERE taq.assignment_id = $1
        ORDER BY taq.question_order
        """,
        assignment_id,
    )

    return {
        **dict(assignment),
        "questions": [dict(q) for q in questions]
    }


# =====================================================
# 4. AVAILABLE ASSIGNMENTS FOR STUDENTS
# GET /assignments/available
# =====================================================
@router.get("/available/list")
async def available_assignments(
    current_user: dict = Depends(require_student),
    db: asyncpg.Connection = Depends(get_db),
):
    rows = await db.fetch(
        """
        SELECT *
        FROM public.teacher_assignments
        WHERE published = TRUE
        ORDER BY due_time ASC NULLS LAST
        """
    )

    return [dict(r) for r in rows]


# =====================================================
# 5. START SUBMISSION
# POST /assignments/{id}/start
# =====================================================
@router.post("/{assignment_id}/start")
async def start_submission(
    assignment_id: str,
    current_user: dict = Depends(require_student),
    db: asyncpg.Connection = Depends(get_db),
):
    existing = await db.fetchrow(
        """
        SELECT id
        FROM public.student_assignment_submissions
        WHERE assignment_id = $1
          AND student_id = $2
        """,
        assignment_id,
        current_user["id"],
    )

    if existing:
        return {"submission_id": str(existing["id"])}

    row = await db.fetchrow(
        """
        INSERT INTO public.student_assignment_submissions (
            assignment_id,
            student_id
        )
        VALUES ($1,$2)
        RETURNING id
        """,
        assignment_id,
        current_user["id"],
    )

    return {"submission_id": str(row["id"])}


# =====================================================
# 6. SAVE ANSWER
# POST /assignments/submissions/{id}/answers
# =====================================================
@router.post("/submissions/{submission_id}/answers")
async def save_answer(
    submission_id: str,
    question_id: str,
    answer_text: str,
    current_user: dict = Depends(require_student),
    db: asyncpg.Connection = Depends(get_db),
):
    await db.execute(
        """
        INSERT INTO public.student_assignment_answers (
            submission_id,
            question_id,
            answer_text
        )
        VALUES ($1,$2,$3)

        ON CONFLICT (submission_id, question_id)
        DO UPDATE SET
            answer_text = EXCLUDED.answer_text,
            updated_at = now()
        """,
        submission_id,
        question_id,
        answer_text,
    )

    return {"success": True}


# =====================================================
# 7. SUBMIT ASSIGNMENT
# POST /assignments/submissions/{id}/submit
# =====================================================
@router.post("/submissions/{submission_id}/submit")
async def submit_assignment(
    submission_id: str,
    current_user: dict = Depends(require_student),
    db: asyncpg.Connection = Depends(get_db),
):
    await db.execute(
        """
        UPDATE public.student_assignment_submissions
        SET
            status = 'submitted',
            submitted_at = now()
        WHERE id = $1
        """,
        submission_id,
    )

    return {"success": True}


# =====================================================
# 8. TEACHER GRADE ANSWER
# POST /assignments/answers/{id}/grade
# =====================================================
@router.post("/answers/{answer_id}/grade")
async def grade_answer(
    answer_id: str,
    payload: StudentAssignmentAnswerEvaluate,
    current_user: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    await db.execute(
        """
        UPDATE public.student_assignment_answers
        SET
            score_awarded = $1,
            feedback = $2,
            evaluated_by = $3,
            evaluated_at = now()
        WHERE id = $4
        """,
        payload.score_awarded,
        payload.feedback,
        current_user["id"],
        answer_id,
    )

    return {"success": True}