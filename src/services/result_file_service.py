"""
结果记录富化与文件名校验服务
"""

from src.infrastructure.persistence.storage_names import normalize_keyword_from_filename
from src.services.price_history_service import (
    build_item_price_context,
    build_market_reference,
    load_price_scope_for_keyword,
    load_price_snapshots,
    parse_price_value,
)
from src.services.result_storage_service import load_visible_result_item_ids
from src.services.spec_utils import load_item_spec_cache, make_spec_resolver


def validate_result_filename(filename: str) -> None:
    if not filename.endswith(".jsonl") or "/" in filename or ".." in filename:
        raise ValueError("无效的文件名")


def enrich_records_with_price_insight(records: list[dict], filename: str) -> list[dict]:
    keyword = normalize_keyword_from_filename(filename)
    snapshots = load_price_snapshots(keyword)
    if not snapshots:
        return records

    visible_item_ids = load_visible_result_item_ids(filename)
    visible_snapshots = [
        snapshot
        for snapshot in snapshots
        if str(snapshot.get("item_id") or "") in visible_item_ids
    ]
    scope = load_price_scope_for_keyword(keyword)
    spec_resolver = (
        make_spec_resolver(load_item_spec_cache()) if scope is not None else None
    )

    enriched = []
    for record in records:
        info = record.get("商品信息", {}) or {}
        clone = dict(record)
        existing_insight = record.get("price_insight") or {}

        if scope is not None:
            reference = build_market_reference(
                keyword=keyword,
                item=info,
                current_market_items=[],
                historical_snapshots=snapshots,
                scope=scope,
                spec_resolver=spec_resolver,
            )
            clone["price_insight"] = reference.get("本商品价格位置") or {}
        elif existing_insight.get("参考口径"):
            # 任务后来关闭了口径时，保留分析时已写入的同配置结果，避免回退到混合均价。
            enriched.append(clone)
            continue
        else:
            clone["price_insight"] = build_item_price_context(
                snapshots,
                item_id=str(info.get("商品ID") or ""),
                current_price=parse_price_value(info.get("当前售价")),
                market_snapshots=visible_snapshots,
            )
        enriched.append(clone)
    return enriched
