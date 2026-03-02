from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from typing import Optional
import asyncpg
import httpx
from app.config import get_settings
from app.database import get_db

security = HTTPBearer()
_jwks_cache = None

async def get_supabase_jwks():
    global _jwks_cache
    if _jwks_cache is None:
        settings = get_settings()
        # Every Supabase project has this public endpoint
        jwks_url = f"{settings.supabase_url}/auth/v1/.well-known/jwks.json"
        async with httpx.AsyncClient() as client:
            resp = await client.get(jwks_url)
            _jwks_cache = resp.json()
    return _jwks_cache


def decode_token(token: str, jwks: dict) -> dict:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token=token,
            key=jwks,
            # settings = settings.supabase_jwt_secret,
            algorithms=["HS256", "RS256", "ES256"],
            options={"verify_aud": False,"verify_signature": True},
        )
        return payload
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {e}  |  Tip: Get a fresh JWT from Supabase Auth",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: asyncpg.Connection = Depends(get_db),
    jwks: dict = Depends(get_supabase_jwks) # Fetch keys first
) -> dict:
    payload = decode_token(credentials.credentials, jwks)
    user_id = payload.get("sub")

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has no 'sub' claim – is this a real Supabase JWT?",
        )

    row = await db.fetchrow(
        "SELECT * FROM public.profiles WHERE id = $1 AND is_deleted = false",
        user_id,
    )

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No profile found for user_id={user_id}. "
                "Run the seed script or create a profile row in Supabase."
            ),
        )

    if not row["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive. Set is_active=true in the profiles table.",
        )

    return dict(row)


# ── Role guards ───────────────────────────────────────────────────────────────

def require_roles(*roles: str):
    async def _guard(current_user: dict = Depends(get_current_user)):
        if current_user["role"] not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Your role is '{current_user['role']}'. "
                    f"This endpoint requires: {list(roles)}"
                ),
            )
        return current_user
    return _guard


require_admin        = require_roles("admin")
require_admin_or_hod = require_roles("admin", "hod")
require_teacher_up   = require_roles("admin", "hod", "teacher")
require_student      = require_roles("student")
require_any          = get_current_user

