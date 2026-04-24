from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from typing import List
import asyncpg
import uuid as uuid_lib

from app.database import get_db
from app.dependencies import get_current_user, require_teacher_up, require_student
from app.services.supabase_client import get_supabase  # ← same as profiles.py
from app.schemas.assignments import (
    TeacherAssignmentCreate,
    TeacherAssignmentResponse,
    TeacherAssignmentUpdate,
    StudentAssignmentAnswerCreate,
    StudentAssignmentAnswerEvaluate,
    BulkAnswerCreate
)
from app.services.descriptive_ai import auto_evaluate_assignment


router = APIRouter(prefix="/assignments", tags=["Assignments"])

# =====================================================
# 1. CREATE ASSIGNMENT
# =====================================================

@router.post("/", response_model=TeacherAssignmentResponse)
async def create_assignment(
    payload: TeacherAssignmentCreate,
    current_user: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    async with db.transaction():

        assignment = await db.fetchrow(
            """
            INSERT INTO public.teacher_assignments (
                course_id, teacher_id, title, description,
                total_marks, passing_marks, start_time, due_time,
                allow_late_submission, published
            )
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            RETURNING *
            """,
            payload.course_id, current_user["id"], payload.title,
            payload.description, payload.total_marks, payload.passing_marks,
            payload.start_time, payload.due_time,
            payload.allow_late_submission, payload.published,
        )

        assignment_id = assignment["id"]
        total_marks   = 0

        for i, q in enumerate(payload.questions, start=1):

            question = await db.fetchrow(
                "SELECT id, question_type FROM public.question_bank WHERE id = $1",
                q.question_id,
            )

            if not question:
                raise HTTPException(status_code=404, detail=f"Question {q.question_id} not found")

            if question["question_type"] not in ("descriptive", "short"):
                raise HTTPException(status_code=400, detail="Only descriptive/short questions allowed")

            await db.execute(
                """
                INSERT INTO public.teacher_assignment_questions
                    (assignment_id, question_id, question_order, marks)
                VALUES ($1,$2,$3,$4)
                """,
                assignment_id, q.question_id, q.question_order or i, q.marks,
            )

            total_marks += float(q.marks)

        final_row = await db.fetchrow(
            """
            UPDATE public.teacher_assignments SET total_marks = $1 WHERE id = $2 RETURNING *
            """,
            total_marks, assignment_id,
        )

        return dict(final_row)


# =====================================================
# 2. LIST MY ASSIGNMENTS (teacher)
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
    current_user: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_db),
):
    assignment = await db.fetchrow(
        "SELECT * FROM public.teacher_assignments WHERE id = $1",
        assignment_id,
    )

    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    role = current_user["role"]

    if role in ["teacher", "admin", "hod"]:
        if (
            role == "teacher"
            and str(assignment["teacher_id"]) != str(current_user["id"])
        ):
            raise HTTPException(status_code=403, detail="Not allowed")

    elif role == "student":
        if not assignment["published"]:
            raise HTTPException(status_code=403, detail="Assignment not published")

    else:
        raise HTTPException(status_code=403, detail="Not allowed")

    questions = await db.fetch(
        """
        SELECT
            taq.id              AS assignment_question_id,
            taq.question_id,
            taq.question_order,
            taq.marks,
            qb.question_text,
            qb.question_type
        FROM public.teacher_assignment_questions taq
        JOIN public.question_bank qb ON qb.id = taq.question_id
        WHERE taq.assignment_id = $1
          AND qb.is_deleted = false
        ORDER BY taq.question_order
        """,
        assignment_id,
    )

    return {
        **dict(assignment),
        "questions": [dict(q) for q in questions]
    }

@router.get("/available/list")
async def available_assignments(
    current_user: dict = Depends(require_student),
    db: asyncpg.Connection = Depends(get_db),
):
    rows = await db.fetch(
        """
        SELECT
            ta.*,
            c.name              AS subject_name,
            c.code              AS subject_code,
            p.full_name         AS teacher_name,
            -- BUG FIX: join submission so the student's real status comes through
            sas.id              AS submission_id,
            COALESCE(sas.status, 'not_started') AS status,
            -- BUG FIX: sum up awarded scores for the evaluated score chip
            (
                SELECT COALESCE(SUM(score_awarded), 0)
                FROM public.student_assignment_answers
                WHERE submission_id = sas.id
            )                   AS total_score,
            -- BUG FIX: question count for the detail modal info grid
            (
                SELECT COUNT(*)
                FROM public.teacher_assignment_questions
                WHERE assignment_id = ta.id
            )::int              AS question_count
        FROM public.teacher_assignments ta
        LEFT JOIN public.courses   c   ON c.id  = ta.course_id
        LEFT JOIN public.profiles  p   ON p.id  = ta.teacher_id
        -- BUG FIX: left join the current student's submission only (not all students)
        LEFT JOIN public.student_assignment_submissions sas
               ON sas.assignment_id = ta.id
              AND sas.student_id    = $1
        WHERE ta.published = TRUE
        ORDER BY ta.due_time ASC NULLS LAST
        """,
        current_user["id"],
    )

    return [dict(r) for r in rows]


