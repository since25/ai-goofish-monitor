import asyncio
import json

from src import scraper


def test_collector_config_requires_enabled_and_result_path():
    assert scraper._collector_config({}) == {}
    assert scraper._collector_config({"collector": {"enabled": False}}) == {}
    assert scraper._collector_config({"collector": {"enabled": True}}) == {}

    config = {"collector": {"enabled": True, "result_path": "/tmp/job/result.jsonl"}}
    assert scraper._collector_config(config)["result_path"] == "/tmp/job/result.jsonl"


def test_collector_saver_appends_json_lines(tmp_path):
    path = tmp_path / "job-1" / "result.jsonl"
    saver = scraper._build_collector_saver(str(path))

    assert asyncio.run(saver({"a": 1}, "kw")) is True
    assert asyncio.run(saver({"a": 2}, "kw")) is True

    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert records == [{"a": 1}, {"a": 2}]
