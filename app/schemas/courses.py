from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
from uuid import UUID


class CourseCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=300)
    code: Optional[str] = None
    semester: Optional[int] = Field(None, ge=1, le=10)
    branch: Optional[str] = None


class CourseUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=300)
    code: Optional[str] = None
    semester: Optional[int] = Field(None, ge=1, le=10)
    branch: Optional[str] = None


class CourseOut(BaseModel):
    id: UUID
    name: str
    code: Optional[str] = None
    semester: Optional[int] = None
    branch: Optional[str] = None
    created_by: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime
    teacher_name: Optional[str] = None


class AssignTeacherIn(BaseModel):
    teacher_id: UUID


class EnrollStudentIn(BaseModel):
    student_id: UUID


class BulkEnrollRequest(BaseModel):
    course_id: str
    usns: List[str]
