from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.dependencies import get_search_job_service
from src.api.routes import search_jobs
from src.domain.models.search_job import SearchJob


def _job(job_id: str = "j1", status: str = "queued") -> SearchJob:
    return SearchJob(
        id=job_id,
        task_name=f"search-{job_id}",
        keyword="MacBook Pro M4 Pro",
        max_pages=1,
        status=status,
        created_at="2026-11-14T10:00:00",
        job_dir=f"/tmp/search_jobs/{job_id}",
    )


class FakeService:
    def __init__(self) -> None:
        self.jobs = {"j1": _job()}

    async def submit(self, payload):
        job = _job("j2")
        job.keyword = payload.keyword
        self.jobs[job.id] = job
        return job

    async def list(self, limit: int = 50):
        return list(self.jobs.values())

    async def details(self, job_id: str, log_lines: int = 40):
        job = self.jobs.get(job_id)
        if job is None:
            return None
        data = job.model_dump()
        data["log_tail"] = ["line-1", "line-2"]
        return data

    async def results(self, job_id: str, offset: int = 0, limit: int = 50):
        if job_id not in self.jobs:
            return None
        return {
            "job": self.jobs[job_id].model_dump(),
            "total": 1,
            "offset": offset,
            "limit": limit,
            "items": [{"item_id": "1", "title": "M4 Pro 24G+512G"}],
        }

    async def cancel(self, job_id: str):
        job = self.jobs.get(job_id)
        if job is None:
            return None
        job.status = "canceled"
        return job


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(search_jobs.router)
    app.dependency_overrides[get_search_job_service] = lambda: FakeService()
    return TestClient(app)


def test_submit_returns_202_and_job_id():
    response = _client().post("/api/search/jobs", json={"keyword": "M4 Pro"})

    assert response.status_code == 202
    body = response.json()
    assert body["id"] == "j2"
    assert body["keyword"] == "M4 Pro"
    assert body["status"] == "queued"


def test_submit_rejects_empty_keyword():
    response = _client().post("/api/search/jobs", json={"keyword": "   "})

    assert response.status_code == 422


def test_submit_rejects_inverted_price_range():
    response = _client().post(
        "/api/search/jobs", json={"keyword": "M4", "min_price": 9000, "max_price": 100}
    )

    assert response.status_code == 422


def test_list_and_detail():
    client = _client()

    listed = client.get("/api/search/jobs").json()
    assert [job["id"] for job in listed["jobs"]] == ["j1"]

    detail = client.get("/api/search/jobs/j1").json()
    assert detail["id"] == "j1"
    assert detail["log_tail"] == ["line-1", "line-2"]


def test_detail_missing_returns_404():
    assert _client().get("/api/search/jobs/nope").status_code == 404


def test_results_and_cancel():
    client = _client()

    results = client.get("/api/search/jobs/j1/results?offset=0&limit=10").json()
    assert results["total"] == 1
    assert results["items"][0]["item_id"] == "1"

    canceled = client.post("/api/search/jobs/j1/cancel").json()
    assert canceled["status"] == "canceled"
    assert client.post("/api/search/jobs/nope/cancel").status_code == 404
