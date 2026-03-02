from fastapi import APIRouter, Depends, HTTPException, status, Request
import asyncpg

from app.database import get_db
from app.schemas.auth import RegisterRequest, LoginRequest, AuthResponse, RefreshRequest
from app.services.supabase_client import get_supabase
from app.dependencies import get_current_user
from app.services.activity import log_activity

router = APIRouter(prefix="/auth", tags=["Auth"])


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
            "email_confirm": True,  # auto-confirm for now
        })
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Supabase error: {str(e)}")

    user = res.user
    if not user:
        raise HTTPException(status_code=400, detail="Failed to create user")

    # 2. Create profile in your DB
    try:
        await db.execute(
            """
            INSERT INTO public.profiles (id, email, full_name, role, branch, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, now(), now())
            ON CONFLICT (id) DO NOTHING
            """,
            user.id, body.email, body.full_name, body.role, body.branch,
        )
    except Exception as e:
        # Rollback: delete the Supabase user if profile creation fails
        supabase.auth.admin.delete_user(user.id)
        raise HTTPException(status_code=500, detail=f"Profile creation failed: {str(e)}")

    # 3. Sign in to get tokens
    sign_in = supabase.auth.sign_in_with_password({
        "email": body.email,
        "password": body.password,
    })

    await log_activity(db, str(user.id), "register",
                       request.client.host if request.client else None)

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