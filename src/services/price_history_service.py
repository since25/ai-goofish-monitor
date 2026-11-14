"""
价格历史记录与聚合服务
"""
from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from datetime import datetime, timedelta
from statistics import median
from typing import Any, Iterable, Optional

from src.domain.models.task import PriceScope
from src.infrastructure.persistence.sqlite_bootstrap import bootstrap_sqlite_storage
from src.infrastructure.persistence.sqlite_connection import sqlite_connection
from src.services.spec_utils import (
    load_item_spec_cache,
    make_spec_resolver,
    normalize_spec,
    normalize_spec_value,
    parse_spec_from_title,
    resolve_item_spec,
    resolve_item_spec_with_source,
    spec_has_values,
)

PRICE_HISTORY_DIR = "price_history"
DEFAULT_HISTORY_WINDOW_DAYS = 30


def normalize_keyword_slug(keyword: str) -> str:
    text = "".join(
        char for char in str(keyword or "").lower().replace(" ", "_")
        if char.isalnum() or char in "_-"
    ).rstrip("_")
    return text or "unknown"


def build_price_history_path(keyword: str) -> str:
    return os.path.join(
        PRICE_HISTORY_DIR,
        f"{normalize_keyword_slug(keyword)}_history.jsonl",
    )


def parse_price_value(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 2)

    text = str(value).strip().replace("¥", "").replace(",", "")
    if not text or text in {"价格异常", "暂无", "-", "N/A"}:
        return None
    if text.endswith("万"):
        text = str(float(text[:-1]) * 10000)
    try:
        return round(float(text), 2)
    except (TypeError, ValueError):
        return None


def _safe_iso_datetime(value: Optional[str]) -> str:
    if value:
        return value
    return datetime.now().isoformat()


def _to_day(iso_text: str) -> str:
    return iso_text[:10]


def _build_snapshot_record(
    *,
    keyword: str,
    task_name: str,
    item: dict,
    run_id: str,
    snapshot_time: str,
) -> Optional[dict]:
    item_id = str(item.get("商品ID") or "").strip()
    link = str(item.get("商品链接") or "").strip()
    unique_id = item_id or link
    price_value = parse_price_value(item.get("当前售价"))
    if not unique_id or price_value is None:
        return None

    return {
        "snapshot_time": snapshot_time,
        "snapshot_day": _to_day(snapshot_time),
        "run_id": run_id,
        "task_name": task_name,
        "keyword": keyword,
        "item_id": unique_id,
        "title": item.get("商品标题") or "",
        "price": price_value,
        "price_display": item.get("当前售价") or "",
        "tags": item.get("商品标签") or [],
        "region": item.get("发货地区") or "",
        "seller": item.get("卖家昵称") or "",
        "publish_time": item.get("发布时间") or "",
        "link": link,
        "spec": {},
        "spec_source": "unknown",
    }


