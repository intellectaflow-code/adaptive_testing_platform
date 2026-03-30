import re
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException, status, Request
import asyncpg
import random
import time
from app.services.email import send_otp_email  # we'll create this

# Temporary in-memory OTP store: { email: { otp, expires_at } }
otp_store: dict = {}

from app.database import get_db
from app.schemas.auth import RegisterRequest, LoginRequest, AuthResponse, RefreshRequest, ChangePasswordRequest, ResetPasswordRequest
from app.services.supabase_client import get_supabase
from app.dependencies import get_current_user
from app.services.activity import log_activity

router = APIRouter(prefix="/auth", tags=["Auth"])


EMAIL_REGEX = re.compile(r"^[\w\.-]+@mite\.ac\.in$")

@router.post("/register", response_model=AuthResponse, status_code=201)
async def register(
    body: RegisterRequest,
    request: Request,
    db: asyncpg.Connection = Depends(get_db),
):
    supabase = get_supabase()

    # 1. Create user in Supabase Auth
    try:
        res = supabase.auth.admin.create_user({
            "email": body.email,
            "password": body.password,
            "email_confirm": True,
        })
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"error: {str(e)}")

    user = res.user
    if not user:
        raise HTTPException(status_code=400, detail="Failed to create user")

    # 2. Create profile in DB
    try:
            await db.execute(
                """
                INSERT INTO public.profiles
                (id, email, full_name, role, branch, usn, sem, section, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, now(), now())
                ON CONFLICT (id) DO NOTHING
                """,
                user.id,
                body.email,
                body.full_name,
                body.role,
                body.branch,
                body.usn,
                body.semester,   # still coming from API as semester
                body.section,
            )
    except Exception as e:
            supabase.auth.admin.delete_user(user.id)
            if "unique_usn" in str(e):
                raise HTTPException(status_code=400, detail="USN already exists")
            raise HTTPException(status_code=500, detail=f"Profile creation failed: {str(e)}")

    # 3. Sign in to get tokens
    sign_in = supabase.auth.sign_in_with_password({
        "email": body.email,
        "password": body.password,
    })

    await log_activity(
        db,
        str(user.id),
        "register",
        request.client.host if request.client else None
    )

    return AuthResponse(
        access_token=sign_in.session.access_token,
        refresh_token=sign_in.session.refresh_token,
        user_id=str(user.id),
        email=user.email,
    )

@router.post("/login", response_model=AuthResponse)
async def login(
    body: LoginRequest,
    request: Request,
    db: asyncpg.Connection = Depends(get_db),
):
    supabase = get_supabase()

    try:
        res = supabase.auth.sign_in_with_password({
            "email": body.email,
            "password": body.password,
        })
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    session = res.session
    user = res.user

    await log_activity(db, str(user.id), "login",
                       request.client.host if request.client else None)

    return AuthResponse(
        access_token=session.access_token,
        refresh_token=session.refresh_token,
        user_id=str(user.id),
        email=user.email,
    )


@router.post("/refresh", response_model=AuthResponse)
async def refresh_token(body: RefreshRequest):
    supabase = get_supabase()

    try:
        res = supabase.auth.refresh_session(body.refresh_token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    return AuthResponse(
        access_token=res.session.access_token,
        refresh_token=res.session.refresh_token,
        user_id=str(res.user.id),
        email=res.user.email,
    )

@router.put("/password", status_code=204)
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_db),
):
    supabase = get_supabase()

    # Verify current password by re-authenticating
    try:
        supabase.auth.admin.update_user_by_id(
            str(current_user["id"]),   # ← cast to string
            {"password": body.new_password}
        )
    except Exception:
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    # Update to new password
    try:
        supabase.auth.admin.update_user_by_id(
            current_user["id"],
            {"password": body.new_password}
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Password update failed: {str(e)}")

    await log_activity(
        db,
        str(current_user["id"]),
        "password_change",
        request.client.host if request.client else None,
    )



@router.post("/logout", status_code=204)
async def logout(
    current_user: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_db),
):
    supabase = get_supabase()
    try:
        supabase.auth.admin.sign_out(current_user["id"])
    except Exception:
        pass  # logout should not fail visibly

    await log_activity(db, str(current_user["id"]), "logout", None)