# =====================================================
# 5. START SUBMISSION
@router.post("/{assignment_id}/start")
async def start_submission(
    assignment_id: str,
    current_user: dict = Depends(require_student),
    db: asyncpg.Connection = Depends(get_db),
):
    existing = await db.fetchrow(
        """
        SELECT id, status
        FROM public.student_assignment_submissions
        WHERE assignment_id = $1
          AND student_id    = $2
        """,
        assignment_id,
        current_user["id"],
    )

    if existing:
        if existing["status"] in ("submitted", "evaluated", "late_submitted"):
            return {
                "submission_id":    str(existing["id"]),
                "already_submitted": True,
                "status":           existing["status"],
            }
        # In-progress — let the frontend resume normally
        return {
            "submission_id":    str(existing["id"]),
            "already_submitted": False,
            "status":           existing["status"],
        }

    row = await db.fetchrow(
        """
        INSERT INTO public.student_assignment_submissions
            (assignment_id, student_id, status)
        VALUES ($1, $2, 'in_progress')
        RETURNING id
        """,
        assignment_id,
        current_user["id"],
    )

    return {
        "submission_id":    str(row["id"]),
        "already_submitted": False,
        "status":           "in_progress",
    }


# =====================================================
# 6. SAVE SINGLE ANSWER
# =====================================================
@router.post("/answers")
async def save_answer(
    payload: StudentAssignmentAnswerCreate,
    current_user: dict = Depends(require_student),
    db: asyncpg.Connection = Depends(get_db),
):
    await db.execute(
        """
        INSERT INTO public.student_assignment_answers
            (submission_id, question_id, answer_text, file_urls)
        VALUES ($1,$2,$3,$4)
        ON CONFLICT (submission_id, question_id)
        DO UPDATE SET
            answer_text = EXCLUDED.answer_text,
            file_urls   = EXCLUDED.file_urls,
            updated_at  = now()
        """,
        payload.submission_id,
        payload.question_id,
        payload.answer_text,
        payload.file_urls,   # ✅ was payload.file_url
    )
    return {"success": True}


# =====================================================
# 7. SAVE BULK ANSWERS
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
                INSERT INTO public.student_assignment_answers
                    (submission_id, question_id, answer_text, file_urls)
                VALUES ($1,$2,$3,$4)
                ON CONFLICT (submission_id, question_id)
                DO UPDATE SET
                    answer_text = EXCLUDED.answer_text,
                    file_urls   = EXCLUDED.file_urls,
                    updated_at  = now()
                """,
                ans.submission_id,
                ans.question_id,
                ans.answer_text,
                ans.file_urls,  
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
        SET status = 'submitted', submitted_at = now()
        WHERE id         = $1
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
    # -----------------------------
    # Update answer marks
    # -----------------------------
    row = await db.fetchrow(
        """
        UPDATE public.student_assignment_answers
        SET
            score_awarded = $1,
            feedback      = $2,
            evaluated_by  = $3,
            evaluated_at  = now()
        WHERE id = $4
        """,
        payload.score_awarded,
        current_user["id"],
        answer_id,
    )

    if not row:
        raise HTTPException(404, "Answer not found")

    submission_id = row["submission_id"]

    # -----------------------------
    # Recalculate total score
    # -----------------------------
    total = await db.fetchval(
        """
        SELECT COALESCE(SUM(score_awarded),0)
        FROM public.student_assignment_answers
        WHERE submission_id = $1
        """,
        submission_id,
    )

    # -----------------------------
    # Update submission
    # -----------------------------
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
        submission_id,
    )

    return {
        "success": True,
        "total_score": float(total)
    }


# =====================================================
# 10. TEACHER VIEW SUBMISSIONS
# GET /assignments/{assignment_id}/submissions
# =====================================================

@router.get("/{assignment_id}/submissions")
async def get_assignment_submissions(
    assignment_id: str,
    current_user: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    # -----------------------------
    # Check assignment exists
    # -----------------------------
    assignment = await db.fetchrow(
        """
        SELECT id, teacher_id, total_marks
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

    # -----------------------------
    # Owner check
    # -----------------------------
    if str(assignment["teacher_id"]) != str(current_user["id"]):
        raise HTTPException(
            status_code=403,
            detail="Not allowed"
        )

    # -----------------------------
    # Get student submissions
    # -----------------------------
    rows = await db.fetch(
        """
        SELECT
            s.id,
            s.student_id,
            s.status,
            s.total_score,
            s.submitted_at,

            p.full_name,
            p.usn,
            p.email

        FROM public.student_assignment_submissions s
        JOIN public.profiles p
        ON p.id = s.student_id

        WHERE s.assignment_id = $1
        ORDER BY s.submitted_at DESC NULLS LAST
        """,
        assignment_id,
    )

    return {
        "total_marks": assignment["total_marks"],
        "submissions": [dict(r) for r in rows]
    }


