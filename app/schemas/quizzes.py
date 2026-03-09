from pydantic import BaseModel, Field, model_validator
from typing import Optional, List
from datetime import datetime
from uuid import UUID


class QuizQuestionAdd(BaseModel):
    question_id: UUID
    question_order: Optional[int] = None
    marks_override: Optional[float] = Field(None, ge=0)


class QuizCreate(BaseModel):
    course_id: UUID
    title: str = Field(..., min_length=3, max_length=500)
    description: Optional[str] = None
    total_marks: Optional[float] = None
    passing_marks: Optional[float] = None
    duration_minutes: Optional[int] = Field(None, ge=1)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    randomize_questions: bool = False
    randomize_options: bool = False
    allow_multiple_attempts: bool = False
    max_attempts: int = Field(1, ge=1)
    show_results_immediately: bool = False
    questions: List[QuizQuestionAdd] = []
    

    @model_validator(mode="after")
    def check_times(self):
        if self.start_time and self.end_time:
            if self.end_time <= self.start_time:
                raise ValueError("end_time must be after start_time")
        return self


class QuizUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=3, max_length=500)
    description: Optional[str] = None
    total_marks: Optional[float] = None
    passing_marks: Optional[float] = None
    duration_minutes: Optional[int] = Field(None, ge=1)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    randomize_questions: Optional[bool] = None
    randomize_options: Optional[bool] = None
    allow_multiple_attempts: Optional[bool] = None
    max_attempts: Optional[int] = Field(None, ge=1)
    show_results_immediately: Optional[bool] = None


class QuizOut(BaseModel):
    id: UUID
    course_id: Optional[UUID] = None
    created_by: Optional[UUID] = None
    title: str
    description: Optional[str] = None
    total_marks: Optional[float] = None
    passing_marks: Optional[float] = None
    duration_minutes: Optional[int] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    randomize_questions: bool
    randomize_options: bool
    allow_multiple_attempts: bool
    max_attempts: int
    show_results_immediately: bool
    is_published: bool
    is_archived: bool
    created_at: datetime
    updated_at: datetime
    question_count: Optional[int] = None
    test_id: Optional[str] = None


class QuizPermissionCreate(BaseModel):
    student_id: UUID
    extra_time_minutes: int = Field(0, ge=0)
    allowed_attempts: Optional[int] = Field(None, ge=1)
    override_end_time: Optional[datetime] = None


class QuizPermissionOut(BaseModel):
    id: UUID
    quiz_id: UUID
    student_id: UUID
    extra_time_minutes: int
    allowed_attempts: Optional[int] = None
    override_end_time: Optional[datetime] = None
    granted_by: Optional[UUID] = None
    granted_at: datetime

