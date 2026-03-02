from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from datetime import datetime
from uuid import UUID


class OptionCreate(BaseModel):
    option_text: str
    media_url: Optional[str] = None
    is_correct: bool = False


class OptionOut(BaseModel):
    id: UUID
    option_text: str
    media_url: Optional[str] = None
    is_correct: bool


class OptionOutStudent(BaseModel):
    """Shown to students – no is_correct field."""
    id: UUID
    option_text: str
    media_url: Optional[str] = None


class QuestionCreate(BaseModel):
    course_id: UUID
    question_text: str = Field(..., min_length=5)
    question_type: Literal["mcq_single", "mcq_multiple", "true_false", "short", "descriptive"]
    difficulty: Optional[Literal["easy", "medium", "hard"]] = None
    topic: Optional[str] = None
    marks: float = Field(..., ge=0)
    negative_marks: float = Field(0.0, ge=0)
    explanation: Optional[str] = None
    media_url: Optional[str] = None
    options: List[OptionCreate] = []
    tags: List[str] = []


class QuestionUpdate(BaseModel):
    question_text: Optional[str] = Field(None, min_length=5)
    difficulty: Optional[Literal["easy", "medium", "hard"]] = None
    topic: Optional[str] = None
    marks: Optional[float] = Field(None, ge=0)
    negative_marks: Optional[float] = Field(None, ge=0)
    explanation: Optional[str] = None
    media_url: Optional[str] = None
    options: Optional[List[OptionCreate]] = None
    tags: Optional[List[str]] = None


class QuestionOut(BaseModel):
    id: UUID
    course_id: Optional[UUID] = None
    created_by: Optional[UUID] = None
    question_text: str
    question_type: str
    difficulty: Optional[str] = None
    topic: Optional[str] = None
    marks: float
    negative_marks: float
    explanation: Optional[str] = None
    media_url: Optional[str] = None
    is_active: bool
    version: int
    created_at: datetime
    options: List[OptionOut] = []
    tags: List[str] = []

