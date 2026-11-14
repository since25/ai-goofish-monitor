"""商品配置（spec）解析与缓存工具。

价格参考按配置分桶时需要两类数据：

1. 已分析商品的 ``ai_analysis.spec``（最准，按 item_id 复用）；
2. 标题正则兜底（新商品、历史未分析商品）。

这里不依赖 AI 客户端，也不写数据库。
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Optional

from src.infrastructure.persistence.sqlite_bootstrap import bootstrap_sqlite_storage
from src.infrastructure.persistence.sqlite_connection import sqlite_connection

PLAUSIBLE_MEMORY = frozenset({8, 16, 18, 24, 32, 36, 48, 64, 96, 128})

CHIP_RE = re.compile(r"(?<![A-Za-z0-9])M(\d{1,2})\s*(Pro|Max|Ultra)?(?![A-Za-z])", re.IGNORECASE)
MEM_WITH_LABEL_RE = re.compile(r"(\d{2,3})\s*(?:GB|G|g|Ｇ)\s*(?:内存|运存|统一内存)")
MEM_LABEL_FIRST_RE = re.compile(r"(?:内存|运存|统一内存)\s*[:：]?\s*(\d{2,3})")
MEM_COMBO_RE = re.compile(r"(\d{2,3})\s*[+＋/]\s*(\d{3,4})\s*(?:GB|G|g|Ｇ)?")
MEM_BARE_RE = re.compile(
    r"(?<![A-Za-z0-9])(16|18|24|32|36|48|64|96|128)\s*(?:GB|G|g|Ｇ)(?![A-Za-z0-9])"
)
STORAGE_LABEL_RE = re.compile(r"(\d{3,4})\s*(?:GB|G|g|Ｇ)\s*(?:固态|硬盘|存储|SSD)")
STORAGE_TB_RE = re.compile(r"(\d+(?:\.\d+)?)\s*TB", re.IGNORECASE)
STORAGE_BARE_RE = re.compile(
    r"(?<![A-Za-z0-9])(128|256|512|1024|2048|4096)\s*(?:GB|G|g|Ｇ)(?![A-Za-z0-9])"
)
SCREEN_RE = re.compile(r"(\d{2}(?:\.\d)?)\s*[寸英寸]")
COLOR_RE = re.compile(r"深空灰|深空黑|银色|黑色|星空色|午夜色|星光色")
REGION_RE = re.compile(r"国行|美版|港版|日版|澳版|欧版|韩版")

SPEC_KEYS = (
    "model",
    "chip",
    "memory_gb",
    "storage_gb",
    "screen_inch",
    "color",
    "region",
    "battery_health_pct",
    "battery_cycles",
)

SpecResolver = Callable[[str, str], dict]


def is_plausible_storage(value: Optional[int]) -> bool:
    """过滤 '12+118核' 这类误把核心数当硬盘的解析。"""
    if value is None:
        return False
    if value in (32, 64):
        return True
    return 128 <= value <= 16384 and value % 128 == 0


def normalize_chip(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).lower().replace(" ", "").replace("-", "").replace("_", "")
    match = re.search(r"m(\d{1,2})(pro|max|ultra)?", text)
    if not match:
        return None
    return f"m{match.group(1)}{match.group(2) or ''}"


def normalize_memory(value: Any) -> Optional[int]:
    if value is None or value == "" or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().upper().replace("GB", "").replace("G", "").strip()
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def normalize_storage(value: Any) -> Optional[int]:
    if value is None or value == "" or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = str(value).strip().upper().replace("GB", "").replace("G", "").strip()
        try:
            number = float(text)
        except (TypeError, ValueError):
            return None
    storage = int(number * 1024) if number < 100 else int(number)
    return storage if is_plausible_storage(storage) else None


def normalize_screen(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace("寸", "").replace("英寸", "").strip())
    except (TypeError, ValueError):
        return None


def normalize_spec_value(key: str, value: Any) -> Any:
    if key == "chip":
        return normalize_chip(value)
    if key in {"memory_gb", "battery_cycles"}:
        return normalize_memory(value)
    if key == "storage_gb":
        return normalize_storage(value)
    if key in {"screen_inch", "battery_health_pct"}:
        return normalize_screen(value)
    if value is None:
        return None
    return str(value).strip().lower()


def normalize_spec(spec: dict[str, Any]) -> dict[str, Any]:
    return {
        key: normalize_spec_value(key, (spec or {}).get(key))
        for key in SPEC_KEYS
    }


def parse_chip_from_text(text: str) -> Optional[str]:
    match = CHIP_RE.search(text or "")
    if not match:
        return None
    suffix = (match.group(2) or "").lower()
    return f"m{match.group(1)}{suffix}"


def parse_memory_from_text(text: str) -> Optional[int]:
    text = text or ""
    for pattern in (MEM_WITH_LABEL_RE, MEM_LABEL_FIRST_RE):
        match = pattern.search(text)
        if match:
            value = normalize_memory(match.group(1))
            if value in PLAUSIBLE_MEMORY:
                return value
    match = MEM_COMBO_RE.search(text)
    if match:
        value = normalize_memory(match.group(1))
        if value in PLAUSIBLE_MEMORY and value >= 16:
            return value
    match = MEM_BARE_RE.search(text)
    if match:
        value = normalize_memory(match.group(1))
        if value in PLAUSIBLE_MEMORY:
            return value
    return None


def parse_storage_from_text(text: str) -> Optional[int]:
    text = text or ""
    match = STORAGE_TB_RE.search(text)
    if match:
        try:
            value = int(float(match.group(1)) * 1024)
        except ValueError:
            return None
        return value if is_plausible_storage(value) else None
    match = STORAGE_LABEL_RE.search(text)
    if match:
        return normalize_storage(match.group(1))
    match = MEM_COMBO_RE.search(text)
    if match:
        return normalize_storage(match.group(2))
    match = STORAGE_BARE_RE.search(text)
    if match:
        return normalize_storage(match.group(1))
    return None


def parse_spec_from_title(title: str) -> dict[str, Any]:
    text = title or ""
    screen_match = SCREEN_RE.search(text)
    color_match = COLOR_RE.search(text)
    region_match = REGION_RE.search(text)
    return normalize_spec(
        {
            "chip": parse_chip_from_text(text),
            "memory_gb": parse_memory_from_text(text),
            "storage_gb": parse_storage_from_text(text),
            "screen_inch": screen_match.group(1) if screen_match else None,
            "color": color_match.group(0) if color_match else None,
            "region": region_match.group(0) if region_match else None,
        }
    )


def load_item_spec_cache(keyword: Optional[str] = None) -> dict[str, dict]:
    """item_id -> 最近一次成功分析出的 spec。"""
    bootstrap_sqlite_storage()
    query = (
        "SELECT item_id, raw_json FROM result_items "
        "WHERE item_id IS NOT NULL AND raw_json IS NOT NULL"
    )
    params: tuple = ()
    if keyword:
        query += " AND keyword = ?"
        params = (keyword,)
    query += " ORDER BY crawl_time ASC, id ASC"

    cache: dict[str, dict] = {}
    with sqlite_connection() as conn:
        for row in conn.execute(query, params):
            item_id = str(row["item_id"] or "").strip()
            if not item_id:
                continue
            try:
                record = json.loads(row["raw_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                continue
            spec = (record.get("ai_analysis") or {}).get("spec") or {}
            if not isinstance(spec, dict):
                continue
            normalized = normalize_spec(spec)
            if any(normalized.get(key) is not None for key in ("chip", "memory_gb", "storage_gb")):
                cache[item_id] = normalized
    return cache


def spec_has_values(spec: Optional[dict]) -> bool:
    return bool(
        spec
        and any(spec.get(key) is not None for key in ("chip", "memory_gb", "storage_gb"))
    )


def resolve_item_spec_with_source(
    item_id: str,
    title: str,
    cache: Optional[dict[str, dict]] = None,
) -> tuple[dict, str]:
    """AI spec 优先，标题正则逐字段兜底，并返回来源。"""
    base = (cache or {}).get(str(item_id or "")) or {}
    parsed = parse_spec_from_title(title or "")
    resolved = {}
    for key in SPEC_KEYS:
        value = base.get(key)
        resolved[key] = value if value is not None else parsed.get(key)
    resolved = normalize_spec(resolved)
    if spec_has_values(base):
        source = "ai"
    elif spec_has_values(parsed):
        source = "title"
    else:
        source = "unknown"
    return resolved, source


def resolve_item_spec(
    item_id: str,
    title: str,
    cache: Optional[dict[str, dict]] = None,
) -> dict:
    spec, _ = resolve_item_spec_with_source(item_id, title, cache)
    return spec


def make_spec_resolver(cache: Optional[dict[str, dict]] = None) -> SpecResolver:
    def resolver(item_id: str, title: str) -> dict:
        return resolve_item_spec(item_id, title, cache)

    return resolver
