from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from app.dependencies import require_student
from app.schemas.insights import InsightsRequest
from app.services.groq_client import generate_ai_insights
import traceback

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.post("/student/insights")
async def generate_insights(
    body: InsightsRequest,
    current_user: dict = Depends(require_student),
):
    try:
        print("Received body:", body)

        insights = await generate_ai_insights(
            body.stats,
            body.subjects,
            body.attempts
        )

        print("Generated insights:", insights)

        return insights

    except Exception as e:
        traceback.print_exc()

        return JSONResponse(
            status_code=502,
            content={
                "error": str(e),
                "type": type(e).__name__
            }
        )