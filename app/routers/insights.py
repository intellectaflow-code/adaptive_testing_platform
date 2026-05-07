from fastapi import APIRouter, Depends, HTTPException
from app.dependencies import require_student
from app.schemas.insights import InsightsRequest
from app.services.groq_client import generate_ai_insights

router = APIRouter(prefix="/analytics", tags=["Analytics"])

# ── Insights ──────────────────────────────────────────────────────────────────

@router.post("/student/insights")
async def generate_insights(
    body: InsightsRequest,
    current_user: dict = Depends(require_student),
):
    try:
        insights = await generate_ai_insights(body.stats, body.subjects, body.attempts)
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e))

    return insights