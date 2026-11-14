import os
import subprocess
import sys
import time
from pathlib import Path

import spider_v2

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_resolve_max_runtime_seconds_default_and_env(monkeypatch):
    monkeypatch.delenv(spider_v2.SPIDER_MAX_RUNTIME_ENV, raising=False)
    assert (
        spider_v2.resolve_max_runtime_seconds()
        == spider_v2.DEFAULT_MAX_RUNTIME_SECONDS
    )

    monkeypatch.setenv(spider_v2.SPIDER_MAX_RUNTIME_ENV, "600")
    assert spider_v2.resolve_max_runtime_seconds() == 600

    monkeypatch.setenv(spider_v2.SPIDER_MAX_RUNTIME_ENV, "0")
    assert (
        spider_v2.resolve_max_runtime_seconds()
        == spider_v2.DEFAULT_MAX_RUNTIME_SECONDS
    )


def test_runtime_watchdog_force_exits_process():
    """看门狗到点后用 124 强制退出，避免卡死进程长期驻留。"""
    script = (
        "import time\n"
        "from spider_v2 import install_runtime_watchdog\n"
        "install_runtime_watchdog(1)\n"
        "time.sleep(30)\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)

    started = time.monotonic()
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    elapsed = time.monotonic() - started

    assert proc.returncode == 124
    assert "看门狗" in proc.stdout
    assert elapsed < 10
