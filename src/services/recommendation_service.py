"""AI 推荐结果与一年持有成本计算。

口径：
    coefficient = 0.55*chip + 0.35*memory + 0.10*storage
    retention   = 1 - 一年期前瞻折旧率（按机龄）
    value       = coefficient * retention / price * 10000
    hold_score  = coefficient / 一年预计亏损 * 10000

一年期折旧率按机龄取值，是估算假设，不是真实成交残值。
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from typing import Optional

from src.infrastructure.persistence.sqlite_connection import get_database_path
from src.services.spec_utils import (
    normalize_chip,
    normalize_memory,
    normalize_storage,
    parse_chip_from_text,
    parse_memory_from_text,
    parse_storage_from_text,
)

CHIP_FACTORS = {
    "m1": 0.72,
    "m1pro": 0.86,
    "m1max": 1.02,
    "m2": 0.85,
    "m2pro": 1.00,
    "m2max": 1.18,
    "m3": 0.95,
    "m3pro": 1.12,
    "m3max": 1.32,
    "m4": 1.06,
    "m4pro": 1.25,
    "m4max": 1.48,
    "m5": 1.18,
    "m5pro": 1.40,
    "m5max": 1.65,
}
STORAGE_FACTORS = {
    128: 0.95,
    256: 0.97,
    512: 1.00,
    1024: 1.08,
    2048: 1.18,
    4096: 1.35,
    8192: 1.60,
}
CHIP_WEIGHT = 0.55
MEMORY_WEIGHT = 0.35
STORAGE_WEIGHT = 0.10

# 一年期前瞻折旧率：按机龄（当前年份 - 机型年份），不是历史残值率。
FORWARD_DEPRECIATION_BY_AGE = {
    0: 0.15,
    1: 0.13,
    2: 0.11,
    3: 0.09,
    4: 0.08,
    5: 0.07,
}
DEFAULT_FORWARD_DEPRECIATION = 0.10
DEPRECIATION_RANGE = 0.03
CHIP_DEFAULT_YEAR = {
    "m1": 2020,
    "m1pro": 2021,
    "m1max": 2021,
    "m2": 2023,
    "m2pro": 2023,
    "m2max": 2023,
    "m3": 2023,
    "m3pro": 2023,
    "m3max": 2023,
    "m4": 2024,
    "m4pro": 2024,
    "m4max": 2024,
    "m5": 2026,
    "m5pro": 2026,
    "m5max": 2026,
}

YEAR_IN_TITLE_RE = re.compile(
    r"20(2[1-6])\s*年(?:\d{1,2}\s*月)?\s*款"
    r"|20(2[1-6])\s*款"
    r"|(2[1-6])\s*年(?:\d{1,2}\s*月)?\s*款"
    r"|(2[1-6])\s*款"
)
YEAR_FACTORY_RE = re.compile(r"20(2[1-6])\s*年[^，。；\n]{0,8}(?:出厂|生产|上市)")
SCREEN_RE = re.compile(r"(\d{2}(?:\.\d)?)\s*[寸英寸]")
BATTERY_PCT_RE = re.compile(
    r"(?:电池|健康|容量|最大容量)[^\d]{0,6}(\d{2,3})\s*%"
    r"|(\d{2,3})\s*%[^\d]{0,4}(?:健康|容量)"
)
CYCLES_RE = re.compile(r"循环[^\d]{0,4}(\d{1,4})\s*次")


def format_size(value, title: str, description: str) -> str:
    text = str(value) if value is not None else ""
    if not text:
        match = SCREEN_RE.search(f"{title} {description}")
        text = match.group(1) if match else ""
    if not text:
        return "-"
    return text.replace(".0", "")


def chip_label(chip: Optional[str]) -> str:
    if not chip:
        return "-"
    match = re.fullmatch(r"m(\d)(pro|max)?", chip)
    if not match:
        return chip.upper()
    return f"M{match.group(1)}{(' ' + match.group(2).title()) if match.group(2) else ''}"


def parse_year(title: str, description: str) -> str:
    text = f"{title} {description}"
    match = YEAR_IN_TITLE_RE.search(text)
    if match:
        value = next((group for group in match.groups() if group), None)
        if value:
            return f"20{value}"
    match = YEAR_FACTORY_RE.search(text)
    if match:
        return f"20{match.group(1)}"
    return "-"


def short_link(link: str) -> str:
    match = re.search(r"item\?id=(\d+)", link or "")
    if match:
        return f"https://www.goofish.com/item?id={match.group(1)}"
    return link or ""


def parse_battery(spec: dict, title: str, description: str) -> str:
    health = normalize_memory(spec.get("battery_health_pct"))
    cycles = normalize_memory(spec.get("battery_cycles"))
    text = f"{title} {description}"
    if health is None:
        match = BATTERY_PCT_RE.search(text)
        if match:
            health = normalize_memory(match.group(1) or match.group(2))
    if cycles is None:
        match = CYCLES_RE.search(text)
        if match:
            cycles = normalize_memory(match.group(1))
    parts = []
    if health is not None:
        parts.append(f"{health}%")
    if cycles is not None:
        parts.append(f"循环{cycles}次")
    return " / ".join(parts) or "-"


def format_storage(value: Optional[int]) -> str:
    if value is None:
        return "-"
    if value >= 1024 and value % 1024 == 0:
        return f"{value // 1024}TB"
    return f"{value}G"


def config_coefficient(chip: Optional[str], memory: Optional[int], storage: Optional[int]) -> Optional[float]:
    if not chip or memory is None or storage is None:
        return None
    chip_factor = CHIP_FACTORS.get(chip)
    if chip_factor is None:
        return None
    memory_factor = max(0.75, min(2.0, 1 + (memory - 24) / 100))
    storage_factor = STORAGE_FACTORS.get(storage, 1.0)
    return round(
        CHIP_WEIGHT * chip_factor
        + MEMORY_WEIGHT * memory_factor
        + STORAGE_WEIGHT * storage_factor,
        3,
    )


def model_age(year: str, chip: Optional[str]) -> Optional[int]:
    """机龄 = 当前年份 - 机型年份；年份缺失时用芯片代际兜底。"""
    numeric_year: Optional[int] = None
    if year and year != "-":
        try:
            numeric_year = int(year)
        except ValueError:
            numeric_year = None
    if numeric_year is None and chip:
        numeric_year = CHIP_DEFAULT_YEAR.get(chip)
    if numeric_year is None:
        return None
    return max(0, datetime.now().year - numeric_year)


def one_year_depreciation(age: Optional[int]) -> float:
    return FORWARD_DEPRECIATION_BY_AGE.get(age, DEFAULT_FORWARD_DEPRECIATION)


def value_per_10k(coefficient: Optional[float], price: Optional[float]) -> Optional[float]:
    if coefficient is None or not price:
        return None
    return round(coefficient / price * 10000, 2)


def build_rows(conn: sqlite3.Connection, task_filter: Optional[str]) -> list[dict]:
    query = """
        SELECT task_name, item_id, title, price, link, raw_json
        FROM result_items
        WHERE status='active' AND is_recommended=1 AND analysis_source='ai'
        ORDER BY task_name ASC, price ASC
    """
    rows = []
    for record in conn.execute(query):
        task_name = str(record["task_name"] or "")
        if task_filter and task_filter.lower() not in task_name.lower():
            continue
        try:
            raw = json.loads(record["raw_json"] or "{}")
        except json.JSONDecodeError:
            raw = {}
        item = raw.get("商品信息") or {}
        analysis = raw.get("ai_analysis") or {}
        spec = analysis.get("spec") or {}
        title = str(record["title"] or item.get("商品标题") or "")
        description = str(item.get("商品描述") or "")
        region = str(
            item.get("发货地区")
            or item.get("地区")
            or item.get("所在地")
            or ""
        ).strip()

        ai_chip = normalize_chip(spec.get("chip"))
        title_chip = normalize_chip(parse_chip_from_text(title))
        # 芯片以 AI spec 为准；标题只在 AI 缺失时兜底。
        chip = ai_chip or title_chip

        memory = normalize_memory(spec.get("memory_gb")) or parse_memory_from_text(
            f"{title} {description}"
        )
        storage = normalize_storage(spec.get("storage_gb")) or parse_storage_from_text(
            f"{title} {description}"
        )
        price = float(record["price"]) if record["price"] is not None else None
        coefficient = config_coefficient(chip, memory, storage)
        year = parse_year(title, description)
        age = model_age(year, chip)
        depreciation = one_year_depreciation(age)
        retention = round(1 - depreciation, 3)
        adjusted = round(coefficient * retention, 3) if coefficient is not None else None
        value = value_per_10k(adjusted, price)
        resale_1y = round(price * (1 - depreciation), 0) if price else None
        loss_1y = round(price * depreciation, 0) if price else None
        loss_low = round(price * max(0.05, depreciation - DEPRECIATION_RANGE), 0) if price else None
        loss_high = round(price * min(0.25, depreciation + DEPRECIATION_RANGE), 0) if price else None
        hold_score = value_per_10k(coefficient, loss_1y)
        task_chip = normalize_chip(parse_chip_from_text(task_name))
        chip_display = chip_label(chip)
        if task_chip and chip and chip != task_chip:
            chip_display = f"{chip_display} *"

        rows.append(
            {
                "task": task_name,
                "item_id": str(record["item_id"] or ""),
                "title": title,
                "price": price,
                "link": short_link(record["link"] or ""),
                "region": region or "-",
                "size": format_size(spec.get("screen_inch"), title, description),
                "year": year,
                "age": age,
                "chip": chip_display,
                "chip_raw": chip,
                "task_chip": task_chip,
                "memory": f"{memory}G" if memory else "-",
                "storage": format_storage(storage),
                "battery": parse_battery(spec, title, description),
                "coefficient": coefficient,
                "depreciation": depreciation,
                "retention": retention,
                "adjusted": adjusted,
                "resale_1y": resale_1y,
                "loss_1y": loss_1y,
                "loss_low": loss_low,
                "loss_high": loss_high,
                "hold_score": hold_score,
                "value": value,
                "ai_value_score": analysis.get("value_score"),
            }
        )
    return rows


def build_recommendation_summary(task_filter: Optional[str] = None) -> dict:
    """读取 SQLite 并返回可直接序列化为 JSON 的推荐汇总。"""
    conn = sqlite3.connect(get_database_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    try:
        rows = build_rows(conn, task_filter)
    finally:
        conn.close()

    rows.sort(
        key=lambda row: (
            row["value"] if row["value"] is not None else -1,
            row["hold_score"] if row["hold_score"] is not None else -1,
        ),
        reverse=True,
    )
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "valuation_year": datetime.now().year,
        "total_items": len(rows),
        "ranked_items": sum(row["value"] is not None for row in rows),
        "weights": {
            "chip": CHIP_WEIGHT,
            "memory": MEMORY_WEIGHT,
            "storage": STORAGE_WEIGHT,
        },
        "depreciation_by_age": [
            {"age": age, "rate": rate}
            for age, rate in sorted(FORWARD_DEPRECIATION_BY_AGE.items())
        ],
        "default_depreciation": DEFAULT_FORWARD_DEPRECIATION,
        "depreciation_range": DEPRECIATION_RANGE,
        "rows": rows,
    }
