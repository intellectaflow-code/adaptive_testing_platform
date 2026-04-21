from __future__ import annotations
from typing import List

import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator


# =====================================================
# ENUMS
# =====================================================

class SubmissionStatus(str, Enum):
    in_progress = "in_progress"
    submitted = "submitted"
    late_submitted = "late_submitted"
    evaluated = "evaluated"


# =====================================================
# BASE CONFIG
# =====================================================

class BaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# =====================================================
# TEACHER ASSIGNMENTS
# =====================================================

class TeacherAssignmentBase(BaseSchema):
    course_id: uuid.UUID
    title: str
    description: Optional[str] = None
    total_marks: Decimal = Decimal("0")
    passing_marks: Decimal = Decimal("0")
    start_time: Optional[datetime] = None
    due_time: Optional[datetime] = None
    allow_late_submission: bool = False
    published: bool = False

    @field_validator("passing_marks")
    @classmethod
    def passing_marks_lte_total(cls, v: Decimal, info) -> Decimal:
        total = info.data.get("total_marks")
        if total is not None and v > total:
            raise ValueError("passing_marks cannot exceed total_marks")
        return v


class TeacherAssignmentCreate(TeacherAssignmentBase):
    questions: list[TeacherAssignmentQuestionBase]


class TeacherAssignmentUpdate(BaseModel):
    course_id: uuid.UUID | None = None
    title: str | None = None
    description: str | None = None
    total_marks: float | None = None
    passing_marks: float | None = None
    start_time: datetime | None = None
    due_time: datetime | None = None
    allow_late_submission: bool | None = None
    published: bool | None = None
    questions: list[TeacherAssignmentQuestionBase] | None = None


class TeacherAssignmentResponse(TeacherAssignmentBase):
    id: uuid.UUID
    teacher_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class TeacherAssignmentDetail(TeacherAssignmentResponse):
    """Full assignment with nested questions."""
    questions: list[TeacherAssignmentQuestionResponse] = []


# =====================================================
# TEACHER ASSIGNMENT QUESTIONS
# =====================================================

class TeacherAssignmentQuestionBase(BaseSchema):
    question_id: uuid.UUID
    question_order: int = 1
    marks: Decimal = Decimal("0")


class TeacherAssignmentQuestionCreate(TeacherAssignmentQuestionBase):
    assignment_id: uuid.UUID


class TeacherAssignmentQuestionUpdate(BaseSchema):
    question_order: Optional[int] = None
    marks: Optional[Decimal] = None


class TeacherAssignmentQuestionResponse(TeacherAssignmentQuestionBase):
    id: uuid.UUID
    assignment_id: uuid.UUID
    created_at: datetime


# =====================================================
# STUDENT ASSIGNMENT SUBMISSIONS
# =====================================================

class StudentAssignmentSubmissionBase(BaseSchema):
    assignment_id: uuid.UUID
    student_id: uuid.UUID


class StudentAssignmentSubmissionCreate(StudentAssignmentSubmissionBase):
    pass


class StudentAssignmentSubmissionUpdate(BaseSchema):
    status: Optional[SubmissionStatus] = None
    submitted_at: Optional[datetime] = None
    total_score: Optional[Decimal] = None


class StudentAssignmentSubmissionResponse(StudentAssignmentSubmissionBase):
    id: uuid.UUID
    status: SubmissionStatus
    submitted_at: Optional[datetime]
    total_score: Decimal
    created_at: datetime
    updated_at: datetime


class StudentAssignmentSubmissionDetail(StudentAssignmentSubmissionResponse):
    """Full submission with nested answers."""
    answers: list[StudentAssignmentAnswerResponse] = []


# =====================================================
# STUDENT ASSIGNMENT ANSWERS
# =====================================================

class StudentAssignmentAnswerBase(BaseSchema):
    question_id: uuid.UUID
    answer_text: Optional[str] = None
    file_url: Optional[str] = None


class StudentAssignmentAnswerCreate(StudentAssignmentAnswerBase):
    submission_id: uuid.UUID


class StudentAssignmentAnswerUpdate(BaseSchema):
    answer_text: Optional[str] = None
    file_url: Optional[str] = None


class StudentAssignmentAnswerEvaluate(BaseSchema):
    """Payload for teacher evaluation of an answer."""
    score_awarded: Decimal
    feedback: Optional[str] = None
    evaluated_by: uuid.UUID


class StudentAssignmentAnswerResponse(StudentAssignmentAnswerBase):
    id: uuid.UUID
    submission_id: uuid.UUID
    score_awarded: Optional[Decimal]
    feedback: Optional[str]
    evaluated_by: Optional[uuid.UUID]
    evaluated_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class BulkAnswerCreate(BaseModel):
    answers: List[StudentAssignmentAnswerCreate]

# =====================================================
# FORWARD REF REBUILDS
# =====================================================
# These must come after all classes are defined
# to resolve forward references in nested schemas.

TeacherAssignmentDetail.model_rebuild()
StudentAssignmentSubmissionDetail.model_rebuild()