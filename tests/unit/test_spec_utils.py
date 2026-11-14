from src.services.spec_utils import parse_chip_from_text, parse_spec_from_title


def test_chip_accepts_hyphen_between_generation_and_suffix():
    # 闲鱼标题里真实出现过 “M4-Pro芯片” 这种写法
    assert parse_chip_from_text("Apple M4-Pro芯片 24G+512G") == "m4pro"
    assert parse_chip_from_text("MacBook Pro M4 Pro") == "m4pro"
    assert parse_chip_from_text("M3Max 36G") == "m3max"
    assert parse_chip_from_text("M1 8G+256G") == "m1"


def test_parse_spec_from_title_keeps_full_chip():
    spec = parse_spec_from_title("macbookpro 14寸 2024款 M4-Pro 24G+512G 国行")
    assert spec["chip"] == "m4pro"
    assert spec["memory_gb"] == 24
    assert spec["storage_gb"] == 512
    assert spec["screen_inch"] == 14.0
    assert spec["region"] == "国行"
