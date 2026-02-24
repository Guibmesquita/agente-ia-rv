from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/health", tags=["Health"])


@router.get("/detailed")
async def health_detailed():
    from services.dependency_check import get_detailed_health
    result = get_detailed_health()

    status_code = 200
    if result["status"] == "critical":
        status_code = 503
    elif result["status"] == "degraded":
        status_code = 200

    return JSONResponse(content=result, status_code=status_code)
