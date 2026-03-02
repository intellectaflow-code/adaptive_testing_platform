#!/usr/bin/env python3
"""
seed.py – populate your Supabase DB with dev test data.

Usage:
    python seed.py

Prerequisites:
    - .env file configured with DATABASE_URL
    - The Supabase auth.users rows must already exist for the UUIDs below
      (create them via Supabase Dashboard → Authentication → Add user)
    - Or swap the UUIDs below with real ones from your project

Tip: run once, then comment out sections you don't want to re-seed.
"""

import asyncio
import asyncpg
import sys
from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    print("❌  DATABASE_URL not set in .env")
    sys.exit(1)

# ── Fixed UUIDs so seed is idempotent ────────────────────────────────────────
ADMIN_ID   = "00000000-0000-0000-0000-000000000001"
HOD_ID     = "00000000-0000-0000-0000-000000000002"
TEACHER_ID = "00000000-0000-0000-0000-000000000003"
STUDENT1   = "00000000-0000-0000-0000-000000000004"
STUDENT2   = "00000000-0000-0000-0000-000000000005"
COURSE_ID  = "00000000-0000-0000-0000-000000000010"
QUIZ_ID    = "00000000-0000-0000-0000-000000000020"
Q1_ID      = "00000000-0000-0000-0000-000000000030"
Q2_ID      = "00000000-0000-0000-0000-000000000031"


async def seed():
    print("🌱  Connecting to database…")
    conn = await asyncpg.connect(DATABASE_URL)

    print("  → profiles")
    for uid, name, role, usn in [
        (ADMIN_ID,   "Dev Admin",    "admin",   None),
        (HOD_ID,     "Dr. HOD",      "hod",     None),
        (TEACHER_ID, "Prof. Sharma", "teacher", None),
        (STUDENT1,   "Alice Kumar",  "student", "1CS21CS001"),
        (STUDENT2,   "Bob Nair",     "student", "1CS21CS002"),
    ]:
        await conn.execute(
            """
            INSERT INTO public.profiles (id, full_name, role, branch, section, usn)
            VALUES ($1, $2, $3, 'CSE', 'A', $4)
            ON CONFLICT (id) DO UPDATE SET full_name = EXCLUDED.full_name
            """,
            uid, name, role, usn,
        )

    print("  → course")
    await conn.execute(
        """
        INSERT INTO public.courses (id, name, code, semester, branch, created_by)
        VALUES ($1, 'Data Structures & Algorithms', 'CS301', 3, 'CSE', $2)
        ON CONFLICT (id) DO NOTHING
        """,
        COURSE_ID, TEACHER_ID,
    )

    print("  → course_teachers + enrollments")
    await conn.execute(
        "INSERT INTO public.course_teachers (course_id, teacher_id) VALUES ($1,$2) ON CONFLICT DO NOTHING",
        COURSE_ID, TEACHER_ID,
    )
    for sid in [STUDENT1, STUDENT2]:
        await conn.execute(
            "INSERT INTO public.enrollments (course_id, student_id) VALUES ($1,$2) ON CONFLICT DO NOTHING",
            COURSE_ID, sid,
        )

    print("  → question_bank")
    await conn.execute(
        """
        INSERT INTO public.question_bank
            (id, course_id, created_by, question_text, question_type, difficulty, marks, negative_marks)
        VALUES ($1,$2,$3,'What is the time complexity of binary search?','mcq_single','easy',2,0.5)
        ON CONFLICT (id) DO NOTHING
        """,
        Q1_ID, COURSE_ID, TEACHER_ID,
    )
    # Options for Q1
    correct_opt = "00000000-0000-0000-0001-000000000001"
    wrong_opts  = [
        ("00000000-0000-0000-0001-000000000002", "O(n)"),
        ("00000000-0000-0000-0001-000000000003", "O(n²)"),
        ("00000000-0000-0000-0001-000000000004", "O(1)"),
    ]
    await conn.execute(
        "INSERT INTO public.question_options (id, question_id, option_text, is_correct) VALUES ($1,$2,'O(log n)',true) ON CONFLICT DO NOTHING",
        correct_opt, Q1_ID,
    )
    for oid, txt in wrong_opts:
        await conn.execute(
            "INSERT INTO public.question_options (id, question_id, option_text, is_correct) VALUES ($1,$2,$3,false) ON CONFLICT DO NOTHING",
            oid, Q1_ID, txt,
        )

    await conn.execute(
        """
        INSERT INTO public.question_bank
            (id, course_id, created_by, question_text, question_type, difficulty, marks, negative_marks)
        VALUES ($1,$2,$3,'A stack uses LIFO principle. True or False?','true_false','easy',1,0)
        ON CONFLICT (id) DO NOTHING
        """,
        Q2_ID, COURSE_ID, TEACHER_ID,
    )
    await conn.execute(
        "INSERT INTO public.question_options (id, question_id, option_text, is_correct) VALUES ('00000000-0000-0000-0002-000000000001',$1,'True',true) ON CONFLICT DO NOTHING",
        Q2_ID,
    )
    await conn.execute(
        "INSERT INTO public.question_options (id, question_id, option_text, is_correct) VALUES ('00000000-0000-0000-0002-000000000002',$1,'False',false) ON CONFLICT DO NOTHING",
        Q2_ID,
    )

    print("  → quiz")
    await conn.execute(
        """
        INSERT INTO public.quizzes
            (id, course_id, created_by, title, description, total_marks, passing_marks,
             duration_minutes, show_results_immediately, is_published)
        VALUES ($1,$2,$3,'DSA Mid-Term Quiz','Chapter 1-3',3,2,30,true,true)
        ON CONFLICT (id) DO NOTHING
        """,
        QUIZ_ID, COURSE_ID, TEACHER_ID,
    )
    for i, qid in enumerate([Q1_ID, Q2_ID], 1):
        await conn.execute(
            "INSERT INTO public.quiz_questions (quiz_id, question_id, question_order) VALUES ($1,$2,$3) ON CONFLICT DO NOTHING",
            QUIZ_ID, qid, i,
        )

    print("  → announcement")
    await conn.execute(
        """
        INSERT INTO public.announcements (course_id, created_by, title, message)
        VALUES ($1,$2,'Welcome to DSA!','Quiz 1 is live. Good luck!')
        ON CONFLICT DO NOTHING
        """,
        COURSE_ID, TEACHER_ID,
    )

    await conn.close()
    print("")
    print("✅  Seed complete!")
    print("")
    print("   Test users (create these in Supabase Auth first, then seed):")
    print(f"     admin   id={ADMIN_ID}")
    print(f"     teacher id={TEACHER_ID}")
    print(f"     student id={STUDENT1}")
    print(f"     student id={STUDENT2}")
    print("")
    print("   Course  id =", COURSE_ID)
    print("   Quiz    id =", QUIZ_ID)


asyncio.run(seed())

