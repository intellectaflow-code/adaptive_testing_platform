from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from uuid import UUID


class StudentPerformanceOut(BaseModel):
    id: UUID
    student_id: UUID
    course_id: UUID
    quizzes_taken: int
    average_score: float
    highest_score: Optional[float] = None
    lowest_score: Optional[float] = None
    improvement_rate: Optional[float] = None
    last_updated: datetime


class DashboardStats(BaseModel):
    tests_taken: int
    avg_score: float = 0
    best_score: float = 0

class SubjectPerformance(BaseModel):
    subject: str
    tests_taken: int
    avg_score: float

class ScoreTrend(BaseModel):
    quiz: str
    total_score: float
    class_avg: float
    submitted_at: datetime


class Attempt(BaseModel):
    attempt_id: str
    test_title: str
    subject: str
    score: float
    time_spent_seconds: Optional[int] = None
    tab_switch_count: Optional[int] = None 
    attempt_date: datetime
    type: str


class LeaderboardEntry(BaseModel):
    rank: int
    student_id: UUID
    name: str
    score: float
    isMe: Optional[bool] = False
    initials: Optional[str] = None

class ReportStudent(BaseModel):
    name: str
    usn: str
    branch: str
    section: str
 
class ReportStats(BaseModel):
    tests_taken: int
    avg_score: float
    best_score: float
 
class ReportSubject(BaseModel):
    name: str
    score: float
    tests: int
 
class ReportAttempt(BaseModel):
    title: str
    subject: str
    attempt_date: str          # ISO date string  "2025-04-28"
    score: float
    time_spent_seconds: int
 
class StudentReportRequest(BaseModel):
    student: ReportStudent
    stats: ReportStats
    subjects: List[ReportSubject]
    attempts: List[ReportAttempt]
