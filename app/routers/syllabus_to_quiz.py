import json
import os
from uuid import UUID
from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
from google.cloud import storage
import vertexai
from vertexai.generative_models import GenerativeModel, Part
import asyncpg
from app.schemas.ai_quiz import QuizConfig
from app.database import get_db
from app.dependencies import require_teacher_up
from dotenv import load_dotenv
from app.config import get_settings

load_dotenv()

settings = get_settings()
vertexai.init(project=settings.google_project_id, location=os.getenv("GOOGLE_LOCATION"))
model = GenerativeModel("gemini-2.0-flash")
storage_client = storage.Client(project=settings.google_project_id)

router = APIRouter(prefix="/ai", tags=["Curriculum AI"])

# ─── 1. GENERATE PREVIEW (NO DATABASE SAVING) ───────────────────────────────

@router.post("/generate-questions")
async def generate_questions_preview(
    course_id: UUID, 
    config: QuizConfig, 
    current_user: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db)
):
    """
    Step 1: Gemini reads the syllabus and returns JSON questions.
    Nothing is saved to the DB yet.
    """
    course = await db.fetchrow(
        "SELECT syllabus_file_url FROM public.courses WHERE id = $1", 
        course_id
    )
    
    if not course or not course['syllabus_file_url']:
        raise HTTPException(status_code=404, detail="No syllabus found for this course.")

    pdf_file = Part.from_uri(uri=course['syllabus_file_url'], mime_type="application/pdf")
    
    if config.q_type == "mcq":
        prompt = f"""Generate {config.count} Multiple Choice Questions based on the topic '{config.module}' from this syllabus. 
        Each must have exactly {config.options_count} options. 
        A detailed 'explanation' field for the correct answer is COMPULSORY. 
        Notes: {config.teacher_notes}. 
        Return ONLY a JSON list:
        [{{"question": "text", "options": ["a", "b", "c", "d"], "answer": "correct_option", "explanation": "reasoning"}}]"""
    else:
        prompt = f"""Generate {config.count} Descriptive Questions based on {config.module}. 
        The expected answer length should be around {config.min_words} words.
        Notes: {config.teacher_notes}. 
        Return ONLY a JSON list:
        [{{"question": "text", "min_words": {config.min_words}}}]"""

    try:
        response = model.generate_content([prompt, pdf_file])
        clean_json = response.text.replace("```json", "").replace("```", "").strip()
        questions = json.loads(clean_json)
        return {"questions": questions}
    except Exception as e:
        print(f"Gemini Error: {e}")
        raise HTTPException(status_code=500, detail="AI failed to generate valid quiz data.")

# ─── 2. FINAL SAVE (AFTER TEACHER EDITS) ────────────────────────────────────

@router.post("/save-questions")
async def save_approved_questions(
    course_id: UUID,
    payload: dict, # Expects {"questions": [...], "module": "topic_name"}
    current_user: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db)
):
    """
    Step 2: Receives the edited list from the frontend and saves to DB.
    """
    questions = payload.get("questions", [])
    topic_name = payload.get("module", "AI Generated")

    if not questions:
        raise HTTPException(status_code=400, detail="No questions provided for saving.")

    async with db.transaction():
        for q in questions:
            # Added 'marks' to avoid the NotNullViolationError
            q_id = await db.fetchval(
                """INSERT INTO public.question_bank 
                   (course_id, created_by, question_text, question_type, topic, is_ai_generated, explanation, marks)
                   VALUES ($1, $2, $3, $4, $5, true, $6, 1.0) RETURNING id""",
                course_id, 
                current_user['id'], 
                q.get('question'), 
                'mcq_single', 
                topic_name,
                q.get('explanation', '')
            )
            
            # Save options for MCQs
            if 'options' in q:
                for opt_text in q['options']:
                    is_correct = (opt_text == q.get('answer'))
                    await db.execute(
                        "INSERT INTO public.question_options (question_id, option_text, is_correct) VALUES ($1, $2, $3)",
                        q_id, opt_text, is_correct
                    )

    return {"status": "success", "message": f"Saved {len(questions)} questions."}

# ─── HELPER: UPLOAD SYLLABUS ────────────────────────────────────────────────

@router.post("/upload/{course_id}")
async def upload_syllabus(course_id: UUID, file: UploadFile = File(...), db: asyncpg.Connection = Depends(get_db)):
    try:
        bucket = storage_client.bucket(settings.google_bucket_name)
        blob = bucket.blob(f"syllabi/{course_id}/{file.filename}")
        blob.upload_from_file(file.file)
        gcs_url = f"gs://{settings.google_bucket_name}/{blob.name}"

        # Fixed column name to syllabus_file_url and used asyncpg for consistency
        await db.execute(
            "UPDATE public.courses SET syllabus_file_url = $1 WHERE id = $2",
            gcs_url, course_id
        )
        return {"status": "success", "url": gcs_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    

@router.post("/create-quiz-from-ai")
async def create_quiz_from_ai(
    course_id: UUID,
    payload: dict, 
    current_user: dict = Depends(require_teacher_up),
    db: asyncpg.Connection = Depends(get_db)
):
    questions = payload.get("questions", [])
    details = payload.get("details", {})
    
    async with db.transaction():
        # 1. Insert into quizzes table
        quiz_id = await db.fetchval(
            """INSERT INTO public.quizzes 
               (course_id, created_by, title, description, total_marks, passing_marks, 
                duration_minutes, randomize_questions, randomize_options, is_published, test_id)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, false, $10) RETURNING id""",
            course_id, current_user['id'], details['title'], details['description'],
            len(questions), float(details['passing_marks']), int(details['duration']),
            True, True, f"AI-{os.urandom(3).hex().upper()}"
        )

        # 2. Insert Questions and Options
        for q in questions:
            q_id = await db.fetchval(
                """INSERT INTO public.question_bank 
                   (course_id, created_by, question_text, question_type, topic, is_ai_generated, explanation, marks)
                   VALUES ($1, $2, $3, 'mcq_single', $4, true, $5, 1.0) RETURNING id""",
                course_id, current_user['id'], q['question'], details['title'], q.get('explanation', '')
            )
            
            for opt_text in q['options']:
                await db.execute(
                    "INSERT INTO public.question_options (question_id, option_text, is_correct) VALUES ($1, $2, $3)",
                    q_id, opt_text, opt_text == q['answer']
                )
                
            # 3. Link question to quiz (Assuming a quiz_questions junction table exists)
            await db.execute(
                "INSERT INTO public.quiz_questions (quiz_id, question_id) VALUES ($1, $2)",
                quiz_id, q_id
            )

    return {"status": "success", "quiz_id": str(quiz_id)}