# 🎓 Quiz Platform API — Dev Setup

FastAPI + asyncpg + Supabase. Hot reload, full error traces, seed script, tests included.

---

## ⚡ Quick Start (5 minutes)

### 1 · Get your Supabase credentials

1. Go to [supabase.com](https://supabase.com) → your project
2. **Settings → API** → copy **JWT Secret**
3. **Settings → Database → Connection string (URI)** → copy the URI

### 2 · Configure `.env`

```bash
cp .env.example .env
# Open .env and fill in SUPABASE_JWT_SECRET and DATABASE_URL
```

### 3 · Install and run

```bash
pip install -r requirements.txt
python run.py
```

API is live at **http://localhost:8000**
Interactive docs at **http://localhost:8000/docs**

### 4 · (Optional) Seed test data

```bash
python seed.py
```

> ⚠️  You must first create the seed user UUIDs in **Supabase → Authentication → Add user**
> and use those UUIDs in `seed.py` (or swap the fixed UUIDs with real ones from your project).

### 5 · Run tests

```bash
pytest tests/ -v
```

---

## 🐳 Docker (dev hot-reload)

```bash
docker-compose up --build
```

---

## 📁 Project Layout

```
quiz_platform/
├── run.py                  ← Start dev server (uvicorn --reload)
├── seed.py                 ← Populate DB with test data
├── pytest.ini
├── requirements.txt
├── .env.example
├── Dockerfile.dev
├── docker-compose.yml
└── app/
    ├── main.py             ← App factory, CORS, error handler, router wiring
    ├── config.py           ← Settings (reads .env)
    ├── database.py         ← asyncpg pool
    ├── dependencies.py     ← JWT auth + role guards
    ├── routers/
    │   ├── profiles.py     ← /api/v1/profiles
    │   ├── courses.py      ← /api/v1/courses
    │   ├── questions.py    ← /api/v1/questions
    │   ├── quizzes.py      ← /api/v1/quizzes
    │   ├── attempts.py     ← /api/v1/attempts  (quiz taking flow)
    │   ├── analytics.py    ← /api/v1/analytics
    │   ├── announcements.py
    │   ├── messages.py
    │   └── admin.py        ← /api/v1/admin
    ├── schemas/            ← Pydantic v2 request/response models
    └── services/
        ├── grading.py      ← Auto-grade MCQ + negative marking
        └── activity.py     ← Audit log helper
tests/
    ├── conftest.py         ← AsyncClient fixture
    └── test_api.py         ← Smoke tests
```

---

## 🔐 Auth Flow

Every endpoint needs a Supabase Bearer JWT:
```
Authorization: Bearer <your_supabase_access_token>
```

Get a token via `supabase.auth.signInWithPassword()` on the client, or from
**Supabase Dashboard → Authentication → Users → three-dot menu → Get JWT**.

**Roles:** `admin` · `hod` · `teacher` · `student`
Set in `public.profiles.role`.

---

## 🎯 Quiz-Taking Flow

```
POST /api/v1/attempts/start/{quiz_id}         → get attempt_id
POST /api/v1/attempts/{id}/answers            → submit each answer (can re-answer)
POST /api/v1/attempts/{id}/proctoring         → report tab_switch / fullscreen_exit
POST /api/v1/attempts/{id}/submit             → finish, get total_score back
GET  /api/v1/attempts/{id}                    → view result (if show_results_immediately)
```

---

## 🌱 Dev Differences vs Production

| Feature | Dev | Production |
|---|---|---|
| `debug=True` | ✅ | ❌ |
| Full tracebacks in JSON responses | ✅ | ❌ |
| CORS | `*` (all) | Restricted origins |
| DB pool size | 2–5 connections | 5–20 connections |
| Uvicorn workers | 1 (with reload) | 4+ |
| GZip compression | off | on |
| Log level | DEBUG | INFO |
| `.env` defaults | generous | all required |

---

## 📬 Example Requests

```bash
# Health check
curl http://localhost:8000/health

# List my courses (as authenticated student)
curl -H "Authorization: Bearer <jwt>" http://localhost:8000/api/v1/courses

# Create a question (as teacher)
curl -X POST http://localhost:8000/api/v1/questions \
  -H "Authorization: Bearer <jwt>" \
  -H "Content-Type: application/json" \
  -d '{
    "course_id": "...",
    "question_text": "What is O(log n)?",
    "question_type": "mcq_single",
    "marks": 2,
    "negative_marks": 0.5,
    "options": [
      {"option_text": "Binary search complexity", "is_correct": true},
      {"option_text": "Bubble sort complexity",  "is_correct": false}
    ]
  }'
```

