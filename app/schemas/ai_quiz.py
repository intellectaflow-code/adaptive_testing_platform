from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import Optional, List

# ---- Start AI Quiz ----

class AIQuizAttemptCreate(BaseModel):
    topic: str = Field(..., min_length=2, max_length=200)
    difficulty: str = Field(..., pattern="^(easy|medium|hard)$")
    total_questions: int = Field(..., ge=1, le=50)


# ---- Question sent to frontend ----

class AIQuizQuestion(BaseModel):
    question_id: UUID
    question_text: str
    options: List[str]


class AIQuizStartResponse(BaseModel):
    attempt_id: UUID
    questions: List[AIQuizQuestion]


# ---- Attempt Output ----

class AIQuizAttemptOut(BaseModel):
    id: UUID
    student_id: UUID
    topic: str
    difficulty: str
    total_questions: int
    correct_answers: Optional[int] = None
    score: Optional[float] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ---- Student Answer ----

class AIQuizAnswerCreate(BaseModel):
    question_id: UUID
    selected_answer: Optional[str] = None


class AIQuizSubmit(BaseModel):
    attempt_id: UUID
    answers: List[AIQuizAnswerCreate]

class QuizConfig(BaseModel):
    module: str
    q_type: str = "mcq"
    count: int = 5
    options_count: Optional[int] = 4
    min_words: Optional[int] = 50
    teacher_notes: Optional[str] = ""
    filename: Optional[str] = ""

# ---- Result Response ----

class AIQuizSubmitResponse(BaseModel):
    attempt_id: UUID
    correct_answers: int
    total_questions: int
    score: int


# ---- Review Answers ----

class AIQuizAnswerOut(BaseModel):
    question_id: UUID
    question_text: str
    options: List[str]  # Add this so the UI can render the full question
    selected_answer: Optional[str] = None
    correct_answer: str
    is_correct: bool
    explanation: Optional[str] = None # Added explanation for review


# ---- Internal DB Schema ----

class AIQuizQuestionDB(BaseModel):
    attempt_id: UUID
    question_text: str
    options: List[str]      # Maps to JSONB
    correct_answer: str
    explanation: Optional[str] = None # Added to store generated explanation

    class Config:
        from_attributes = True

# NEW: Schema for saving to public.ai_quiz_answers table
class AIQuizAnswerDB(BaseModel):
    attempt_id: UUID
    question_id: UUID
    selected_answer: Optional[str] = None
    is_correct: bool
    explanation: Optional[str] = None # Stores the specific explanation in the answers table

    class Config:
        from_attributes = True


# app/schemas/ai_explain.py

class AIExplainRequest(BaseModel):
    question_text: str
    options: List[str]
    correct_answer: str

# NEW: Response for explanation generation
class AIExplainResponse(BaseModel):
    explanation: str
