import asyncio

from src.domain.models.task import PriceScope, Task
from src.infrastructure.persistence.sqlite_task_repository import SqliteTaskRepository
from src.services.price_history_service import record_market_snapshots
from src.services.result_file_service import enrich_records_with_price_insight


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
            min_samples=2,
            fallback=["drop_storage"],
        ),
        is_running=False,
    )


def test_result_enrichment_uses_task_scope(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db_path = tmp_path / "data" / "app.sqlite3"
    repository = SqliteTaskRepository(
        db_path=str(db_path),
        legacy_config_file=None,
    )
    asyncio.run(repository.save(_task_with_scope()))

    items = [
        {
            "商品ID": "A",
            "商品标题": "MacBook Pro M4 Pro 24G+512G",
            "当前售价": "¥10000",
            "商品链接": "https://www.goofish.com/item?id=A",
        },
        {
            "商品ID": "B",
            "商品标题": "MacBook Pro M4 Pro 24G+512G",
            "当前售价": "¥11000",
            "商品链接": "https://www.goofish.com/item?id=B",
        },
        {
            "商品ID": "C",
            "商品标题": "MacBook Pro M4 Pro 48G+1TB",
            "当前售价": "¥18000",
            "商品链接": "https://www.goofish.com/item?id=C",
        },
        {
            "商品ID": "D",
            "商品标题": "MacBook Pro M4 16G+512G",
            "当前售价": "¥8000",
            "商品链接": "https://www.goofish.com/item?id=D",
        },
    ]
    record_market_snapshots(
        keyword="MacBook Pro M4 Pro",
        task_name="m4pro",
        items=items,
        run_id="run-scope-result",
        snapshot_time="2026-11-01T12:00:00",
    )

    record = {
        "商品信息": {
            "商品ID": "A",
            "商品标题": "MacBook Pro M4 Pro 24G+512G",
            "当前售价": "¥10500",
        },
        "ai_analysis": {"is_recommended": True},
    }
    enriched = enrich_records_with_price_insight(
        [record],
        "MacBook_Pro_M4_Pro_full_data.jsonl",
    )

    insight = enriched[0]["price_insight"]
    assert insight["参考口径"]["mode"] == "config"
    assert insight["参考口径"]["bucket"] == {
        "chip": "m4pro",
        "memory_gb": 24,
        "storage_gb": 512,
    }
    assert insight["market_median_price"] == 10500.0
    assert insight["deal_score"] is not None