def record_market_snapshots(
    *,
    keyword: str,
    task_name: str,
    items: Iterable[dict],
    run_id: str,
    snapshot_time: Optional[str] = None,
    seen_item_ids: Optional[set[str]] = None,
    spec_cache: Optional[dict[str, dict]] = None,
    spec_resolver=None,
) -> list[dict]:
    snapshot_time = _safe_iso_datetime(snapshot_time)
    seen = seen_item_ids if seen_item_ids is not None else set()
    records: list[dict] = []

    for item in items:
        record = _build_snapshot_record(
            keyword=keyword,
            task_name=task_name,
            item=item,
            run_id=run_id,
            snapshot_time=snapshot_time,
        )
        if record is None or record["item_id"] in seen:
            continue
        spec_text = f"{record['title']} {item.get('商品描述') or ''}".strip()
        if spec_cache is not None:
            spec, spec_source = resolve_item_spec_with_source(
                record["item_id"], spec_text, spec_cache
            )
        elif spec_resolver is not None:
            spec = spec_resolver(record["item_id"], spec_text) or {}
            spec_source = "ai" if spec_has_values(spec) else "unknown"
        else:
            spec, spec_source = resolve_item_spec_with_source(
                record["item_id"], spec_text
            )
        record["spec"] = spec
        record["spec_source"] = spec_source
        seen.add(record["item_id"])
        records.append(record)

    if not records:
        return []

    bootstrap_sqlite_storage()
    keyword_slug = normalize_keyword_slug(keyword)
    with sqlite_connection() as conn:
        for record in records:
            conn.execute(
                """
                INSERT OR IGNORE INTO price_snapshots (
                    keyword_slug, keyword, task_name, snapshot_time, snapshot_day,
                    run_id, item_id, title, price, price_display, tags_json, region,
                    seller, publish_time, link, spec_json, spec_source,
                    chip, memory_gb, storage_gb, screen_inch
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    keyword_slug,
                    record.get("keyword", keyword),
                    record.get("task_name", task_name),
                    record.get("snapshot_time", snapshot_time),
                    record.get("snapshot_day", _to_day(snapshot_time)),
                    record.get("run_id", run_id),
                    record.get("item_id", ""),
                    record.get("title", ""),
                    record.get("price"),
                    record.get("price_display", ""),
                    json.dumps(record.get("tags") or [], ensure_ascii=False),
                    record.get("region", ""),
                    record.get("seller", ""),
                    record.get("publish_time", ""),
                    record.get("link", ""),
                    json.dumps(record.get("spec") or {}, ensure_ascii=False),
                    record.get("spec_source", "unknown"),
                    (record.get("spec") or {}).get("chip"),
                    (record.get("spec") or {}).get("memory_gb"),
                    (record.get("spec") or {}).get("storage_gb"),
                    (record.get("spec") or {}).get("screen_inch"),
                ),
            )
        conn.commit()
    return records


def load_price_snapshots(keyword: str) -> list[dict]:
    bootstrap_sqlite_storage()
    with sqlite_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM price_snapshots
            WHERE keyword_slug = ?
            ORDER BY snapshot_time ASC, id ASC
            """,
            (normalize_keyword_slug(keyword),),
        ).fetchall()
    snapshots: list[dict] = []
    for row in rows:
        snapshots.append(
            {
                "snapshot_time": row["snapshot_time"],
                "snapshot_day": row["snapshot_day"],
                "run_id": row["run_id"],
                "task_name": row["task_name"],
                "keyword": row["keyword"],
                "item_id": row["item_id"],
                "title": row["title"],
                "price": row["price"],
                "price_display": row["price_display"],
                "tags": json.loads(row["tags_json"] or "[]"),
                "region": row["region"],
                "seller": row["seller"],
                "publish_time": row["publish_time"],
                "link": row["link"],
                "spec": _parse_spec_json(row["spec_json"]),
                "spec_source": row["spec_source"] or "unknown",
                "chip": row["chip"],
                "memory_gb": row["memory_gb"],
                "storage_gb": row["storage_gb"],
                "screen_inch": row["screen_inch"],
            }
        )
    return snapshots


def _merge_scope_spec(base_spec: Optional[dict], resolved: Optional[dict]) -> dict:
    merged = dict(base_spec or {})
    for key, value in (resolved or {}).items():
        if merged.get(key) is None:
            merged[key] = value
    return merged


def _parse_spec_json(value: Any) -> dict:
    try:
        spec = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return spec if isinstance(spec, dict) else {}


def delete_price_snapshots(keyword: str) -> int:
    bootstrap_sqlite_storage()
    with sqlite_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM price_snapshots WHERE keyword_slug = ?",
            (normalize_keyword_slug(keyword),),
        )
        conn.commit()
    return int(cursor.rowcount or 0)


def update_price_snapshot_spec(
    *,
    keyword: str,
    item_id: str,
    spec: dict,
    spec_source: str = "ai",
) -> int:
    """AI 分析完成后回填快照 spec，供后续价格口径直接使用。"""
    normalized_spec = normalize_spec(spec or {})
    if not keyword or not item_id or not spec_has_values(normalized_spec):
        return 0
    bootstrap_sqlite_storage()
    with sqlite_connection() as conn:
        cursor = conn.execute(
            "UPDATE price_snapshots SET spec_json = ?, spec_source = ?, "
            "chip = ?, memory_gb = ?, storage_gb = ?, screen_inch = ? "
            "WHERE keyword_slug = ? AND item_id = ?",
            (
                json.dumps(normalized_spec, ensure_ascii=False),
                spec_source,
                normalized_spec.get("chip"),
                normalized_spec.get("memory_gb"),
                normalized_spec.get("storage_gb"),
                normalized_spec.get("screen_inch"),
                normalize_keyword_slug(keyword),
                str(item_id),
            ),
        )
        conn.commit()
    return int(cursor.rowcount or 0)


