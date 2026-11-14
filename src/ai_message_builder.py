"""
AI 请求消息构造辅助函数
"""
from typing import Dict, List, Union


TEXT_ONLY_ANALYSIS_NOTE = (
    "补充说明：本次未提供商品图片，请仅根据商品文字字段和卖家信息判断，不要推断图片内容。"
)

PRICE_SCOPE_NOTE = (
    "\n价格参考中的“同配置参考”已按当前商品配置筛选。"
    "只有当“参考口径.fallback_level”为 exact 且 sample_count 达到任务要求时，"
    "才能据此判断性价比并输出 value_score；否则请在 reason 中说明配置样本不足，"
    "不要用“当前搜索样本”或“历史价格概览”的混合均价下结论。\n"
)


def build_analysis_text_prompt(
    product_json: str,
    prompt_text: str,
    *,
    include_images: bool,
    has_scoped_price_reference: bool = False,
) -> str:
    note = "" if include_images else f"\n{TEXT_ONLY_ANALYSIS_NOTE}\n"
    value_note = (
        "\n如果商品 JSON 中包含“同配置参考”，请优先使用它判断价格位置；"
        "若没有，再结合“价格参考”中的价格位置、历史走势、"
        "配置、成色、附件、卖家信息综合判断性价比。"
        "你可以额外输出可选字段 value_score(0-100) 和 value_summary，"
        "但必须保留原有 is_recommended/reason 等字段。\n"
    )
    scope_note = PRICE_SCOPE_NOTE if has_scoped_price_reference else ""
    return f"""请基于你的专业知识和我的要求，分析以下完整的商品JSON数据：

```json
{product_json}
```

    {prompt_text}
    {value_note}
    {scope_note}
    {note}"""


def build_user_message_content(
    text_prompt: str,
    image_data_urls: List[str],
) -> Union[str, List[Dict[str, object]]]:
    if not image_data_urls:
        return text_prompt

    user_content: List[Dict[str, object]] = [
        {"type": "image_url", "image_url": {"url": url}}
        for url in image_data_urls
    ]
    user_content.append({"type": "text", "text": text_prompt})
    return user_content
