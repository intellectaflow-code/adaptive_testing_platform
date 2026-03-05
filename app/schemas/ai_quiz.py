from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Optional


class AIQuizAttemptCreate(BaseModel):
    topic: str
    difficulty: str
    total_questions: int


class AIQuizAttemptOut(BaseModel):
    id: UUID
    student_id: UUID
    topic: str
    difficulty: str
    total_questions: int
    correct_answers: Optional[int]
    score: Optional[float]
    created_at: datetime

    class Config:
        from_attributes = True

class AIQuizAnswerCreate(BaseModel):
    question_text: str
    selected_answer: str
    correct_answer: str
    is_correct: bool


class AIQuizAnswerOut(BaseModel):
    id: UUID
    attempt_id: UUID
    question_text: str
    selected_answer: str
    correct_answer: str
    is_correct: bool

    class Config:
        from_attributes = True

from typing import List


class AIQuizSubmit(BaseModel):
    attempt_id: UUID
    answers: List[AIQuizAnswerCreate]