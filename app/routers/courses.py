from fastapi import APIRouter, Depends, HTTPException, status, Request
from typing import List, Optional
import asyncpg
from fastapi import UploadFile, File, Form
from google.cloud import storage
from app.database import get_db
from app.dependencies import get_current_user, require_teacher_up, require_admin_or_hod, require_admin
from app.schemas.courses import (
    BulkEnrollRequest, CourseCreate, CourseUpdate, CourseOut,
    AssignTeacherIn, EnrollStudentIn,
)
from app.config import get_settings
from app.services.activity import log_activity


router = APIRouter(prefix="/courses", tags=["Courses"])
settings = get_settings()

def get_storage_client():
    return storage.Client()

# ---- Helpers ----

async def _get_course_or_404(db, course_id: str):
    row = await db.fetchrow(
        "SELECT * FROM public.courses WHERE id = $1 AND is_deleted = false", course_id
    )
    if not row:
        raise HTTPException(status_code=404, detail="Course not found")
    return row


async def _assert_course_access(db, course_id: str, user: dict):
    """Teacher must be assigned to the course; admin/hod bypass."""
    if user["role"] in ("admin", "hod"):
        return
    if user["role"] == "teacher":
        row = await db.fetchrow(
            "SELECT id FROM public.course_teachers WHERE course_id = $1 AND teacher_id = $2",
            course_id, str(user["id"]),
        )
        if not row:
            raise HTTPException(status_code=403, detail="Not assigned to this course")
        return
    raise HTTPException(status_code=403, detail="Access denied")



@router.post("", response_model=CourseOut, status_code=201)
async def create_course(
    name: str = Form(...),
    code: Optional[str] = Form(None),      # Changed to Optional
    semester: Optional[str] = Form(None),  # Receive as string first to avoid 422
    branch: Optional[str] = Form(None),    # Changed to Optional
    file: UploadFile = File(...),          # Mandatory
    current_user: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db),
):
    
    try:
        semester_int = int(semester)
    except (ValueError, TypeError):
        semester_int = 1 # Fallback default

    # 1. Upload Syllabus to Google Cloud Storage
    try:
        storage_client = get_storage_client()
        bucket = storage_client.bucket(settings.google_bucket_name)
        # Unique path per course/teacher
        blob_path = f"syllabi/{current_user['id']}/{file.filename}"
        blob = bucket.blob(blob_path)
        
        blob.upload_from_file(file.file, content_type="application/pdf")
        gcs_url = f"gs://{settings.google_bucket_name}/{blob_path}"
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Syllabus upload failed: {str(e)}")

    # 2. Database Transaction
    async with db.transaction():
        # Insert Course including the syllabus URL
        row = await db.fetchrow(
            """
            INSERT INTO public.courses (name, code, semester, branch, created_by, syllabus_file_url)
            VALUES ($1, $2, $3, $4, $5, $6) RETURNING *
            """,
            name, code, semester_int, branch, str(current_user["id"]), gcs_url,
        )
        
        # Link teacher to the course
        await db.execute(
            """
            INSERT INTO public.course_teachers (course_id, teacher_id)
            VALUES ($1, $2)
            """,
            row["id"], str(current_user["id"])
        )

        await log_activity(db, str(current_user["id"]), "create_course", {"course_id": str(row["id"])})
        
        return dict(row)


