from fastapi import APIRouter, Depends, HTTPException
import asyncpg
from typing import List
from pydantic import BaseModel

from app.database import get_db
from app.dependencies import get_current_user, require_teacher_up, require_student
from app.schemas.assignments import (
    TeacherAssignmentCreate,
    TeacherAssignmentResponse,
    TeacherAssignmentUpdate,
    StudentAssignmentAnswerCreate,
    StudentAssignmentAnswerEvaluate,
    BulkAnswerCreate
)

router = APIRouter(prefix="/assignments", tags=["Assignments"])

# =====================================================
# UPGRADED CREATE ASSIGNMENT ROUTE
# Creates assignment + saves selected questions
# 1. CREATE ASSIGNMENT
# =====================================================

@router.post("/", response_model=TeacherAssignmentResponse)
async def create_assignment(
    payload: TeacherAssignmentCreate,
    current_user: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    async with db.transaction():

        # -----------------------------------------
        # 1. Create Assignment
        # -----------------------------------------
        assignment = await db.fetchrow(
            """
            INSERT INTO public.teacher_assignments (
                course_id,
                teacher_id,
                title,
                description,
                total_marks,
                passing_marks,
                start_time,
                due_time,
                allow_late_submission,
                published
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

        assignment_id = assignment["id"]

        # -----------------------------------------
        # 2. Insert Selected Questions
        # -----------------------------------------
        total_marks = 0

        for i, q in enumerate(payload.questions, start=1):

            # Validate only descriptive questions
            question = await db.fetchrow(
                """
                SELECT id, question_type
                FROM public.question_bank
                WHERE id = $1
                """,
                q.question_id,
            )

            if not question:
                raise HTTPException(
                    status_code=404,
                    detail=f"Question {q.question_id} not found"
                )

            if question["question_type"] not in ("descriptive", "short"):
                raise HTTPException(
                    status_code=400,
                    detail="Only descriptive/short questions allowed"
                )

            await db.execute(
                """
                INSERT INTO public.teacher_assignment_questions (
                    assignment_id,
                    question_id,
                    question_order,
                    marks
                )
                VALUES ($1,$2,$3,$4)
                """,
                assignment_id,
                q.question_id,
                q.question_order or i,
                q.marks,
            )

            total_marks += float(q.marks)

        # -----------------------------------------
        # 3. Auto Update Total Marks
        # -----------------------------------------
        await db.execute(
            """
            UPDATE public.teacher_assignments
            SET total_marks = $1
            WHERE id = $2
            """,
            total_marks,
            assignment_id,
        )

        # -----------------------------------------
        # 4. Return Final Row
        # -----------------------------------------
        final_row = await db.fetchrow(
            """
            SELECT *
            FROM public.teacher_assignments
            WHERE id = $1
            """,
            assignment_id,
        )

        return dict(final_row)


# =====================================================
# 2. LIST MY ASSIGNMENTS
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
# =====================================================
@router.get("/{assignment_id}")
async def get_assignment(
    assignment_id: str,
    current_user: dict = Depends(require_student),
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
        raise HTTPException(
            status_code=404,
            detail="Assignment not found"
        )

    role = current_user["role"]

    # -----------------------------------
    # Teacher / Admin / HOD
    # -----------------------------------
    if role in ["teacher", "admin", "hod"]:
        if (
            role == "teacher"
            and str(assignment["teacher_id"]) != str(current_user["id"])
        ):
            raise HTTPException(
                status_code=403,
                detail="Not allowed"
            )

    # -----------------------------------
    # Student
    # -----------------------------------
    elif role == "student":
        if not assignment["published"]:
            raise HTTPException(
                status_code=403,
                detail="Assignment not published"
            )

    else:
        raise HTTPException(
            status_code=403,
            detail="Not allowed"
        )

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
# 4. AVAILABLE ASSIGNMENTS
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
            student_id,
            status
        )
        VALUES ($1,$2,'in_progress')
        RETURNING id
        """,
        assignment_id,
        current_user["id"],
    )

    return {"submission_id": str(row["id"])}


# =====================================================
# 6. SAVE SINGLE ANSWER (SCHEMA ALIGNED)
# =====================================================
@router.post("/answers")
async def save_answer(
    payload: StudentAssignmentAnswerCreate,
    current_user: dict = Depends(require_student),
    db: asyncpg.Connection = Depends(get_db),
):
    await db.execute(
        """
        INSERT INTO public.student_assignment_answers (
            submission_id,
            question_id,
            answer_text,
            file_url
        )
        VALUES ($1,$2,$3,$4)

        ON CONFLICT (submission_id, question_id)
        DO UPDATE SET
            answer_text = EXCLUDED.answer_text,
            file_url = EXCLUDED.file_url,
            updated_at = now()
        """,
        payload.submission_id,
        payload.question_id,
        payload.answer_text,
        payload.file_url,
    )

    return {"success": True}


# =====================================================
# 7. SAVE BULK ANSWERS (FAST)
# =====================================================
@router.post("/answers/bulk")
async def save_bulk_answers(
    payload: BulkAnswerCreate,
    current_user: dict = Depends(require_student),
    db: asyncpg.Connection = Depends(get_db),
):
    async with db.transaction():
        for ans in payload.answers:
            await db.execute(
                """
                INSERT INTO public.student_assignment_answers (
                    submission_id,
                    question_id,
                    answer_text,
                    file_url
                )
                VALUES ($1,$2,$3,$4)

                ON CONFLICT (submission_id, question_id)
                DO UPDATE SET
                    answer_text = EXCLUDED.answer_text,
                    file_url = EXCLUDED.file_url,
                    updated_at = now()
                """,
                ans.submission_id,
                ans.question_id,
                ans.answer_text,
                ans.file_url,
            )

    return {"success": True}


# =====================================================
# 8. SUBMIT ASSIGNMENT
# =====================================================
@router.post("/submissions/{submission_id}/submit")
async def submit_assignment(
    submission_id: str,
    current_user: dict = Depends(require_student),
    db: asyncpg.Connection = Depends(get_db),
):
    result = await db.execute(
        """
        UPDATE public.student_assignment_submissions
        SET
            status = 'submitted',
            submitted_at = now()
        WHERE id = $1
          AND student_id = $2
        """,
        submission_id,
        current_user["id"],
    )

    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Submission not found")

    return {"success": True}


# =====================================================
# 9. TEACHER GRADING
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

# =====================================================
# UPDATE ASSIGNMENT (FULL EDIT ROUTE)
# PUT /assignments/{assignment_id}
# Updates metadata + replaces questions
# =====================================================

@router.put(
    "/{assignment_id}",
    response_model=TeacherAssignmentResponse
)
async def update_assignment(
    assignment_id: str,
    payload: TeacherAssignmentUpdate,
    current_user: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    async with db.transaction():

        # -----------------------------------------
        # 1. Check Exists
        # -----------------------------------------
        assignment = await db.fetchrow(
            """
            SELECT *
            FROM public.teacher_assignments
            WHERE id = $1
            """,
            assignment_id,
        )

        if not assignment:
            raise HTTPException(
                status_code=404,
                detail="Assignment not found"
            )

        # -----------------------------------------
        # 2. Owner Check
        # -----------------------------------------
        if str(assignment["teacher_id"]) != str(current_user["id"]):
            raise HTTPException(
                status_code=403,
                detail="Not allowed"
            )

        # -----------------------------------------
        # 3. Update Main Assignment
        # -----------------------------------------
        updated = await db.fetchrow(
            """
            UPDATE public.teacher_assignments
            SET
                course_id = COALESCE($2, course_id),
                title = COALESCE($3, title),
                description = COALESCE($4, description),
                total_marks = COALESCE($5, total_marks),
                passing_marks = COALESCE($6, passing_marks),
                start_time = COALESCE($7, start_time),
                due_time = COALESCE($8, due_time),
                allow_late_submission = COALESCE($9, allow_late_submission),
                published = COALESCE($10, published),
                updated_at = now()
            WHERE id = $1
            RETURNING *
            """,
            assignment_id,
            payload.course_id,
            payload.title,
            payload.description,
            payload.total_marks,
            payload.passing_marks,
            payload.start_time,
            payload.due_time,
            payload.allow_late_submission,
            payload.published,
        )

        # -----------------------------------------
        # 4. Replace Questions (if provided)
        # -----------------------------------------
        if hasattr(payload, "questions") and payload.questions is not None:

            # delete old mappings
            await db.execute(
                """
                DELETE FROM public.teacher_assignment_questions
                WHERE assignment_id = $1
                """,
                assignment_id,
            )

            total_marks = 0

            for i, q in enumerate(payload.questions, start=1):

                # validate question exists
                row = await db.fetchrow(
                    """
                    SELECT id, question_type
                    FROM public.question_bank
                    WHERE id = $1
                    """,
                    q.question_id,
                )

                if not row:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Question {q.question_id} not found"
                    )

                if row["question_type"] not in ("descriptive", "short"):
                    raise HTTPException(
                        status_code=400,
                        detail="Only descriptive/short questions allowed"
                    )

                await db.execute(
                    """
                    INSERT INTO public.teacher_assignment_questions (
                        assignment_id,
                        question_id,
                        question_order,
                        marks
                    )
                    VALUES ($1,$2,$3,$4)
                    """,
                    assignment_id,
                    q.question_id,
                    q.question_order or i,
                    q.marks,
                )

                total_marks += float(q.marks)

            # update total marks automatically
            updated = await db.fetchrow(
                """
                UPDATE public.teacher_assignments
                SET total_marks = $2,
                    updated_at = now()
                WHERE id = $1
                RETURNING *
                """,
                assignment_id,
                total_marks,
            )

        return dict(updated)


# =====================================================
# DELETE ASSIGNMENT
# DELETE /assignments/{assignment_id}
# =====================================================

@router.delete("/{assignment_id}")
async def delete_assignment(
    assignment_id: str,
    current_user: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    assignment = await db.fetchrow(
        """
        SELECT id, teacher_id
        FROM public.teacher_assignments
        WHERE id = $1
        """,
        assignment_id,
    )

    if not assignment:
        raise HTTPException(
            status_code=404,
            detail="Assignment not found"
        )

    if str(assignment["teacher_id"]) != str(current_user["id"]):
        raise HTTPException(
            status_code=403,
            detail="Not allowed"
        )

    await db.execute(
        """
        DELETE FROM public.teacher_assignments
        WHERE id = $1
        """,
        assignment_id,
    )

    return {
        "success": True,
        "message": "Assignment deleted"
    }