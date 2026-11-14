import json
import sqlite3
from datetime import datetime

from src.services.recommendation_service import (
    build_rows,
    config_coefficient,
    model_age,
    parse_year,
)


def test_m1max_coefficient_available():
    coefficient = config_coefficient("m1max", 64, 1024)
    assert coefficient is not None
    assert coefficient > config_coefficient("m1pro", 64, 1024)


def test_parse_year_accepts_2021_model():
    assert parse_year("MacBook Pro 16寸 2021款 M1 Max 64G+1T", "") == "2021"
    assert parse_year("21款 MacBook Pro 14寸 M1 Max", "") == "2021"


def test_model_age_falls_back_to_m1max_year():
    expected = max(0, datetime.now().year - 2021)
    assert model_age("-", "m1max") == expected


def _memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE result_items (
            task_name TEXT,
            item_id TEXT,
            title TEXT,
            price REAL,
            link TEXT,
            raw_json TEXT,
            status TEXT,
            is_recommended INTEGER,
            analysis_source TEXT
        )
        """
    )
    raw = {
        "商品信息": {
            "商品标题": "MacBook Pro 16寸 2021款 M1 Max 64G+1T",
            "商品描述": "",
            "发货地区": "上海",
        },
        "ai_analysis": {
            "spec": {
                "chip": "M1 Max",
                "memory_gb": 64,
                "storage_gb": 1024,
                "screen_inch": 16,
                "battery_health_pct": 88,
            }
        },
    }
    conn.execute(
        "INSERT INTO result_items VALUES (?,?,?,?,?,?,?,?,?)",
        (
            "m1max-64g-1t",
            "9001",
            "MacBook Pro 16寸 2021款 M1 Max 64G+1T",
            11000.0,
            "https://www.goofish.com/item?id=9001",
            json.dumps(raw, ensure_ascii=False),
            "active",
            1,
            "ai",
        ),
    )
    return conn


def test_build_rows_ranks_m1max_result():
    conn = _memory_conn()
    try:
        rows = build_rows(conn, None)
    finally:
        conn.close()

    assert len(rows) == 1
    row = rows[0]
    assert row["task"] == "m1max-64g-1t"
    assert row["task_chip"] == "m1max"
    assert row["region"] == "上海"
    assert row["chip"] == "M1 Max"
    assert row["memory"] == "64G"
    assert row["storage"] == "1TB"
    assert row["year"] == "2021"
    assert row["coefficient"] is not None
    assert row["value"] is not None
    assert row["hold_score"] is not None


def test_one_year_depreciation_stays_monotonic_for_old_models():
    from src.services.recommendation_service import (
        DEFAULT_FORWARD_DEPRECIATION,
        one_year_depreciation,
    )

    rates = [one_year_depreciation(age) for age in range(0, 11)]
    assert rates == sorted(rates, reverse=True)
    assert one_year_depreciation(6) < one_year_depreciation(5)
    assert one_year_depreciation(None) == DEFAULT_FORWARD_DEPRECIATION