@router.get("", response_model=List[CourseOut])
async def list_courses(
    branch: Optional[str] = None,
    semester: Optional[int] = None,
    skip: int = 0,
    limit: int = 50,
    current_user: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_db),
):

    # -----------------------------
    # 🎓 STUDENT
    # -----------------------------
    if current_user["role"] == "student":
        rows = await db.fetch(
            """
            SELECT 
                c.*,
                STRING_AGG(p.full_name, ', ' ORDER BY p.full_name) AS teacher_name
            FROM public.courses c
            JOIN public.enrollments e 
                ON e.course_id = c.id AND e.student_id = $1
            LEFT JOIN public.course_teachers ct 
                ON ct.course_id = c.id
            LEFT JOIN public.profiles p 
                ON p.id = ct.teacher_id 
                AND p.is_deleted = false 
                AND p.role = 'teacher'
            WHERE c.is_deleted = false
            GROUP BY c.id
            ORDER BY c.name
            LIMIT $2 OFFSET $3
            """,
            str(current_user["id"]),
            limit,
            skip,
        )
        return [dict(r) for r in rows]


    # -----------------------------
    # 👨‍🏫 TEACHER
    # -----------------------------
    if current_user["role"] == "teacher":
        rows = await db.fetch(
            """
            SELECT 
                c.*,
                STRING_AGG(p.full_name, ', ' ORDER BY p.full_name) AS teacher_name
            FROM public.courses c
            JOIN public.course_teachers ct ON ct.course_id = c.id
            LEFT JOIN public.profiles p ON p.id = ct.teacher_id
            WHERE ct.teacher_id = $1 
              AND c.is_deleted = false
            GROUP BY c.id
            ORDER BY c.name
            LIMIT $2 OFFSET $3
            """,
            str(current_user["id"]),
            limit,
            skip
        )
        return [dict(r) for r in rows]


    # -----------------------------
    # 🧑‍💼 ADMIN / HOD
    # -----------------------------
    where_parts = ["c.is_deleted = false"]
    params: list = []
    idx = 1

    # 🔒 HOD restriction (IMPORTANT)
    if current_user["role"] == "hod":
        where_parts.append(f"c.branch = ${idx}")
        params.append(current_user["branch"])
        idx += 1

    # Optional filters
    if branch:
        where_parts.append(f"c.branch = ${idx}")
        params.append(branch)
        idx += 1

    if semester:
        where_parts.append(f"c.semester = ${idx}")
        params.append(semester)
        idx += 1

    where = " AND ".join(where_parts)

    rows = await db.fetch(
        f"""
        SELECT 
            c.*,
            STRING_AGG(p.full_name, ', ' ORDER BY p.full_name) AS teacher_name,
            MIN(
                CASE 
                    WHEN ct.teacher_id = ${idx} THEN 0 
                    ELSE 1 
                END
            ) AS priority
        FROM public.courses c
        LEFT JOIN public.course_teachers ct ON ct.course_id = c.id
        LEFT JOIN public.profiles p ON p.id = ct.teacher_id
        WHERE {where}
        GROUP BY c.id
        ORDER BY 
            priority ASC,                    -- 🔥 My courses first
            teacher_name ASC NULLS LAST,     -- 🔥 Then by teacher
            c.name ASC                      -- fallback
        LIMIT ${idx+1} OFFSET ${idx+2}
        """,
        *params,
        str(current_user["id"]),  # 👈 used in priority
        limit,
        skip,
    )

    return [dict(r) for r in rows]

@router.get("/{course_id}", response_model=CourseOut)
async def get_course(
    course_id: str,
    current_user: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_db),
):
    return dict(await _get_course_or_404(db, course_id))


@router.put("/{course_id}", response_model=CourseOut)
async def update_course(
    course_id: str,
    body: CourseUpdate,
    current_user: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_db),
):
    await _assert_course_access(db, course_id, current_user)
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    set_clause = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(updates.keys()))
    row = await db.fetchrow(
        f"UPDATE public.courses SET {set_clause}, updated_at = now() WHERE id = $1 AND is_deleted = false RETURNING *",
        course_id, *updates.values(),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Course not found")
    return dict(row)


@router.delete("/{course_id}", status_code=204)
async def delete_course(
    course_id: str,
    current_user: dict = Depends(require_admin_or_hod),
    db: asyncpg.Connection = Depends(get_db),
):
    await db.execute(
        "UPDATE public.courses SET is_deleted = true, updated_at = now() WHERE id = $1",
        course_id,
    )


# ---- Teachers ----

@router.post("/{course_id}/teachers", status_code=201)
async def assign_teacher(
    course_id: str,
    body: AssignTeacherIn,
    _: dict = Depends(require_admin_or_hod),
    db: asyncpg.Connection = Depends(get_db),
):
    await _get_course_or_404(db, course_id)
    try:
        await db.execute(
            "INSERT INTO public.course_teachers (course_id, teacher_id) VALUES ($1, $2)",
            course_id, str(body.teacher_id),
        )
    except asyncpg.UniqueViolationError:
        raise HTTPException(status_code=409, detail="Teacher already assigned")
    return {"detail": "Teacher assigned"}


@router.delete("/{course_id}/teachers/{teacher_id}", status_code=204)
async def remove_teacher(
    course_id: str,
    teacher_id: str,
    _: dict = Depends(require_admin_or_hod),
    db: asyncpg.Connection = Depends(get_db),
):
    await db.execute(
        "DELETE FROM public.course_teachers WHERE course_id = $1 AND teacher_id = $2",
        course_id, teacher_id,
    )


@router.get("/{course_id}/teachers")
async def list_teachers(
    course_id: str,
    _: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_db),
):
    rows = await db.fetch(
        """
        SELECT p.id, p.full_name, p.branch, ct.assigned_at
        FROM public.course_teachers ct
        JOIN public.profiles p ON p.id = ct.teacher_id
        WHERE ct.course_id = $1 AND p.is_deleted = false
        """,
        course_id,
    )
    return [dict(r) for r in rows]


