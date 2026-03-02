from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from uuid import UUID


class AnswerSubmit(BaseModel):
    question_id: UUID
    selected_option_id: Optional[UUID] = None
    answer_text: Optional[str] = None
    time_spent_seconds: Optional[int] = Field(None, ge=0)


class AttemptStartOut(BaseModel):
    attempt_id: UUID
    quiz_id: UUID
    attempt_number: int
    started_at: datetime
    duration_minutes: Optional[int] = None
    end_time_override: Optional[datetime] = None


class AttemptOut(BaseModel):
    id: UUID
    quiz_id: UUID
    student_id: UUID
    attempt_number: int
    started_at: Optional[datetime] = None
    submitted_at: Optional[datetime] = None
    total_score: Optional[float] = None
    status: Optional[str] = None
    tab_switch_count: int
    full_screen_violations: int
    cheating_flag: bool
    time_spent_seconds: Optional[int] = None
    created_at: datetime


class ProctoringEvent(BaseModel):
    event_type: str   # "tab_switch" | "fullscreen_exit"
    count: int = 1


class ManualGradeIn(BaseModel):
    answer_id: UUID
    score_awarded: float = Field(..., ge=0)
    is_correct: Optional[bool] = None


class StudentAnswerOut(BaseModel):
    id: UUID
    attempt_id: UUID
    question_id: UUID
    selected_option_id: Optional[UUID] = None
    answer_text: Optional[str] = None
    time_spent_seconds: Optional[int] = None
    score_awarded: Optional[float] = None
    is_correct: Optional[bool] = None
    evaluated_by: Optional[UUID] = None
    evaluated_at: Optional[datetime] = None