def load_price_scope_for_keyword(keyword: str) -> Optional[PriceScope]:
    """读取任务级价格口径；未配置或已关闭时返回 None。"""
    if not keyword:
        return None
    target_slug = normalize_keyword_slug(keyword)
    bootstrap_sqlite_storage()
    with sqlite_connection() as conn:
        rows = conn.execute(
            "SELECT keyword, price_scope_json FROM tasks ORDER BY id ASC"
        ).fetchall()
    for row in rows:
        if normalize_keyword_slug(row["keyword"]) != target_slug:
            continue
        try:
            scope = PriceScope.model_validate_json(row["price_scope_json"] or "{}")
        except Exception:
            return None
        return scope if scope.is_active() else None
    return None


def _dedupe_latest(records: Iterable[dict], group_key: str) -> list[dict]:
    latest_by_key: dict[str, dict] = {}
    for record in records:
        key = str(record.get(group_key) or "").strip()
        if not key:
            continue
        latest_by_key[key] = record
    return list(latest_by_key.values())


def _summarize_prices(records: Iterable[dict]) -> dict:
    entries = [record for record in records if parse_price_value(record.get("price")) is not None]
    prices = [float(record["price"]) for record in entries]
    if not prices:
        return {
            "sample_count": 0,
            "avg_price": None,
            "median_price": None,
            "min_price": None,
            "max_price": None,
        }

    return {
        "sample_count": len(prices),
        "avg_price": round(sum(prices) / len(prices), 2),
        "median_price": round(float(median(prices)), 2),
        "min_price": round(min(prices), 2),
        "max_price": round(max(prices), 2),
    }


