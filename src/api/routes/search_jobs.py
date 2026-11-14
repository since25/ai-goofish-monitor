"""一次性后台搜索任务路由。

与 ``/api/tasks`` 完全分开：这里的任务不进调度、不出现在任务列表，
结果只从任务自己的目录读取。
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.dependencies import get_search_job_service
from src.domain.models.search_job import SearchJobRequest
from src.services.search_job_service import SearchJobService

router = APIRouter(prefix="/api/search/jobs", tags=["search-jobs"])


@router.post("", status_code=202)
async def submit_search_job(
    payload: SearchJobRequest,
    service: SearchJobService = Depends(get_search_job_service),
):
    """提交一次后台搜索，立即返回 job_id。"""
    job = await service.submit(payload)
    return job.model_dump()


@router.get("")
async def list_search_jobs(
    limit: int = Query(20, ge=1, le=200),
    service: SearchJobService = Depends(get_search_job_service),
):
    jobs = await service.list(limit=limit)
    return {"jobs": [job.model_dump() for job in jobs]}


@router.get("/{job_id}")
async def get_search_job(
    job_id: str,
    log_lines: int = Query(40, ge=0, le=500),
    service: SearchJobService = Depends(get_search_job_service),
):
    data = await service.details(job_id, log_lines=log_lines)
    if data is None:
        raise HTTPException(status_code=404, detail="搜索任务不存在")
    return data


@router.get("/{job_id}/results")
async def get_search_job_results(
    job_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    service: SearchJobService = Depends(get_search_job_service),
):
    data = await service.results(job_id, offset=offset, limit=limit)
    if data is None:
        raise HTTPException(status_code=404, detail="搜索任务不存在")
    return data


@router.post("/{job_id}/cancel")
async def cancel_search_job(
    job_id: str,
    service: SearchJobService = Depends(get_search_job_service),
):
    job = await service.cancel(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="搜索任务不存在")
    return job.model_dump()
