import asyncio
from types import SimpleNamespace

from src.services import scheduler_service
from src.services.scheduler_service import SchedulerService


class DummyProcessService:
    async def start_task(self, task_id: int, task_name: str) -> bool:
        return True


def _make_task(
    task_id: int = 1,
    task_name: str = "demo",
    cron: str = "5 8,12,16,20 * * *",
    enabled: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(id=task_id, task_name=task_name, cron=cron, enabled=enabled)


def test_resolve_misfire_grace_seconds_defaults_and_env(monkeypatch):
    monkeypatch.delenv(scheduler_service.MISFIRE_GRACE_ENV, raising=False)
    assert (
        scheduler_service.resolve_misfire_grace_seconds()
        == scheduler_service.DEFAULT_MISFIRE_GRACE_SECONDS
    )

    monkeypatch.setenv(scheduler_service.MISFIRE_GRACE_ENV, "120")
    assert scheduler_service.resolve_misfire_grace_seconds() == 120

    monkeypatch.setenv(scheduler_service.MISFIRE_GRACE_ENV, "abc")
    assert (
        scheduler_service.resolve_misfire_grace_seconds()
        == scheduler_service.DEFAULT_MISFIRE_GRACE_SECONDS
    )


def test_reload_jobs_passes_misfire_grace_and_coalesce(monkeypatch):
    service = SchedulerService(DummyProcessService())
    recorded = {}

    monkeypatch.setattr(service.scheduler, "remove_all_jobs", lambda: None)
    monkeypatch.setattr(
        service.scheduler,
        "add_job",
        lambda func, **kwargs: recorded.update(kwargs),
    )

    asyncio.run(service.reload_jobs([_make_task()]))

    assert recorded["id"] == "task_1"
    assert recorded["replace_existing"] is True
    assert (
        recorded["misfire_grace_time"]
        == scheduler_service.DEFAULT_MISFIRE_GRACE_SECONDS
    )
    assert recorded["coalesce"] is True
    assert recorded["max_instances"] == 1


def test_reload_jobs_registers_job_with_grace(monkeypatch):
    """确保真正注册到 APScheduler 的 job 也带着宽限配置（防止默认 1 秒丢任务）。"""
    monkeypatch.delenv(scheduler_service.MISFIRE_GRACE_ENV, raising=False)

    async def scenario():
        service = SchedulerService(DummyProcessService())
        await service.reload_jobs([_make_task()])
        service.scheduler.start(paused=True)
        try:
            job = service.scheduler.get_job("task_1")
            assert job is not None
            return job.misfire_grace_time, job.coalesce, job.max_instances
        finally:
            service.scheduler.shutdown(wait=False)

    assert asyncio.run(scenario()) == (
        scheduler_service.DEFAULT_MISFIRE_GRACE_SECONDS,
        True,
        1,
    )


def test_reload_jobs_skips_disabled_and_empty_cron(monkeypatch):
    service = SchedulerService(DummyProcessService())
    added = []

    monkeypatch.setattr(service.scheduler, "remove_all_jobs", lambda: None)
    monkeypatch.setattr(
        service.scheduler,
        "add_job",
        lambda func, **kwargs: added.append(kwargs["id"]),
    )

    asyncio.run(
        service.reload_jobs(
            [
                _make_task(task_id=1, enabled=False),
                _make_task(task_id=2, cron=""),
            ]
        )
    )

    assert added == []
