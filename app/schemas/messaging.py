from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from uuid import UUID


class AnnouncementCreate(BaseModel):
    course_id: Optional[UUID] = None
    title: str = Field(..., min_length=3, max_length=500)
    message: str = Field(..., min_length=5)


class AnnouncementUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=3)
    message: Optional[str] = Field(None, min_length=5)
    is_active: Optional[bool] = None


class AnnouncementOut(BaseModel):
    id: UUID
    course_id: Optional[UUID] = None
    created_by: Optional[UUID] = None
    title: str
    message: str
    is_active: bool
    created_at: datetime

    teacher_name: Optional[str] = None   # ✅ ADD
    course_name: Optional[str] = None


class MessageCreate(BaseModel):
    receiver_id: UUID
    message: str = Field(..., min_length=1, max_length=5000)


class MessageOut(BaseModel):
    id: UUID
    sender_id: Optional[UUID] = None
    receiver_id: Optional[UUID] = None
    message: str
    is_read: bool
    created_at: datetime