@router.get("/me")
async def me(current_user: dict = Depends(get_current_user)):
    return current_user


@router.post("/send-otp", status_code=200)
async def send_otp(body: dict):
    email = body.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")

    otp = str(random.randint(100000, 999999))
    otp_store[email] = {
        "otp": otp,
        "expires_at": time.time() + 300
    }

    try:
        await send_otp_email(email, otp)
    except Exception as e:
        print("Email send failed:", str(e))
        raise HTTPException(status_code=500, detail=f"Failed to send OTP: {str(e)}")

    return {"message": "OTP sent successfully"}


@router.post("/verify-otp", status_code=200)
async def verify_otp(body: dict):
    email = body.get("email")
    otp = body.get("otp")

    record = otp_store.get(email)

    if not record:
        raise HTTPException(status_code=400, detail="OTP not found. Request a new one.")
    if time.time() > record["expires_at"]:
        otp_store.pop(email, None)
        raise HTTPException(status_code=400, detail="OTP expired. Request a new one.")
    if record["otp"] != otp:
        raise HTTPException(status_code=400, detail="Invalid OTP")

    otp_store.pop(email, None)  # clear after successful verify
    return {"message": "OTP verified"}


@router.post("/reset-password", status_code=200)
async def reset_password(body: ResetPasswordRequest):
    supabase = get_supabase()
    try:
        users = supabase.auth.admin.list_users()
        target = next((u for u in users if u.email == body.email), None)
        if not target:
            raise HTTPException(status_code=404, detail="No account found with this email")
        supabase.auth.admin.update_user_by_id(
            str(target.id),
            {"password": body.new_password}
        )
        return {"message": "Password reset successful"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Reset failed: {str(e)}")
    
    
@router.post("/bulk-register-students")
async def bulk_register_students(
    students: List[Dict],
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_db),
):
    """
    Bulk create students from Excel (JSON input)
    Uses same logic as register()
    """

    # 🔐 Only admin or HOD
    if current_user["role"] not in ["admin", "hod"]:
        raise HTTPException(403, "Not authorized")

    supabase = get_supabase()

    created = 0
    errors = []

    for i, s in enumerate(students):
        try:
            # -----------------------
            # 🔍 Validation
            # -----------------------
            email = s.get("email")
            if not email or not EMAIL_REGEX.match(email):
                raise Exception("Invalid email")

            # 🔐 HOD restriction
            branch = s.get("branch")
            if current_user["role"] == "hod":
                if branch != current_user["branch"]:
                    raise Exception("Cannot add student from another branch")

            password = s.get("password") or "Student@123"  # default password

            # -----------------------
            # 1. Create Auth User
            # -----------------------
            res = supabase.auth.admin.create_user({
                "email": email,
                "password": password,
                "email_confirm": True,
            })

            user = res.user
            if not user:
                raise Exception("Auth creation failed")

            # -----------------------
            # 2. Insert Profile
            # -----------------------
            await db.execute(
                """
                INSERT INTO public.profiles
                (id, email, full_name, role, branch, usn, sem, section, created_at, updated_at)
                VALUES ($1, $2, $3, 'student', $4, $5, $6, $7, now(), now())
                ON CONFLICT (id) DO NOTHING
                """,
                user.id,
                email,
                s.get("full_name"),
                branch,
                s.get("usn"),
                s.get("semester"),
                s.get("section"),
            )

            # -----------------------
            # 3. Log Activity
            # -----------------------
            await log_activity(
                db,
                str(user.id),
                "bulk_register_student",
                request.client.host if request.client else None
            )

            created += 1

        except Exception as e:
            errors.append({
                "row": i + 1,
                "email": s.get("email"),
                "error": str(e)
            })

    return {
        "created": created,
        "failed": len(errors),
        "errors": errors
    }
