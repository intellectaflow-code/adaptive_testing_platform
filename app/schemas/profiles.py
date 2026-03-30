from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime
from uuid import UUID


class ProfileCreate(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=200)
    role: Literal["admin", "teacher", "hod", "student"]
    branch: Optional[str] = None
    section: Optional[str] = None
    usn: Optional[str] = None
    email: str = Field(..., min_length=2, max_length=200)


class ProfileUpdate(BaseModel):
    full_name: Optional[str] = Field(None, min_length=2, max_length=200)
    branch: Optional[str] = None
    section: Optional[str] = None
    usn: Optional[str] = None
    sem: Optional[int] = None


class ProfileAdminUpdate(ProfileUpdate):
    role: Optional[Literal["admin", "teacher", "hod", "student"]] = None
    is_active: Optional[bool] = None


class ProfileOut(BaseModel):
    id: UUID
    full_name: str
    email: Optional[str] = None
    role: str
    branch: Optional[str] = None
    section: Optional[str] = None
    usn: Optional[str] = None
    sem: Optional[int] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class DepartmentOut(BaseModel):
    id: UUID
    name: str
    code: Optional[str] = None