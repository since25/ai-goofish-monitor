from src.services.price_history_service import (
    build_item_price_context,
    build_price_history_insights,
    load_price_snapshots,
    record_market_snapshots,
)


def test_record_market_snapshots_and_build_price_history_insights(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    seen_item_ids = set()

    run1_items = [
        {
            "商品ID": "1001",
            "商品标题": "Sony A7M4 单机",
            "当前售价": "¥10000",
            "商品标签": ["验货宝"],
            "发货地区": "上海",
            "卖家昵称": "卖家A",
            "商品链接": "https://www.goofish.com/item?id=1001",
            "发布时间": "2026-01-01 09:00",
        },
        {
            "商品ID": "1002",
            "商品标题": "Sony A7M4 套机",
            "当前售价": "¥12000",
            "商品标签": ["包邮"],
            "发货地区": "杭州",
            "卖家昵称": "卖家B",
            "商品链接": "https://www.goofish.com/item?id=1002",
            "发布时间": "2026-01-01 10:00",
        },
    ]
    run2_items = [
        {
            "商品ID": "1001",
            "商品标题": "Sony A7M4 单机",
            "当前售价": "¥9500",
            "商品标签": ["验货宝"],
            "发货地区": "上海",
            "卖家昵称": "卖家A",
            "商品链接": "https://www.goofish.com/item?id=1001",
            "发布时间": "2026-01-02 09:00",
        },
        {
            "商品ID": "1003",
            "商品标题": "Sony A7M4 全套",
            "当前售价": "¥13000",
            "商品标签": ["同城"],
            "发货地区": "南京",
            "卖家昵称": "卖家C",
            "商品链接": "https://www.goofish.com/item?id=1003",
            "发布时间": "2026-01-02 11:00",
        },
    ]

    inserted_run1 = record_market_snapshots(
        keyword="sony a7m4",
        task_name="Sony A7M4 监控",
        items=run1_items,
        run_id="run-1",
        snapshot_time="2026-01-01T12:00:00",
        seen_item_ids=seen_item_ids,
    )
    assert len(inserted_run1) == 2

    inserted_run2 = record_market_snapshots(
        keyword="sony a7m4",
        task_name="Sony A7M4 监控",
        items=run2_items,
        run_id="run-2",
        snapshot_time="2026-01-02T12:00:00",
        seen_item_ids=set(),
    )
    assert len(inserted_run2) == 2

    snapshots = load_price_snapshots("sony a7m4")
    assert len(snapshots) == 4

    insights = build_price_history_insights("sony a7m4")
    assert insights["market_summary"]["sample_count"] == 2
    assert insights["market_summary"]["avg_price"] == 11250.0
    assert insights["market_summary"]["min_price"] == 9500.0
    assert insights["history_summary"]["unique_items"] == 3
    assert len(insights["daily_trend"]) == 2
    assert insights["daily_trend"][0]["day"] == "2026-01-01"
    assert insights["daily_trend"][1]["day"] == "2026-01-02"

    item_context = build_item_price_context(
        snapshots,
        item_id="1001",
        current_price=9500.0,
    )
    assert item_context["observation_count"] == 2
    assert item_context["min_price"] == 9500.0
    assert item_context["max_price"] == 10000.0
    assert item_context["price_change_amount"] == -500.0
    assert item_context["deal_label"] == "高性价比"


def _scoped_snapshot(item_id: str, title: str, price: float, snapshot_time: str = "2026-11-01T12:00:00"):
    return {
        "item_id": item_id,
        "title": title,
        "price": price,
        "snapshot_time": snapshot_time,
        "run_id": "run-scope",
    }


def _scoped_scope(**overrides):
    from src.domain.models.task import PriceScope

    payload = {
        "mode": "config",
        "match": {"chip": "m4pro", "memory_gb": [24, 48]},
        "bucket_by": ["chip", "memory_gb", "storage_gb"],
        "window_days": 30,
        "min_samples": 2,
        "fallback": ["drop_storage"],
    }
    payload.update(overrides)
    return PriceScope(**payload)


def _current_m4pro_item(price: str = "10500"):
    return {
        "商品ID": "A",
        "商品标题": "MacBook Pro M4 Pro 24G+512G",
        "当前售价": price,
    }


def test_scoped_market_reference_buckets_by_configuration():
    from src.services.price_history_service import build_market_reference

    snapshots = [
        _scoped_snapshot("A", "MacBook Pro M4 Pro 24G+512G", 10000),
        _scoped_snapshot("B", "MacBook Pro M4 Pro 24G+512G", 11000),
        _scoped_snapshot("C", "MacBook Pro M4 Pro 24G+1TB", 13000),
        _scoped_snapshot("D", "MacBook Pro M4 Pro 48G+1TB", 17000),
        _scoped_snapshot("E", "MacBook Pro M4 Pro 16G+512G", 8000),
        _scoped_snapshot("F", "MacBook Pro M4 24G+512G", 8500),
    ]

    reference = build_market_reference(
        keyword="MacBook Pro M4 Pro",
        item=_current_m4pro_item(),
        current_market_items=[],
        historical_snapshots=snapshots,
        scope=_scoped_scope(),
    )

    assert reference["参考口径"]["fallback_level"] == "exact"
    assert reference["参考口径"]["bucket"] == {
        "chip": "m4pro",
        "memory_gb": 24,
        "storage_gb": 512,
    }
    assert reference["参考口径"]["sample_count"] == 2
    assert reference["参考口径"]["excluded"]["mismatch:memory_gb"] == 1
    assert reference["参考口径"]["excluded"]["mismatch:chip"] == 1
    assert reference["同配置参考"]["sample_count"] == 2
    assert reference["同配置参考"]["median_price"] == 10500.0
    assert reference["本商品价格位置"]["market_median_price"] == 10500.0
    assert reference["本商品价格位置"]["deal_score"] is not None


def test_scoped_market_reference_falls_back_when_storage_bucket_is_thin():
    from src.services.price_history_service import build_market_reference

    snapshots = [
        _scoped_snapshot("A", "MacBook Pro M4 Pro 24G+512G", 10000),
        _scoped_snapshot("B", "MacBook Pro M4 Pro 24G+1TB", 13000),
        _scoped_snapshot("C", "MacBook Pro M4 Pro 24G+1TB", 13500),
    ]

    reference = build_market_reference(
        keyword="MacBook Pro M4 Pro",
        item=_current_m4pro_item(),
        current_market_items=[],
        historical_snapshots=snapshots,
        scope=_scoped_scope(),
    )

    assert reference["参考口径"]["fallback_level"] == "drop_storage"
    assert reference["参考口径"]["bucket"] == {"chip": "m4pro", "memory_gb": 24}
    assert reference["同配置参考"]["sample_count"] == 3


def test_scoped_market_reference_marks_insufficient_without_fallback():
    from src.services.price_history_service import build_market_reference

    snapshots = [
        _scoped_snapshot("A", "MacBook Pro M4 Pro 24G+512G", 10000),
        _scoped_snapshot("B", "MacBook Pro M4 Pro 24G+1TB", 13000),
    ]

    reference = build_market_reference(
        keyword="MacBook Pro M4 Pro",
        item=_current_m4pro_item(),
        current_market_items=[],
        historical_snapshots=snapshots,
        scope=_scoped_scope(fallback=[]),
    )

    assert reference["参考口径"]["fallback_level"] == "insufficient"
    assert reference["同配置参考"]["sample_count"] == 1
    assert reference["本商品价格位置"]["deal_score"] is None
    assert reference["本商品价格位置"]["deal_label"] == "样本不足"


def test_scoped_market_reference_handles_out_of_scope_current_item():
    from src.services.price_history_service import build_market_reference

    snapshots = [
        _scoped_snapshot("A", "MacBook Pro M4 Pro 24G+512G", 12000),
        _scoped_snapshot("B", "MacBook Pro M4 Pro 48G+1TB", 17000),
    ]

    reference = build_market_reference(
        keyword="MacBook Pro M4 Pro",
        item={
            "商品ID": "X",
            "商品标题": "MacBook Pro M4 Pro 16G+512G",
            "当前售价": "8500",
        },
        current_market_items=[],
        historical_snapshots=snapshots,
        scope=_scoped_scope(min_samples=1),
    )

    assert reference["参考口径"]["current_in_scope"] is False
    assert reference["参考口径"]["fallback_level"] == "insufficient"
    assert reference["本商品价格位置"]["deal_score"] is None


def test_keyword_scope_keeps_legacy_shape():
    from src.services.price_history_service import build_market_reference

    reference = build_market_reference(
        keyword="MacBook Pro M4 Pro",
        item=_current_m4pro_item(),
        current_market_items=[{"当前售价": "10000"}],
        historical_snapshots=[
            _scoped_snapshot("A", "MacBook Pro M4 Pro 24G+512G", 10000),
        ],
    )

    assert "参考口径" not in reference
    assert "同配置参考" not in reference
    assert set(reference) == {
        "当前搜索样本",
        "历史价格概览",
        "本商品价格位置",
        "关键词",
    }


def test_scoped_market_reference_applies_window():
    from src.services.price_history_service import build_market_reference

    snapshots = [
        _scoped_snapshot("A", "MacBook Pro M4 Pro 24G+512G", 10000),
        _scoped_snapshot("OLD", "MacBook Pro M4 Pro 24G+512G", 9000, "2026-01-01T12:00:00"),
    ]

    reference = build_market_reference(
        keyword="MacBook Pro M4 Pro",
        item=_current_m4pro_item(),
        current_market_items=[],
        historical_snapshots=snapshots,
        scope=_scoped_scope(min_samples=1, window_days=30),
    )

    assert reference["参考口径"]["sample_count"] == 1
    assert reference["参考口径"]["pool"]["out_of_window"] == 1


def test_scoped_market_reference_accepts_dict_scope():
    from src.services.price_history_service import build_market_reference

    reference = build_market_reference(
        keyword="MacBook Pro M4 Pro",
        item=_current_m4pro_item(),
        current_market_items=[],
        historical_snapshots=[
            _scoped_snapshot("A", "MacBook Pro M4 Pro 24G+512G", 10000),
            _scoped_snapshot("B", "MacBook Pro M4 Pro 24G+512G", 11000),
        ],
        scope={
            "mode": "config",
            "match": {"chip": "m4pro", "memory_gb": [24, 48]},
            "bucket_by": ["chip", "memory_gb", "storage_gb"],
            "min_samples": 2,
        },
    )

    assert reference["参考口径"]["mode"] == "config"
    assert reference["同配置参考"]["sample_count"] == 2


def test_record_market_snapshots_persists_spec(tmp_path, monkeypatch):
    from src.services.price_history_service import (
        load_price_snapshots,
        record_market_snapshots,
        update_price_snapshot_spec,
    )

    monkeypatch.chdir(tmp_path)
    items = [
        {
            "商品ID": "m4-1",
            "商品标题": "MacBook Pro M4 Pro 24G+512G 国行",
            "当前售价": "¥12000",
            "商品链接": "https://www.goofish.com/item?id=m4-1",
        }
    ]
    record_market_snapshots(
        keyword="MacBook Pro M4 Pro",
        task_name="m4pro",
        items=items,
        run_id="run-spec",
        snapshot_time="2026-11-01T12:00:00",
    )

    snapshots = load_price_snapshots("MacBook Pro M4 Pro")
    assert snapshots[0]["spec"]["chip"] == "m4pro"
    assert snapshots[0]["spec"]["memory_gb"] == 24
    assert snapshots[0]["spec"]["storage_gb"] == 512
    assert snapshots[0]["spec_source"] == "title"
    assert snapshots[0]["chip"] == "m4pro"
    assert snapshots[0]["memory_gb"] == 24
    assert snapshots[0]["storage_gb"] == 512

    updated = update_price_snapshot_spec(
        keyword="MacBook Pro M4 Pro",
        item_id="m4-1",
        spec={"chip": "m4pro", "memory_gb": 48, "storage_gb": 1024},
        spec_source="ai",
    )
    assert updated == 1
    snapshots = load_price_snapshots("MacBook Pro M4 Pro")
    assert snapshots[0]["spec"]["memory_gb"] == 48
    assert snapshots[0]["spec_source"] == "ai"


def test_record_market_snapshots_prefers_cached_ai_spec(tmp_path, monkeypatch):
    from src.services.price_history_service import load_price_snapshots, record_market_snapshots

    monkeypatch.chdir(tmp_path)
    items = [
        {
            "商品ID": "m4-2",
            "商品标题": "MacBook Pro M4 Pro 24G+512G",
            "当前售价": "¥12000",
            "商品链接": "https://www.goofish.com/item?id=m4-2",
        }
    ]
    spec_cache = {
        "m4-2": {"chip": "m4pro", "memory_gb": 48, "storage_gb": 1024}
    }
    record_market_snapshots(
        keyword="MacBook Pro M4 Pro",
        task_name="m4pro",
        items=items,
        run_id="run-spec-ai",
        snapshot_time="2026-11-01T12:00:00",
        spec_cache=spec_cache,
    )

    snapshot = load_price_snapshots("MacBook Pro M4 Pro")[0]
    assert snapshot["spec"]["memory_gb"] == 48
    assert snapshot["spec"]["storage_gb"] == 1024
    assert snapshot["spec_source"] == "ai"


def test_price_history_insights_respects_scope(tmp_path, monkeypatch):
    from src.domain.models.task import PriceScope
    from src.services.price_history_service import (
        build_price_history_insights,
        record_market_snapshots,
    )

    monkeypatch.chdir(tmp_path)
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
            "商品标题": "MacBook Pro M4 16G+512G",
            "当前售价": "¥8000",
            "商品链接": "https://www.goofish.com/item?id=C",
        },
        {
            "商品ID": "D",
            "商品标题": "MacBook Pro M4 Pro 48G+1TB",
            "当前售价": "¥18000",
            "商品链接": "https://www.goofish.com/item?id=D",
        },
    ]
    record_market_snapshots(
        keyword="MacBook Pro M4 Pro",
        task_name="m4pro",
        items=items,
        run_id="run-insights",
        snapshot_time="2026-11-01T12:00:00",
    )

    insights = build_price_history_insights(
        "MacBook Pro M4 Pro",
        scope=PriceScope(
            mode="config",
            match={"chip": "m4pro", "memory_gb": [24, 48]},
            bucket_by=["chip", "memory_gb", "storage_gb"],
        ),
    )

    assert insights["market_summary"]["sample_count"] == 3
    assert insights["history_summary"]["unique_items"] == 3
    assert insights["参考口径"]["mode"] == "config"
    assert insights["参考口径"]["excluded"]["mismatch:chip"] == 1
