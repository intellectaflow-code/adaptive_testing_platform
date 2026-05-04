import logging
import sys
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import create_pool, close_pool
from app.routers import (
    departments, profiles, courses, questions, quizzes,
    attempts, analytics, announcements, messages, admin, auth, teachers_dashboard, syllabus_to_quiz, settings,ai_quiz, assignments
)



# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logging.getLogger("asyncpg").setLevel(logging.WARNING)
logger = logging.getLogger("quiz")

config = get_settings()  # renamed from 'settings' to 'config' to avoid conflict


# ── Lifespan ─────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 60)
    logger.info("  Quiz Platform API   ")
    logger.info("  ENV:      %s", config.app_env)
    logger.info("  DEBUG:    %s", config.debug)
    logger.info("  ORIGINS:  %s", config.allowed_origins)
    logger.info("=" * 60)
    await create_pool()
    yield
    await close_pool()
    logger.info("Shutdown complete.")


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Quiz Platform API  [DEV]",
    description=(
        "College quiz/test platform – admin · teacher · HOD · student.\n\n"
        "**Dev mode:** full error traces, open CORS, debug logging.\n\n"
        "📌 All routes are prefixed `/api/v1`"
    ),
    version="1.0.0-dev",
    debug=True,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS – open in dev ────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://adaptivetestingplatfromteachers-759082157852.us-central1.run.app","https://adaptivetestingplatfromstudents-759082157852.us-central1.run.app","https://intellectaflow.com","https://www.intellectaflow.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Dev error handler ─────────────────────────────────────────────────────────
@app.exception_handler(Exception)
async def dev_exception_handler(request: Request, exc: Exception):
    tb = traceback.format_exc()
    logger.error("Unhandled exception on %s %s\n%s", request.method, request.url.path, tb)
    return JSONResponse(
        status_code=500,
        content={
            "detail": str(exc),
            "type": type(exc).__name__,
            "traceback": tb.splitlines(),
        },
    )


# ── Request logger ────────────────────────────────────────────────────────────
import time

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    ms = (time.perf_counter() - start) * 1000
    logger.debug("%-6s %-40s  %s  %.0fms",
                 request.method, request.url.path, response.status_code, ms)
    return response


# ── Routers ───────────────────────────────────────────────────────────────────
PREFIX = "/api/v1"
app.include_router(auth.router,                 prefix=PREFIX)
app.include_router(profiles.router,             prefix=PREFIX)
app.include_router(courses.router,              prefix=PREFIX)
app.include_router(questions.router,            prefix=PREFIX)
app.include_router(quizzes.router,              prefix=PREFIX)
app.include_router(attempts.router,             prefix=PREFIX)
app.include_router(analytics.router,            prefix=PREFIX)
app.include_router(announcements.router,        prefix=PREFIX)
app.include_router(messages.router,             prefix=PREFIX)
app.include_router(admin.router,                prefix=PREFIX)
app.include_router(teachers_dashboard.router,   prefix=PREFIX)
app.include_router(syllabus_to_quiz.router,     prefix=PREFIX)
app.include_router(settings.router,             prefix=PREFIX)
app.include_router(ai_quiz.router,              prefix=PREFIX)
app.include_router(departments.router,          prefix=PREFIX)
app.include_router(assignments.router,          prefix=PREFIX)


# ── Health / root ─────────────────────────────────────────────────────────────
@app.get("/health", tags=["Dev"])
async def health():
    return {"status": "ok", "env": config.app_env, "debug": config.debug}


@app.get("/", tags=["Dev"])
async def root():
    return {
        "message": "Quiz Platform API – Dev Mode",
        "docs": "/docs",
        "redoc": "/redoc",
        "health": "/health",
    }