# =====================================================
# GET ONE SUBMISSION WITH ANSWERS
# =====================================================

@router.get("/submission/{submission_id}")
async def get_submission_detail(
    submission_id: str,
    current_user: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    row = await db.fetchrow(
        """
        SELECT
            s.*,
            p.full_name,
            p.usn,
            a.teacher_id,
            a.title as assignment_title
        FROM public.student_assignment_submissions s
        JOIN public.profiles p
          ON p.id = s.student_id
        JOIN public.teacher_assignments a
          ON a.id = s.assignment_id
        WHERE s.id = $1
        """,
        submission_id,
    )

    if not row:
        raise HTTPException(404, "Submission not found")

    if str(row["teacher_id"]) != str(current_user["id"]):
        raise HTTPException(403, "Not allowed")

    answers = await db.fetch(
        """
        SELECT
            ans.*,
            qb.question_text,
            taq.marks as max_marks
        FROM public.student_assignment_answers ans
        JOIN public.question_bank qb
          ON qb.id = ans.question_id
        LEFT JOIN public.teacher_assignment_questions taq
          ON taq.assignment_id = $1
         AND taq.question_id = ans.question_id
        WHERE ans.submission_id = $2
        ORDER BY taq.question_order
        """,
        row["assignment_id"],
        submission_id,
    )

    return {
        **dict(row),
        "answers": [dict(a) for a in answers]
    }


# =====================================================
# 10. GET ASSIGNMENT RESULTS (student view)
# =====================================================
@router.get("/submissions/{submission_id}/results")
async def get_assignment_results(
    submission_id: str,
    current_user: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_db),
):
    submission = await db.fetchrow(
        "SELECT * FROM public.student_assignment_submissions WHERE id = $1",
        submission_id,
    )

    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    if current_user["role"] == "student":
        if str(submission["student_id"]) != str(current_user["id"]):
            raise HTTPException(status_code=403, detail="Not allowed")

    answers = await db.fetch(
        """
        SELECT
            saa.*,
            qb.question_text,
            qb.question_type,
            taq.marks
        FROM public.student_assignment_answers saa
        JOIN public.question_bank qb
          ON qb.id = saa.question_id
        LEFT JOIN public.teacher_assignment_questions taq
          ON taq.question_id   = qb.id
         AND taq.assignment_id = $1
        WHERE saa.submission_id = $2
        ORDER BY taq.question_order
        """,
        submission["assignment_id"],
        submission_id,
    )

    return {
        "submission": dict(submission),
        "answers":    [dict(a) for a in answers],
    }

