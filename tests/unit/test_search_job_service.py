import asyncio
import json
from pathlib import Path

from src.domain.models.search_job import SearchJob, SearchJobRequest
from src.services.search_job_service import (
    SearchJobService,
    build_collector_config,
    count_result_lines,
    flatten_record,
)


def _service(tmp_path, monkeypatch, **kwargs) -> SearchJobService:
    monkeypatch.setenv("APP_DATABASE_FILE", str(tmp_path / "app.sqlite3"))
    monkeypatch.chdir(tmp_path)
    return SearchJobService(job_root=str(tmp_path / "data" / "search_jobs"), **kwargs)


def _job(tmp_path, **overrides) -> SearchJob:
    payload = {
        "id": "j1",
        "task_name": "search-j1",
        "keyword": "MacBook Pro M4 Pro",
        "max_pages": 2,
        "min_price": 5000.0,
        "max_price": 12000.0,
        "region": "上海",
        "personal_only": True,
        "created_at": "2026-11-14T10:00:00",
        "job_dir": str(tmp_path / "data" / "search_jobs" / "j1"),
    }
    payload.update(overrides)
    return SearchJob(**payload)


def test_build_collector_config_is_isolated(tmp_path):
    job = _job(tmp_path)
    payload = build_collector_config(
        job, Path(job.job_dir) / "result.jsonl", Path(job.job_dir) / "log.txt"
    )

    task = payload[0]
    assert task["keyword"] == "MacBook Pro M4 Pro"
    assert task["decision_mode"] == "keyword"
    assert task["keyword_rules"] == []
    assert task["cron"] == ""
    assert task["enabled"] is True
    assert task["min_price"] == "5000.0"
    assert task["max_price"] == "12000.0"
    assert task["region"] == "上海"
    assert task["collector"]["enabled"] is True
    assert task["collector"]["result_path"].endswith("result.jsonl")
    # 采集任务不该带定时任务的字段
    assert "price_scope" not in task


def test_flatten_record_extracts_spec_and_price():
    record = {
        "爬取时间": "2026-11-14T10:00:00",
        "商品信息": {
            "商品ID": "123",
            "商品标题": "MacBook Pro M4 Pro 24G+512G 国行",
            "当前售价": "¥10500",
            "发货地区": "上海",
            "商品链接": "https://www.goofish.com/item?id=123",
        },
        "卖家信息": {"卖家昵称": "小王"},
    }

    item = flatten_record(record)

    assert item["item_id"] == "123"
    assert item["price"] == 10500.0
    assert item["region"] == "上海"
    assert item["seller"] == "小王"
    assert item["spec"]["chip"] == "m4pro"
    assert item["spec"]["memory_gb"] == 24
    assert item["spec"]["storage_gb"] == 512
    assert item["spec"]["region"] == "国行"


def test_submit_creates_job_dir_config_and_row(tmp_path, monkeypatch):
    service = _service(tmp_path, monkeypatch)

    job = asyncio.run(
        service.submit(SearchJobRequest(keyword="MacBook Pro M4 Pro", max_pages=2))
    )

    job_dir = Path(job.job_dir)
    config = json.loads((job_dir / "config.json").read_text(encoding="utf-8"))
    assert config[0]["collector"]["enabled"] is True
    assert config[0]["task_name"] == job.task_name

    loaded = asyncio.run(service.get(job.id))
    assert loaded is not None
    assert loaded.status == "queued"
    assert loaded.keyword == "MacBook Pro M4 Pro"


def test_cancel_queued_job_marks_canceled(tmp_path, monkeypatch):
    service = _service(tmp_path, monkeypatch)
    job = asyncio.run(service.submit(SearchJobRequest(keyword="M3 Max")))

    canceled = asyncio.run(service.cancel(job.id))

    assert canceled.status == "canceled"
    assert service.is_active() is False


def test_worker_waits_until_scheduled_task_is_idle(tmp_path, monkeypatch):
    service = _service(tmp_path, monkeypatch)
    service._idle_poll_seconds = 0.02
    state = {"busy": True}
    service.bind_busy_check(lambda: state["busy"])

    async def fake_execute(job):
        job.status = "succeeded"
        job.finished_at = "2026-11-14T10:10:00"
        job.result_count = 0
        await asyncio.to_thread(service._repo.update, job)

    monkeypatch.setattr(service, "_execute", fake_execute)

    async def scenario():
        await service.start()
        try:
            job = await service.submit(SearchJobRequest(keyword="M4 Max"))
            await asyncio.sleep(0.1)
            assert (await service.get(job.id)).status == "queued"

            state["busy"] = False
            current = None
            for _ in range(100):
                current = await service.get(job.id)
                if current.status == "succeeded":
                    break
                await asyncio.sleep(0.02)
            assert current.status == "succeeded"
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_results_are_paged_and_flattened(tmp_path, monkeypatch):
    service = _service(tmp_path, monkeypatch)
    job = _job(tmp_path)
    job_dir = Path(job.job_dir)
    job_dir.mkdir(parents=True, exist_ok=True)
    records = [
        {
            "商品信息": {
                "商品ID": "1",
                "商品标题": "MacBook Pro M4 Pro 24G+512G",
                "当前售价": "10000",
            }
        },
        {
            "商品信息": {
                "商品ID": "2",
                "商品标题": "MacBook Pro M4 Max 36G+1T",
                "当前售价": "18000",
            }
        },
    ]
    (job_dir / "result.jsonl").write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )
    service._repo.save(job)

    assert count_result_lines(job_dir / "result.jsonl") == 2

    page = asyncio.run(service.results(job.id, offset=1, limit=1))
    assert page["total"] == 2
    assert page["offset"] == 1
    assert len(page["items"]) == 1
    assert page["items"][0]["item_id"] == "2"
