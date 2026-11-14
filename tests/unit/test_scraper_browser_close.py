import asyncio
import subprocess
import sys

from src import scraper


class WorkingBrowser:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


class HangingBrowser:
    async def close(self):
        await asyncio.sleep(30)


class BrokenBrowser:
    async def close(self):
        raise RuntimeError("target closed")


def test_close_browser_safely_closes_normally():
    browser = WorkingBrowser()

    assert asyncio.run(scraper._close_browser_safely(browser, timeout=1)) is True
    assert browser.closed is True


def test_close_browser_safely_times_out_and_forces_kill():
    calls = []

    ok = asyncio.run(
        scraper._close_browser_safely(
            HangingBrowser(),
            timeout=0.05,
            force_kill=lambda: calls.append("kill") or 1,
        )
    )

    assert ok is False
    assert calls == ["kill"]


def test_close_browser_safely_falls_back_on_exception():
    calls = []

    ok = asyncio.run(
        scraper._close_browser_safely(
            BrokenBrowser(),
            timeout=1,
            force_kill=lambda: calls.append("kill") or 1,
        )
    )

    assert ok is False
    assert calls == ["kill"]


def test_iter_descendant_pids_finds_child():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert child.pid in scraper._iter_descendant_pids()
    finally:
        child.kill()
        child.wait()


def test_kill_descendant_processes_kills_child():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        killed = scraper._kill_descendant_processes()
        assert killed >= 1
        child.wait(timeout=10)
        assert child.returncode == -9
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()


def test_kill_descendant_processes_respects_markers():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert scraper._kill_descendant_processes(markers=("chrome",)) == 0
        assert child.poll() is None
    finally:
        child.kill()
        child.wait()


def test_force_kill_browser_processes_ignores_non_browser_children():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert scraper._force_kill_browser_processes() == 0
        assert child.poll() is None
    finally:
        child.kill()
        child.wait()
