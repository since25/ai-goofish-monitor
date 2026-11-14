from src.domain.models.task import PriceScope, TaskGenerateRequest
from src.services.price_scope_inference import infer_price_scope
from src.services.task_generation_runner import build_task_create


def test_infer_price_scope_from_chip_and_memory_range():
    scope = infer_price_scope(
        "MacBook Pro M4 Pro",
        "只看 M4 Pro 芯片，内存 24-48G，电池健康 90% 以上。",
    )
    assert scope is not None
    assert scope.mode == "config"
    assert scope.match == {"chip": "m4pro", "memory_gb": [24, 48]}
    assert scope.bucket_by == ["chip", "memory_gb", "storage_gb"]


def test_infer_price_scope_from_memory_list():
    scope = infer_price_scope(
        "MacBook Pro M3 Pro",
        "内存必须为 24G/32G/36G/48G，其他配置不要。",
    )
    assert scope is not None
    assert scope.match["memory_gb"] == [24, 48]


def test_infer_price_scope_requires_chip_and_memory():
    assert infer_price_scope("Sony A7M4", "机身成色好，预算 8000-12000。") is None
    assert infer_price_scope("MacBook Pro M4 Pro", "只看成色，不限内存。") is None


def test_build_task_create_prefers_explicit_scope():
    req = TaskGenerateRequest(
        task_name="m4pro",
        keyword="MacBook Pro M4 Pro",
        description="内存 24-48G",
        price_scope=PriceScope(mode="keyword"),
    )
    task = build_task_create(req, "prompts/m4pro_criteria.txt")
    assert task.price_scope.mode == "keyword"


def test_build_task_create_infers_scope_when_omitted():
    req = TaskGenerateRequest(
        task_name="m4pro",
        keyword="MacBook Pro M4 Pro",
        description="内存 24-48G",
    )
    task = build_task_create(req, "prompts/m4pro_criteria.txt")
    assert task.price_scope.mode == "config"
    assert task.price_scope.match == {"chip": "m4pro", "memory_gb": [24, 48]}


def test_infer_price_scope_with_ai_parses_structured_json(monkeypatch):
    import asyncio

    import src.services.price_scope_inference as inference

    class FakeAIClient:
        def is_available(self):
            return True

        async def _call_ai(self, *_args, **_kwargs):
            return (
                '{"mode":"config","match":{"chip":"M4 Pro","memory_gb":[24,48]},'
                '"bucket_by":["chip","memory_gb","storage_gb"],"window_days":30,'
                '"min_samples":5,"fallback":["drop_storage"]}'
            )

        async def close(self):
            return None

    monkeypatch.setattr(inference, "AIClient", FakeAIClient)
    scope = asyncio.run(
        inference.infer_price_scope_with_ai("MacBook Pro M4 Pro", "内存 24-48G")
    )
    assert scope is not None
    assert scope.mode == "config"
    assert scope.match == {"chip": "m4pro", "memory_gb": [24, 48]}


def test_infer_price_scope_with_ai_returns_none_for_keyword(monkeypatch):
    import asyncio

    import src.services.price_scope_inference as inference

    class FakeAIClient:
        def is_available(self):
            return True

        async def _call_ai(self, *_args, **_kwargs):
            return '{"mode":"keyword"}'

        async def close(self):
            return None

    monkeypatch.setattr(inference, "AIClient", FakeAIClient)
    assert asyncio.run(inference.infer_price_scope_with_ai("Sony A7M4", "看成色")) is None
