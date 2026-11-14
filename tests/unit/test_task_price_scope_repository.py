import asyncio

from src.domain.models.task import PriceScope, Task
from src.infrastructure.persistence.sqlite_task_repository import SqliteTaskRepository


def _task_with_scope() -> Task:
    return Task(
        task_name="m4pro",
        enabled=True,
        keyword="MacBook Pro M4 Pro",
        description="24-48G",
        max_pages=1,
        personal_only=True,
        min_price=None,
        max_price=None,
        cron=None,
        ai_prompt_base_file="prompts/base_prompt.txt",
        ai_prompt_criteria_file="prompts/macbook_pro_m4_pro_criteria.txt",
        price_scope=PriceScope(
            mode="config",
            match={"chip": "m4pro", "memory_gb": [24, 48]},
            bucket_by=["chip", "memory_gb", "storage_gb"],
            window_days=30,
            min_samples=5,
            fallback=["drop_storage"],
        ),
        is_running=False,
    )


def test_task_price_scope_roundtrips_through_sqlite(tmp_path):
    repository = SqliteTaskRepository(
        db_path=str(tmp_path / "app.sqlite3"),
        legacy_config_file=None,
    )

    saved = asyncio.run(repository.save(_task_with_scope()))
    loaded = asyncio.run(repository.find_by_id(saved.id))

    assert loaded is not None
    assert loaded.price_scope.mode == "config"
    assert loaded.price_scope.match == {"chip": "m4pro", "memory_gb": [24, 48]}
    assert loaded.price_scope.bucket_by == ["chip", "memory_gb", "storage_gb"]
    assert loaded.price_scope.min_samples == 5
