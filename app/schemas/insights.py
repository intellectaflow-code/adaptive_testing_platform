from pydantic import BaseModel
from typing import Optional, List


class SubjectIn(BaseModel):
    name: str
    score: float
    tests: int


class AttemptIn(BaseModel):
    title: str
    subject: str
    score: float
    attempt_date: Optional[str] = None


class StatsIn(BaseModel):
    tests_taken: int
    avg_score: float
    best_score: float
    streak: int
    tests_this_week: int


class InsightsRequest(BaseModel):
    stats: StatsIn
    subjects: List[SubjectIn]
    attempts: List[AttemptIn]