"""
结果导出服务
"""
import csv
from io import StringIO


EXPORT_HEADERS = [
    "任务名称",
    "搜索关键字",
    "商品ID",
    "商品标题",
    "型号",
    "芯片",
    "尺寸",
    "内存GB",
    "硬盘GB",
    "颜色",
    "版本",
    "电池健康",
    "循环次数",
    "保修",
    "当前售价",
    "发布时间",
    "卖家昵称",
    "AI是否推荐",
    "分析来源",
    "原因",
    "价格观察次数",
    "价格最低值",
    "价格最高值",
    "市场均价",
    "性价比分数",
    "性价比标签",
    "商品链接",
]


def _spec_value(spec: dict, key: str, suffix: str = "") -> str:
    value = spec.get(key)
    if value is None or value == "":
        return ""
    return f"{value}{suffix}"



def build_results_csv(records: list[dict]) -> str:
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=EXPORT_HEADERS)
    writer.writeheader()

    for record in records:
        item = record.get("商品信息", {}) or {}
        seller = record.get("卖家信息", {}) or {}
        ai_analysis = record.get("ai_analysis", {}) or {}
        price_insight = record.get("price_insight", {}) or {}
        spec = ai_analysis.get("spec") or {}
        writer.writerow(
            {
                "任务名称": record.get("任务名称", ""),
                "搜索关键字": record.get("搜索关键字", ""),
                "商品ID": item.get("商品ID", ""),
                "商品标题": item.get("商品标题", ""),
                "型号": _spec_value(spec, "model"),
                "芯片": _spec_value(spec, "chip"),
                "尺寸": _spec_value(spec, "screen_inch", "寸"),
                "内存GB": _spec_value(spec, "memory_gb"),
                "硬盘GB": _spec_value(spec, "storage_gb"),
                "颜色": _spec_value(spec, "color"),
                "版本": _spec_value(spec, "region"),
                "电池健康": _spec_value(spec, "battery_health_pct", "%"),
                "循环次数": _spec_value(spec, "battery_cycles"),
                "保修": _spec_value(spec, "warranty"),
                "当前售价": item.get("当前售价", ""),
                "发布时间": item.get("发布时间", ""),
                "卖家昵称": seller.get("卖家昵称") or item.get("卖家昵称", ""),
                "AI是否推荐": "是" if ai_analysis.get("is_recommended") else "否",
                "分析来源": ai_analysis.get("analysis_source", ""),
                "原因": ai_analysis.get("reason", ""),
                "价格观察次数": price_insight.get("observation_count", ""),
                "价格最低值": price_insight.get("min_price", ""),
                "价格最高值": price_insight.get("max_price", ""),
                "市场均价": price_insight.get("market_avg_price", ""),
                "性价比分数": ai_analysis.get("value_score", price_insight.get("deal_score", "")),
                "性价比标签": ai_analysis.get("value_summary", price_insight.get("deal_label", "")),
                "商品链接": item.get("商品链接", ""),
            }
        )

    return buffer.getvalue()
