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
    course_name: Optional[str] = None  
    course_code: Optional[str] = None 
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


class QuizTemplateBase(BaseModel):
    title: str
    total_versions: int = Field(default=6, ge=1)
    questions_per_quiz: int = Field(default=20, ge=1)

class QuizTemplateCreate(QuizTemplateBase):
    pass

class QuizTemplate(QuizTemplateBase):
    id: UUID
    teacher_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True

class TemplatePoolItem(BaseModel):
    question_id: UUID
    is_anchor: bool = False

class AddQuestionsToPool(BaseModel):
    template_id: UUID
    questions: List[TemplatePoolItem]

class TemplatePoolResponse(BaseModel):
    template_id: UUID
    question_id: UUID
    is_anchor: bool
    # We include details for the UI
    question_text: Optional[str] = None

class GenerateVariantsRequest(BaseModel):
    template_id: UUID
    student_ids: List[UUID] # The 60 students to be distributed

class QuizAssignmentOut(BaseModel):
    id: UUID
    student_id: UUID
    quiz_id: UUID
    assigned_at: datetime
    # Nested quiz info so the student knows what to take
    quiz_title: str

class QuizTemplateCreate(BaseModel):
    title: str
    total_versions: int = 6
    questions_per_quiz: int = 20

class QuizTemplateOut(QuizTemplateCreate):
    id: UUID
    teacher_id: UUID
    created_at: datetime

# Question Pool Management
class PoolItem(BaseModel):
    question_id: UUID
    is_anchor: bool = False

class AddToPoolRequest(BaseModel):
    questions: List[PoolItem]

# Generation Request
class GenerateRequest(BaseModel):
    student_ids: List[UUID]

class QuizSubmission(BaseModel):
    answers: List[dict]  # Expects [{"question_id": "...", "selected_answer": "..."}]
    tab_switches: int = 0
    time_spent: int = 0