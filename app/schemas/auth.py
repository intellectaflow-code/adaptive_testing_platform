from fastapi import HTTPException
from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: Optional[str] = None
    role: Optional[str] = "student"
    branch: Optional[str] = None

    @field_validator("email")
    @classmethod
    def validate_mite_domain(cls, v: str) -> str:
        if not v.endswith("@mite.ac.in"):
            raise HTTPException(
                status_code=400, 
                detail="Only @mite.ac.in email addresses are allowed."
            )
        return v.lower()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user_id: str
    email: str


class RefreshRequest(BaseModel):
    refresh_token: str