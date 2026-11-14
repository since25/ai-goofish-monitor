"""从任务关键词/需求描述中推断价格参考口径。

只在用户明确给出「芯片 + 内存范围」时启用，避免猜错：
  - 芯片：M4 Pro / M3 Max 等
  - 内存：24-48G / 24GB 至 48GB / 24、32、36、48G
"""

from __future__ import annotations

import re
from typing import Optional

from src.domain.models.task import PriceScope
from src.infrastructure.external.ai_client import AIClient
from src.services.ai_response_parser import parse_ai_response_json
from src.services.spec_utils import (
    PLAUSIBLE_MEMORY,
    normalize_chip,
    parse_chip_from_text,
)

MEMORY_RANGE_RE = re.compile(
    r"(\d{2,3})\s*(?:GB|G|g)?\s*(?:-|~|—|－|到|至)\s*(\d{2,3})\s*(?:GB|G|g)",
    re.IGNORECASE,
)
MEMORY_RANGE_RE_REVERSED = re.compile(
    r"(\d{2,3})\s*(?:GB|G|g)\s*(?:-|~|—|－|到|至)\s*(\d{2,3})\s*(?:GB|G|g)?",
    re.IGNORECASE,
)
MEMORY_TOKEN_RE = re.compile(r"(\d{2,3})\s*(?:GB|G|g)(?![A-Za-z])")


def _parse_memory_range(text: str) -> Optional[tuple[int, int]]:
    for pattern in (MEMORY_RANGE_RE, MEMORY_RANGE_RE_REVERSED):
        match = pattern.search(text)
        if not match:
            continue
        low, high = int(match.group(1)), int(match.group(2))
        if low > high:
            low, high = high, low
        if low in PLAUSIBLE_MEMORY and high in PLAUSIBLE_MEMORY:
            return low, high

    # “内存 24G/32G/36G/48G” 这类列表：只在“内存”附近收集带 G 的数字
    for marker in re.finditer(r"内存|运存|统一内存", text):
        window = text[marker.start() : marker.start() + 60]
        values = [
            int(value)
            for value in MEMORY_TOKEN_RE.findall(window)
            if int(value) in PLAUSIBLE_MEMORY
        ]
        if len(values) >= 2:
            return min(values), max(values)
    return None


def infer_price_scope(keyword: str, description: str = "") -> Optional[PriceScope]:
    """有明确芯片和内存范围时返回 config 口径，否则返回 None。"""
    keyword_text = str(keyword or "")
    description_text = str(description or "")
    chip = normalize_chip(parse_chip_from_text(keyword_text)) or normalize_chip(
        parse_chip_from_text(description_text)
    )
    if not chip:
        return None
    memory_range = _parse_memory_range(description_text) or _parse_memory_range(
        keyword_text
    )
    if not memory_range:
        return None

    low, high = memory_range
    return PriceScope(
        mode="config",
        match={"chip": chip, "memory_gb": [low, high]},
        bucket_by=["chip", "memory_gb", "storage_gb"],
        window_days=30,
        min_samples=5,
        fallback=["drop_storage"],
    )


PRICE_SCOPE_PROMPT = """你是二手交易监控系统的价格参考口径提取器。

根据下面的【搜索关键词】和【购买需求】，提取“同配置比价”所需的结构化约束。
只输出一个 JSON 对象，不要输出解释或代码块。

规则：
1. 只有用户明确指定了“芯片/型号”和“内存范围”时才启用。
2. 无法确认时输出 {"mode": "keyword"}。
3. chip 使用小写、无空格形式，例如 m4pro、m3max。
4. memory_gb 使用 [最小值, 最大值]；storage_gb 可选。

输出格式：
{
  "mode": "config",
  "match": {"chip": "m4pro", "memory_gb": [24, 48]},
  "bucket_by": ["chip", "memory_gb", "storage_gb"],
  "window_days": 30,
  "min_samples": 5,
  "fallback": ["drop_storage"]
}

【搜索关键词】
{keyword}

【购买需求】
{description}
"""


def _normalize_memory_range(value) -> Optional[tuple[int, int]]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    low, high = value
    try:
        low, high = int(float(low)), int(float(high))
    except (TypeError, ValueError):
        return None
    if low > high:
        low, high = high, low
    if low not in PLAUSIBLE_MEMORY or high not in PLAUSIBLE_MEMORY:
        return None
    return low, high


async def infer_price_scope_with_ai(
    keyword: str,
    description: str = "",
) -> Optional[PriceScope]:
    """让 LLM 输出结构化口径；失败/无明确约束时返回 None。"""
    client = AIClient()
    if not client.is_available():
        return None
    try:
        text = await client._call_ai(
            [
                {
                    "role": "user",
                    "content": PRICE_SCOPE_PROMPT.replace(
                        "{keyword}", keyword or ""
                    ).replace("{description}", description or ""),
                }
            ],
            temperature=0,
            max_output_tokens=500,
            enable_json_output=True,
        )
        payload = parse_ai_response_json(text)
        if not isinstance(payload, dict) or payload.get("mode") != "config":
            return None
        match = payload.get("match") or {}
        chip = normalize_chip(match.get("chip"))
        memory_range = _normalize_memory_range(match.get("memory_gb"))
        if not chip or not memory_range:
            return None
        bucket_by = payload.get("bucket_by") or [
            "chip",
            "memory_gb",
            "storage_gb",
        ]
        if not isinstance(bucket_by, list):
            bucket_by = ["chip", "memory_gb", "storage_gb"]
        fallback = payload.get("fallback") or ["drop_storage"]
        if not isinstance(fallback, list):
            fallback = ["drop_storage"]
        return PriceScope(
            mode="config",
            match={"chip": chip, "memory_gb": list(memory_range)},
            bucket_by=[str(key) for key in bucket_by if str(key).strip()],
            window_days=max(1, int(payload.get("window_days") or 30)),
            min_samples=max(1, int(payload.get("min_samples") or 5)),
            fallback=[
                item
                for item in fallback
                if item in {"drop_storage", "drop_memory", "task"}
            ],
        )
    except Exception:
        return None
    finally:
        await client.close()
