"""
tests/test_api.py – basic smoke tests.

These test the API layer without hitting a real DB.
For full integration tests set a real DATABASE_URL in .env and use seed.py first.
"""
import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_health(client: AsyncClient):
    r = await client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "env" in data


@pytest.mark.anyio
async def test_root(client: AsyncClient):
    r = await client.get("/")
    assert r.status_code == 200
    assert "docs" in r.json()


@pytest.mark.anyio
async def test_no_token_returns_403(client: AsyncClient):
    """Calling a protected endpoint without a token should return 403 (no bearer)."""
    r = await client.get("/api/v1/profiles/me")
    assert r.status_code in (401, 403)


@pytest.mark.anyio
async def test_bad_token_returns_401(client: AsyncClient):
    r = await client.get(
        "/api/v1/profiles/me",
        headers={"Authorization": "Bearer this.is.garbage"},
    )
    assert r.status_code == 401
    assert "Invalid token" in r.json()["detail"]


@pytest.mark.anyio
async def test_create_question_requires_teacher(client: AsyncClient):
    """Students (or no-auth) cannot create questions."""
    r = await client.post(
        "/api/v1/questions",
        json={
            "course_id": "00000000-0000-0000-0000-000000000010",
            "question_text": "What is 2+2?",
            "question_type": "mcq_single",
            "marks": 1,
        },
        headers={"Authorization": "Bearer this.is.garbage"},
    )
    assert r.status_code == 401


@pytest.mark.anyio
async def test_quiz_list_no_auth(client: AsyncClient):
    r = await client.get("/api/v1/quizzes")
    assert r.status_code in (401, 403)


@pytest.mark.anyio
async def test_openapi_docs_available(client: AsyncClient):
    r = await client.get("/docs")
    assert r.status_code == 200


@pytest.mark.anyio
async def test_openapi_json(client: AsyncClient):
    r = await client.get("/openapi.json")
    assert r.status_code == 200
    schema = r.json()
    # Check our main route groups are present
    paths = schema["paths"]
    assert "/api/v1/quizzes" in paths
    assert "/api/v1/questions" in paths
    assert "/api/v1/profiles/me" in paths
    assert "/api/v1/admin/dashboard" in paths