# =====================================================
# UPLOAD ANSWER ATTACHMENTS
@router.post("/answers/attachments")
async def upload_answer_attachments(
    submission_id: str = Form(...),
    question_id:   str = Form(...),
    files:         List[UploadFile] = File(...),
    current_user:  dict = Depends(require_student),
    db:            asyncpg.Connection = Depends(get_db),
):
    submission = await db.fetchrow(
        """
        SELECT id FROM public.student_assignment_submissions
        WHERE id = $1 AND student_id = $2
        """,
        submission_id,
        current_user["id"],
    )
    if not submission:
        raise HTTPException(status_code=403, detail="Submission not found or not yours")

    ALLOWED_TYPES = {
        "application/pdf",
        "image/jpeg", "image/png", "image/gif", "image/webp",
    }
    MAX_BYTES = 10 * 1024 * 1024

    uploaded_urls = []
    supabase = get_supabase()

    for file in files:
        if file.content_type not in ALLOWED_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"File type '{file.content_type}' not allowed",
            )

        contents = await file.read()
        if len(contents) > MAX_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"File '{file.filename}' exceeds 10 MB limit",
            )

        ext       = file.filename.rsplit(".", 1)[-1] if "." in file.filename else "bin"
        safe_name = f"{uuid_lib.uuid4().hex}.{ext}"
        path      = f"{submission_id}/{question_id}/{safe_name}"

        supabase.storage.from_("assignment-pdfs").upload(
            path=path,
            file=contents,
            file_options={"content-type": file.content_type, "upsert": "true"},
        )
        public_url = supabase.storage \
            .from_("assignment-pdfs") \
            .get_public_url(path)

        uploaded_urls.append(public_url)
    await db.execute(
        """
        UPDATE public.student_assignment_answers
        SET
            file_urls  = $1,
            updated_at = now()
        WHERE submission_id = $2
          AND question_id   = $3
        """,
        uploaded_urls,    # $1
        submission_id,    # $2
        question_id,      # $3
    )

    return {"success": True, "urls": uploaded_urls}
# =====================================================
# UPDATE ASSIGNMENT
# PUT /assignments/{assignment_id}
# =====================================================
@router.put("/{assignment_id}", response_model=TeacherAssignmentResponse)
async def update_assignment(
    assignment_id: str,
    payload: TeacherAssignmentUpdate,
    current_user: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    async with db.transaction():

        assignment = await db.fetchrow(
            "SELECT * FROM public.teacher_assignments WHERE id = $1",
            assignment_id,
        )
        if not assignment:
            raise HTTPException(status_code=404, detail="Assignment not found")
        if str(assignment["teacher_id"]) != str(current_user["id"]):
            raise HTTPException(status_code=403, detail="Not allowed")
        updated = await db.fetchrow(
            """
            UPDATE public.teacher_assignments
            SET
                course_id             = COALESCE($2,  course_id),
                title                 = COALESCE($3,  title),
                description           = COALESCE($4,  description),
                total_marks           = COALESCE($5,  total_marks),
                passing_marks         = COALESCE($6,  passing_marks),
                start_time            = COALESCE($7,  start_time),
                due_time              = COALESCE($8,  due_time),
                allow_late_submission = COALESCE($9,  allow_late_submission),
                published             = COALESCE($10, published),
                updated_at            = now()
            WHERE id = $1
            RETURNING *
            """,
            assignment_id,
            payload.course_id, payload.title, payload.description,
            payload.total_marks, payload.passing_marks,
            payload.start_time, payload.due_time,
            payload.allow_late_submission, payload.published,
        )
        if hasattr(payload, "questions") and payload.questions is not None:
            await db.execute(
                "DELETE FROM public.teacher_assignment_questions WHERE assignment_id = $1",
                assignment_id,
            )
            total_marks = 0
            for i, q in enumerate(payload.questions, start=1):
                row = await db.fetchrow(
                    "SELECT id, question_type FROM public.question_bank WHERE id = $1",
                    q.question_id,
                )
                if not row:
                    raise HTTPException(status_code=404, detail=f"Question {q.question_id} not found")
                if row["question_type"] not in ("descriptive", "short"):
                    raise HTTPException(status_code=400, detail="Only descriptive/short questions allowed")
                await db.execute(
                    """
                    INSERT INTO public.teacher_assignment_questions
                        (assignment_id, question_id, question_order, marks)
                    VALUES ($1,$2,$3,$4)
                    """,
                    assignment_id, q.question_id, q.question_order or i, q.marks,
                )

                total_marks += float(q.marks)
            updated = await db.fetchrow(
                """
                UPDATE public.teacher_assignments
                SET total_marks = $2, updated_at = now()
                WHERE id = $1
                RETURNING *
                """,
                assignment_id, total_marks,
            )
        return dict(updated)


# =====================================================
# DELETE ASSIGNMENT
# =====================================================
@router.delete("/{assignment_id}")
async def delete_assignment(
    assignment_id: str,
    current_user: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    assignment = await db.fetchrow(
        "SELECT id, teacher_id FROM public.teacher_assignments WHERE id = $1",
        assignment_id,
    )
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")
    if str(assignment["teacher_id"]) != str(current_user["id"]):
        raise HTTPException(status_code=403, detail="Not allowed")
    await db.execute(
        "DELETE FROM public.teacher_assignments WHERE id = $1",
        assignment_id,
    )
    return {"success": True, "message": "Assignment deleted"}