"""推荐结果与一年持有成本路由。"""

from fastapi import APIRouter, Query

from src.services.recommendation_service import build_recommendation_summary


router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])


@router.get("/summary")
async def get_recommendation_summary(
    task: str | None = Query(None, description="按任务名子串过滤"),
    top: int = Query(20, ge=1, le=200, description="返回的榜单条数"),
):
    """返回 AI 推荐配置、买入性价比和一年持有亏损估算。"""
    data = build_recommendation_summary(task)
    rows = data["rows"]
    data["top"] = rows[:top]
    data["hold_top"] = sorted(
        [row for row in rows if row["hold_score"] is not None],
        key=lambda row: row["hold_score"],
        reverse=True,
    )[:top]
    return data