def _build_daily_trend(snapshots: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for snapshot in snapshots:
        grouped[str(snapshot.get("snapshot_day") or "")].append(snapshot)

    points: list[dict] = []
    for day in sorted(grouped.keys()):
        day_records = _dedupe_latest(grouped[day], "item_id")
        summary = _summarize_prices(day_records)
        summary["day"] = day
        points.append(summary)
    return points


def _recent_window_snapshots(snapshots: list[dict], window_days: int) -> list[dict]:
    if not snapshots:
        return []
    latest_time = max(str(record.get("snapshot_time") or "") for record in snapshots)
    latest_dt = datetime.fromisoformat(latest_time)
    filtered = []
    for record in snapshots:
        current_time = datetime.fromisoformat(str(record.get("snapshot_time") or latest_time))
        if (latest_dt - current_time).days <= max(0, window_days):
            filtered.append(record)
    return filtered


def _resolve_deal_label(score: int) -> str:
    if score >= 65:
        return "高性价比"
    if score >= 50:
        return "值得关注"
    if score >= 40:
        return "价格正常"
    return "价格偏高"


def build_item_price_context(
    snapshots: list[dict],
    *,
    item_id: str,
    current_price: Optional[float],
    market_snapshots: Optional[list[dict]] = None,
    market_summary: Optional[dict] = None,
    market_min_samples: int = 1,
) -> dict:
    if not item_id:
        return {"observation_count": 0, "deal_score": None, "deal_label": "暂无数据"}

    item_snapshots = [record for record in snapshots if str(record.get("item_id")) == str(item_id)]
    if not item_snapshots:
        return {"observation_count": 0, "deal_score": None, "deal_label": "暂无数据"}

    latest_item_snapshot = item_snapshots[-1]
    price_now = current_price if current_price is not None else parse_price_value(latest_item_snapshot.get("price"))
    historical_prices = [
        float(record["price"])
        for record in item_snapshots
        if parse_price_value(record.get("price")) is not None
    ]

    if market_summary is not None:
        summary = market_summary
        market_avg = summary.get("avg_price")
        market_median = summary.get("median_price")
        sample_count = int(summary.get("sample_count") or 0)
        benchmark = market_median if market_median is not None else market_avg
        has_market = benchmark is not None and sample_count >= max(1, market_min_samples)
    else:
        source_snapshots = market_snapshots if market_snapshots is not None else snapshots
        latest_run_id = str(source_snapshots[-1].get("run_id") or "") if source_snapshots else ""
        latest_market = _dedupe_latest(
            [record for record in source_snapshots if str(record.get("run_id") or "") == latest_run_id],
            "item_id",
        )
        summary = _summarize_prices(latest_market)
        market_avg = summary.get("avg_price")
        market_median = summary.get("median_price")
        benchmark = market_avg
        has_market = benchmark is not None

    score = None
    if has_market and price_now is not None:
        score = 50
        score += int(((benchmark - price_now) / benchmark) * 60)
        if historical_prices:
            historical_max = max(historical_prices)
            if historical_max > 0:
                score += int(((historical_max - price_now) / historical_max) * 20)
            if math.isclose(price_now, min(historical_prices), rel_tol=0.001):
                score += 8
        score = max(0, min(100, score))

    previous_price = historical_prices[-2] if len(historical_prices) >= 2 else None
    change_amount = None if previous_price is None or price_now is None else round(price_now - previous_price, 2)
    change_percent = None
    if change_amount is not None and previous_price:
        change_percent = round(change_amount / previous_price * 100, 2)

    return {
        "observation_count": len(historical_prices),
        "current_price": price_now,
        "avg_price": round(sum(historical_prices) / len(historical_prices), 2) if historical_prices else None,
        "median_price": round(float(median(historical_prices)), 2) if historical_prices else None,
        "min_price": round(min(historical_prices), 2) if historical_prices else None,
        "max_price": round(max(historical_prices), 2) if historical_prices else None,
        "first_seen_at": item_snapshots[0].get("snapshot_time"),
        "last_seen_at": latest_item_snapshot.get("snapshot_time"),
        "market_avg_price": market_avg,
        "market_median_price": market_median,
        "price_change_amount": change_amount,
        "price_change_percent": change_percent,
        "deal_score": score,
        "deal_label": _resolve_deal_label(score) if score is not None else "样本不足",
    }


def _coerce_price_scope(scope: Optional[PriceScope | dict]) -> Optional[PriceScope]:
    if scope is None:
        return None
    if isinstance(scope, PriceScope):
        return scope
    return PriceScope.model_validate(scope)


def _parse_iso_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _build_scope_sample_pool(
    historical_snapshots: list[dict],
    current_market_items: list[dict],
    window_days: int,
) -> tuple[list[dict], dict]:
    records: dict[str, dict] = {}
    now_iso = datetime.now().isoformat()

    def put(record: dict) -> None:
        item_id = record.get("item_id")
        if not item_id:
            return
        existing = records.get(item_id)
        if existing is None:
            records[item_id] = record
            return
        existing_time = _parse_iso_datetime(existing.get("snapshot_time"))
        record_time = _parse_iso_datetime(record.get("snapshot_time"))
        if existing_time is not None and record_time is not None and existing_time > record_time:
            return
        records[item_id] = record

    for snapshot in historical_snapshots or []:
        item_id = str(snapshot.get("item_id") or "").strip()
        price = parse_price_value(snapshot.get("price"))
        if not item_id or price is None:
            continue
        put(
            {
                "item_id": item_id,
                "title": str(snapshot.get("title") or ""),
                "price": price,
                "snapshot_time": str(snapshot.get("snapshot_time") or ""),
                "spec": snapshot.get("spec") or {},
                "spec_source": snapshot.get("spec_source") or "unknown",
            }
        )

    for market_item in current_market_items or []:
        item_id = str(market_item.get("商品ID") or "").strip()
        price = parse_price_value(market_item.get("当前售价"))
        if not item_id or price is None:
            continue
        put(
            {
                "item_id": item_id,
                "title": str(market_item.get("商品标题") or ""),
                "price": price,
                "snapshot_time": now_iso,
                "spec": {},
                "spec_source": "unknown",
            }
        )

    if not records:
        return [], {"deduped": 0, "out_of_window": 0}

    times = [t for t in (_parse_iso_datetime(r.get("snapshot_time")) for r in records.values()) if t]
    anchor = max(times) if times else datetime.now()
    cutoff = anchor - timedelta(days=max(1, int(window_days or 1)))

    pool = []
    out_of_window = 0
    for record in records.values():
        moment = _parse_iso_datetime(record.get("snapshot_time"))
        if moment is not None and moment < cutoff:
            out_of_window += 1
            continue
        pool.append(record)
    pool.sort(key=lambda record: str(record.get("snapshot_time") or ""))
    return pool, {"deduped": len(records), "out_of_window": out_of_window}


def _match_value(key: str, actual: Any, expected: Any) -> bool:
    if expected is None:
        return True
    if isinstance(expected, (list, tuple)):
        if (
            len(expected) == 2
            and any(isinstance(part, (int, float)) for part in expected)
            and all(part is None or isinstance(part, (int, float)) for part in expected)
        ):
            number = _as_number(actual)
            if number is None:
                return False
            low, high = expected
            if low is not None and number < float(low):
                return False
            if high is not None and number > float(high):
                return False
            return True
        normalized = [normalize_spec_value(key, value) for value in expected]
        return normalize_spec_value(key, actual) in normalized

    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        number = _as_number(actual)
        return number is not None and number == float(expected)

    if isinstance(expected, str):
        actual_text = str(normalize_spec_value(key, actual) or "").lower()
        expected_text = str(normalize_spec_value(key, expected) or "").lower()
        return bool(actual_text and expected_text and expected_text in actual_text)

    return actual == expected


def _as_number(value: Any) -> Optional[float]:
    try:
        return float(str(value).replace("¥", "").replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def _matches_price_scope(spec: dict, match: dict) -> tuple[bool, Optional[str]]:
    for key, expected in (match or {}).items():
        actual = spec.get(key)
        if actual is None or actual == "":
            return False, f"unknown:{key}"
        if not _match_value(key, actual, expected):
            return False, f"mismatch:{key}"
    return True, None


def _scope_bucket_candidates(scope: PriceScope) -> list[list[str]]:
    if scope.mode != "config":
        return [[]]
    base = [key for key in scope.bucket_by if key]
    candidates = [base]
    for action in scope.fallback:
        current = candidates[-1]
        if action == "drop_storage" and "storage_gb" in current:
            candidates.append([key for key in current if key != "storage_gb"])
        elif action == "drop_memory" and "memory_gb" in current:
            candidates.append([key for key in current if key != "memory_gb"])
        elif action == "task":
            candidates.append([])
    deduped = []
    seen = set()
    for candidate in candidates:
        marker = tuple(candidate)
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(candidate)
    return deduped


def _bucket_level(scope: PriceScope, keys: list[str]) -> str:
    if not keys:
        return "task"
    if keys == [key for key in scope.bucket_by if key]:
        return "exact"
    base = set(scope.bucket_by)
    removed = base - set(keys)
    if removed == {"storage_gb"}:
        return "drop_storage"
    if removed == {"memory_gb"}:
        return "drop_memory"
    return "custom"


def _select_scoped_bucket(
    eligible: list[dict],
    current_spec: dict,
    scope: PriceScope,
) -> tuple[str, dict, dict]:
    empty_summary = _summarize_prices([])
    best_fallback: tuple[list[str], dict, dict] | None = None

    for keys in _scope_bucket_candidates(scope):
        if not keys:
            summary = _summarize_prices(eligible)
            level = "task"
            if summary["sample_count"] >= scope.min_samples:
                return level, {}, summary
            if best_fallback is None or summary["sample_count"] > best_fallback[2]["sample_count"]:
                best_fallback = (keys, {}, summary)
            continue

        if any(current_spec.get(key) is None for key in keys):
            continue
        bucket = {key: current_spec.get(key) for key in keys}
        subset = [
            record
            for record in eligible
            if all(
                normalize_spec_value(key, record.get("spec", {}).get(key))
                == normalize_spec_value(key, value)
                for key, value in bucket.items()
            )
        ]
        summary = _summarize_prices(subset)
        level = _bucket_level(scope, keys)
        if summary["sample_count"] >= scope.min_samples:
            return level, bucket, summary
        if best_fallback is None or summary["sample_count"] > best_fallback[2]["sample_count"]:
            best_fallback = (keys, bucket, summary)

    if best_fallback is not None:
        keys, bucket, summary = best_fallback
        return "insufficient", bucket, summary
    return "insufficient", {}, empty_summary


def _build_legacy_market_reference(
    *,
    keyword: str,
    item: dict,
    current_market_items: list[dict],
    historical_snapshots: list[dict],
) -> dict:
    current_market_records = []
    for market_item in current_market_items:
        price = parse_price_value(market_item.get("当前售价"))
        if price is None:
            continue
        current_market_records.append({"price": price})

    market_snapshot = _summarize_prices(current_market_records)
    history_summary = _summarize_prices(_dedupe_latest(historical_snapshots, "item_id"))
    item_context = build_item_price_context(
        historical_snapshots,
        item_id=str(item.get("商品ID") or ""),
        current_price=parse_price_value(item.get("当前售价")),
    )
    return {
        "当前搜索样本": market_snapshot,
        "历史价格概览": history_summary,
        "本商品价格位置": item_context,
        "关键词": keyword,
    }


def build_market_reference(
    *,
    keyword: str,
    item: dict,
    current_market_items: list[dict],
    historical_snapshots: list[dict],
    scope: Optional[PriceScope | dict] = None,
    spec_resolver=None,
) -> dict:
    coerced_scope = _coerce_price_scope(scope)
    if coerced_scope is None or not coerced_scope.is_active():
        return _build_legacy_market_reference(
            keyword=keyword,
            item=item,
            current_market_items=current_market_items,
            historical_snapshots=historical_snapshots,
        )

    current_id = str(item.get("商品ID") or "")
    current_title = str(item.get("商品标题") or "")
    current_description = str(item.get("商品描述") or "")
    current_text = f"{current_title} {current_description}".strip()
    current_price = parse_price_value(item.get("当前售价"))
    resolver = spec_resolver or (lambda item_id, title: resolve_item_spec(item_id, title))
    current_spec = resolver(current_id, current_text) or parse_spec_from_title(current_text)

    pool, pool_meta = _build_scope_sample_pool(
        historical_snapshots,
        current_market_items,
        coerced_scope.window_days,
    )
    for record in pool:
        base_spec = record.get("spec") or {}
        resolved = resolver(record["item_id"], record["title"]) or parse_spec_from_title(
            record["title"]
        )
        record["spec"] = _merge_scope_spec(base_spec, resolved)

    eligible = []
    excluded: dict[str, int] = {}
    for record in pool:
        matched, reason = _matches_price_scope(record["spec"], coerced_scope.match)
        if matched:
            eligible.append(record)
            continue
        key = reason or "mismatch"
        excluded[key] = excluded.get(key, 0) + 1

    current_in_scope, current_reason = _matches_price_scope(
        current_spec, coerced_scope.match
    )
    level, bucket, scoped_summary = _select_scoped_bucket(
        eligible, current_spec, coerced_scope
    )

    history_summary = _summarize_prices(eligible)
    current_market_records = [
        {"price": price}
        for price in (
            parse_price_value(market_item.get("当前售价"))
            for market_item in current_market_items
        )
        if price is not None
    ]
    market_snapshot = _summarize_prices(current_market_records)

    item_context = build_item_price_context(
        historical_snapshots,
        item_id=current_id,
        current_price=current_price,
        market_summary=scoped_summary,
        market_min_samples=coerced_scope.min_samples,
    )
    reference_context = {
        "mode": coerced_scope.mode,
        "match": coerced_scope.match,
        "bucket": bucket,
        "bucket_by": list(bucket.keys()),
        "sample_count": scoped_summary.get("sample_count", 0),
        "eligible_sample_count": len(eligible),
        "window_days": coerced_scope.window_days,
        "min_samples": coerced_scope.min_samples,
        "fallback_level": level,
        "excluded": excluded,
        "pool": pool_meta,
        "current_spec": current_spec,
        "current_in_scope": current_in_scope,
        "current_reason": current_reason,
    }
    item_context["参考口径"] = reference_context

    return {
        "当前搜索样本": market_snapshot,
        "历史价格概览": history_summary,
        "同配置参考": scoped_summary,
        "本商品价格位置": item_context,
        "参考口径": reference_context,
        "关键词": keyword,
    }


def _filter_snapshots_by_scope(
    records: list[dict],
    scope: PriceScope,
    resolver,
) -> tuple[list[dict], dict[str, int]]:
    filtered: list[dict] = []
    excluded: dict[str, int] = {}
    for record in records:
        base_spec = record.get("spec") or {}
        resolved = resolver(record.get("item_id"), record.get("title") or "") or {}
        merged = _merge_scope_spec(base_spec, resolved)
        matched, reason = _matches_price_scope(merged, scope.match)
        if matched:
            clone = dict(record)
            clone["spec"] = merged
            filtered.append(clone)
            continue
        key = reason or "mismatch"
        excluded[key] = excluded.get(key, 0) + 1
    return filtered, excluded


def build_price_history_insights(
    keyword: str,
    *,
    window_days: int = DEFAULT_HISTORY_WINDOW_DAYS,
    visible_item_ids: Optional[set[str]] = None,
    scope: Optional[PriceScope | dict] = None,
) -> dict:
    snapshots = load_price_snapshots(keyword)
    if visible_item_ids is not None:
        snapshots = [
            snapshot
            for snapshot in snapshots
            if str(snapshot.get("item_id") or "") in visible_item_ids
        ]

    effective_scope = (
        _coerce_price_scope(scope)
        if scope is not None
        else load_price_scope_for_keyword(keyword)
    )
    if effective_scope is not None and effective_scope.is_active():
        empty_reference = {
            "mode": effective_scope.mode,
            "match": effective_scope.match,
            "window_days": window_days,
            "sample_scope": "eligible",
        }
        if not snapshots:
            return {
                "market_summary": _summarize_prices([]),
                "history_summary": {"unique_items": 0, **_summarize_prices([])},
                "daily_trend": [],
                "latest_snapshot_at": None,
                "参考口径": empty_reference,
            }

        resolver = make_spec_resolver(load_item_spec_cache())
        recent_snapshots = _recent_window_snapshots(snapshots, window_days)
        eligible, excluded = _filter_snapshots_by_scope(
            recent_snapshots,
            effective_scope,
            resolver,
        )
        latest_run_id = (
            str(eligible[-1].get("run_id") or "") if eligible else ""
        )
        latest_run_snapshots = _dedupe_latest(
            [
                record
                for record in eligible
                if str(record.get("run_id") or "") == latest_run_id
            ],
            "item_id",
        )
        history_items = _dedupe_latest(eligible, "item_id")
        latest_snapshot_at = (
            eligible[-1].get("snapshot_time") if eligible else None
        )
        return {
            "market_summary": {
                **_summarize_prices(latest_run_snapshots),
                "snapshot_time": latest_snapshot_at,
            },
            "history_summary": {
                "unique_items": len(history_items),
                **_summarize_prices(history_items),
            },
            "daily_trend": _build_daily_trend(eligible),
            "latest_snapshot_at": latest_snapshot_at,
            "参考口径": {
                **empty_reference,
                "sample_count": len(history_items),
                "excluded": excluded,
            },
        }

    if not snapshots:
        return {
            "market_summary": _summarize_prices([]),
            "history_summary": {"unique_items": 0, **_summarize_prices([])},
            "daily_trend": [],
            "latest_snapshot_at": None,
        }

    recent_snapshots = _recent_window_snapshots(snapshots, window_days)
    latest_run_id = str(snapshots[-1].get("run_id") or "")
    latest_run_snapshots = _dedupe_latest(
        [record for record in snapshots if str(record.get("run_id") or "") == latest_run_id],
        "item_id",
    )
    latest_records_by_item = _dedupe_latest(recent_snapshots, "item_id")

    return {
        "market_summary": {
            **_summarize_prices(latest_run_snapshots),
            "snapshot_time": snapshots[-1].get("snapshot_time"),
        },
        "history_summary": {
            "unique_items": len(latest_records_by_item),
            **_summarize_prices(latest_records_by_item),
        },
        "daily_trend": _build_daily_trend(recent_snapshots),
        "latest_snapshot_at": snapshots[-1].get("snapshot_time"),
    }