# ---- Enrollments ----

@router.post("/{course_id}/enroll", status_code=201)
async def enroll_student(
    course_id: str,
    body: EnrollStudentIn,
    current_user: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_db),
):
    await _get_course_or_404(db, course_id)

    # Teachers can enroll any student; students can self-enroll
    student_id = (
        str(body.student_id)
        if current_user["role"] in ("admin", "hod", "teacher")
        else str(current_user["id"])
    )

    try:
        row = await db.fetchrow(
            "INSERT INTO public.enrollments (course_id, student_id) VALUES ($1, $2) RETURNING *",
            course_id, student_id,
        )
    except asyncpg.UniqueViolationError:
        raise HTTPException(status_code=409, detail="Already enrolled")
    return dict(row)


@router.delete("/{course_id}/enroll/{student_id}", status_code=204)
async def unenroll_student(
    course_id: str,
    student_id: str,
    current_user: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_db),
):
    if current_user["role"] == "student" and str(current_user["id"]) != student_id:
        raise HTTPException(status_code=403, detail="Cannot unenroll another student")
    await db.execute(
        "DELETE FROM public.enrollments WHERE course_id = $1 AND student_id = $2",
        course_id, student_id,
    )


@router.get("/{course_id}/students")
async def list_enrolled_students(
    course_id: str,
    current_user: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_db),
):
    await _assert_course_access(db, course_id, current_user)
    rows = await db.fetch(
        """
        SELECT p.id, p.full_name, p.usn, p.branch, p.section, e.enrolled_at
        FROM public.enrollments e
        JOIN public.profiles p ON p.id = e.student_id
        WHERE e.course_id = $1 AND p.is_deleted = false
        ORDER BY p.full_name
        """,
        course_id,
    )
    return [dict(r) for r in rows]


@router.post("/bulk-enroll-usn")
async def bulk_enroll_usn(
    body: BulkEnrollRequest,
    current_user: dict = Depends(require_admin_or_hod),
    db: asyncpg.Connection = Depends(get_db),
):
    course_id = body.course_id
    usns = body.usns
    if not usns:
        raise HTTPException(400, "No USNs provided")

    # 🔍 Get course
    course = await db.fetchrow(
        "SELECT branch FROM courses WHERE id = $1",
        course_id
    )
    if not course:
        raise HTTPException(404, "Course not found")

    # 🔐 HOD restriction
    if current_user["role"] == "hod":
        if course["branch"] != current_user["branch"]:
            raise HTTPException(403, "Only your branch allowed")

    # 🔍 Get students by USN
    students = await db.fetch(
        """
        SELECT id, usn, branch
        FROM profiles
        WHERE usn = ANY($1::text[])
        """,
        usns
    )

    enrolled = 0
    skipped = []
    not_found = list(usns)

    async with db.transaction():
        for s in students:
            # remove from not_found
            if s["usn"] in not_found:
                not_found.remove(s["usn"])

            # HOD branch check
            if current_user["role"] == "hod":
                if s["branch"] != current_user["branch"]:
                    skipped.append(s["usn"])
                    continue

            await db.execute(
                """
                INSERT INTO enrollments (course_id, student_id)
                VALUES ($1, $2)
                ON CONFLICT DO NOTHING
                """,
                course_id,
                s["id"]
            )
            enrolled += 1

    return {
        "enrolled": enrolled,
        "skipped": skipped,
        "not_found": not_found
    }
@router.get("/departments")
async def list_departments(
    db: asyncpg.Connection = Depends(get_db),
):
    rows = await db.fetch(
        "SELECT id, name, code FROM public.departments ORDER BY name"
    )
    return [dict(r) for r in rows]
