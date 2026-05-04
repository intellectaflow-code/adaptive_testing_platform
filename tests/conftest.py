import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.dependencies import get_current_user


# Mock student user
def mock_student():
    return {
        "id": "11111111-1111-1111-1111-111111111111",
        "role": "student",
        "branch": "CSE"
    }


# Mock teacher user
def mock_teacher():
    return {
        "id": "22222222-2222-2222-2222-222222222222",
        "role": "teacher",
        "branch": "CSE"
    }


@pytest.fixture
def student_client():
    app.dependency_overrides[get_current_user] = mock_student
    yield TestClient(app)
    app.dependency_overrides = {}


@pytest.fixture
def teacher_client():
    app.dependency_overrides[get_current_user] = mock_teacher
    yield TestClient(app)
    app.dependency_overrides = {}