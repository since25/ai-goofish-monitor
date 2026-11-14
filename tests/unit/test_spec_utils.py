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


def test_chip_allows_plus_between_generation_and_suffix():
    assert parse_chip_from_text("2023款+M3+Max+16寸") == "m3max"


def test_storage_is_not_confused_with_memory():
    spec = parse_spec_from_title("macbook m3 max，16寸，128G内存 4T硬盘，美版")
    assert spec["memory_gb"] == 128
    assert spec["storage_gb"] == 4096


def test_battery_health_and_cycles_from_text():
    spec = parse_spec_from_title("Macbook Pro 16寸 M3Max 36G+1T 电池循环54，电池健康100%")
    assert spec["battery_health_pct"] == 100.0
    assert spec["battery_cycles"] == 54

    spec = parse_spec_from_title("循环次数：440次 最大容量：91%")
    assert spec["battery_health_pct"] == 91.0
    assert spec["battery_cycles"] == 440

    spec = parse_spec_from_title("电池最大容量100%。 22次循环")
    assert spec["battery_health_pct"] == 100.0
    assert spec["battery_cycles"] == 22


def test_memory_storage_combo_without_units():
    spec = parse_spec_from_title("美版，银色，m3max 16寸，48+1t 充电次数10次左右")
    assert spec["memory_gb"] == 48
    assert spec["storage_gb"] == 1024
    assert spec["battery_cycles"] == 10

    spec = parse_spec_from_title("2023款 M3 Max 16寸 48内存+1TB硬盘 电池,容量 96%")
    assert spec["memory_gb"] == 48
    assert spec["storage_gb"] == 1024
    assert spec["battery_health_pct"] == 96.0


def test_spaced_chip_falls_back_to_description():
    title = "美版 MacBook Pro 14 寸 M3 Ma x 64G 2T 电池健康度 98"
    description = "美版 MacBook Pro 14 寸 M3 Max 64G 2T，外观很新"
    spec = parse_spec_from_title(f"{title} {description}")
    assert spec["chip"] == "m3max"
    assert spec["battery_health_pct"] == 98.0
