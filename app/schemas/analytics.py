from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime
from uuid import UUID


class QuestionAnalyticsOut(BaseModel):
    id: UUID
    question_id: Optional[UUID] = None
    quiz_id: Optional[UUID] = None
    total_attempts: int
    correct_count: int
    incorrect_count: int
    average_time_seconds: float
    difficulty_index: Optional[float] = None
    discrimination_index: Optional[float] = None
    updated_at: datetime


class StudentPerformanceOut(BaseModel):
    id: UUID
    student_id: UUID
    course_id: UUID
    quizzes_taken: int
    average_score: float
    highest_score: Optional[float] = None
    lowest_score: Optional[float] = None
    improvement_rate: Optional[float] = None
    last_updated: datetime


class AIGeneratedQuestionCreate(BaseModel):
    course_id: UUID
    generated_text: str
    syllabus_reference: Optional[str] = None
    difficulty: Optional[Literal["easy", "medium", "hard"]] = None


class AIGeneratedQuestionOut(BaseModel):
    id: UUID
    course_id: Optional[UUID] = None
    generated_text: str
    syllabus_reference: Optional[str] = None
    difficulty: Optional[str] = None
    approved: bool
    approved_by: Optional[UUID] = None
    created_at: datetime

