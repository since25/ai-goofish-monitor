"""一次性后台搜索任务：单飞队列 + 子进程 + 独立目录。

设计约定（与定时任务隔离）：
- 只在 ``search_jobs`` 表里登记，不写 ``tasks``；
- 结果写 ``data/search_jobs/<job_id>/result.jsonl``，不写 result_items；
- 不记录行情快照、不发通知、不跑 AI 判定；
- 同一时间只允许一个浏览器在跑（与定时任务互斥）。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from src.domain.models.search_job import SearchJob, SearchJobRequest
from src.infrastructure.persistence.sqlite_search_job_repository import (
    SqliteSearchJobRepository,
)
from src.services.price_history_service import parse_price_value
from src.services.spec_utils import parse_spec_from_title

DEFAULT_JOB_ROOT = "data/search_jobs"
DEFAULT_MAX_RUNTIME_SECONDS = 95 * 60
DEFAULT_IDLE_POLL_SECONDS = 5.0
STOP_TIMEOUT_SECONDS = 15


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _append_json_line(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(payload + "\n")


def count_result_lines(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            if line.strip():
                total += 1
    return total


def read_log_tail(path: Path, lines: int = 40) -> list[str]:
    if not path.exists():
        return []
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - 64 * 1024))
            chunk = handle.read().decode("utf-8", "replace")
    except OSError:
        return []
    content = chunk.splitlines()
    return content[-max(1, int(lines)):]


def build_collector_config(job: SearchJob, result_path: Path, log_path: Path) -> list[dict]:
    """spider_v2 --config 接受的任务数组（一条）。"""

    def _price(value: Optional[float]) -> Optional[str]:
        return None if value is None else str(value)

    return [
        {
            "task_name": job.task_name,
            "enabled": True,
            "keyword": job.keyword,
            "description": "",
            "analyze_images": False,
            "max_pages": job.max_pages,
            "personal_only": job.personal_only,
            "min_price": _price(job.min_price),
            "max_price": _price(job.max_price),
            "cron": "",
            "ai_prompt_base_file": "",
            "ai_prompt_criteria_file": "",
            "account_state_file": "",
            "account_strategy": "auto",
            "free_shipping": job.free_shipping,
            "new_publish_option": "",
            "region": job.region or "",
            "decision_mode": "keyword",
            "keyword_rules": [],
            "collector": {
                "enabled": True,
                "result_path": str(result_path),
                "log_path": str(log_path),
            },
        }
    ]


def flatten_record(record: dict) -> dict:
    info = record.get("商品信息", {}) or {}
    seller = record.get("卖家信息", {}) or {}
    title = str(info.get("商品标题") or "")
    description = str(info.get("商品描述") or "")
    spec = parse_spec_from_title(f"{title} {description}")
    return {
        "item_id": str(info.get("商品ID") or ""),
        "title": title,
        "price": parse_price_value(info.get("当前售价")),
        "price_display": info.get("当前售价"),
        "region": info.get("发货地区") or "",
        "seller": seller.get("卖家昵称") or info.get("卖家昵称") or "",
        "publish_time": info.get("发布时间") or "",
        "link": info.get("商品链接") or "",
        "description": description[:500],
        "spec": spec,
        "crawl_time": record.get("爬取时间") or "",
    }


class SearchJobService:
    """单飞队列 + 子进程管理。"""

    def __init__(
        self,
        repository=None,
        *,
        job_root: str = DEFAULT_JOB_ROOT,
        max_runtime_seconds: int = DEFAULT_MAX_RUNTIME_SECONDS,
        idle_poll_seconds: float = DEFAULT_IDLE_POLL_SECONDS,
        busy_check: Optional[Callable[[], bool]] = None,
    ) -> None:
        self._repo = repository or SqliteSearchJobRepository()
        self._job_root = Path(job_root)
        self._max_runtime_seconds = max(60, int(max_runtime_seconds))
        self._idle_poll_seconds = max(1.0, float(idle_poll_seconds))
        self._busy_check = busy_check
        self._queue: Optional[asyncio.Queue[str]] = None
        self._worker: Optional[asyncio.Task] = None
        self._process: Optional[asyncio.subprocess.Process] = None
        self._current_job_id: Optional[str] = None
        self._pending: set[str] = set()
        self._cancel_requested: set[str] = set()
        self._stopping = False

    # ---------- 生命周期 ----------

    def bind_busy_check(self, check: Optional[Callable[[], bool]]) -> None:
        """注入“定时任务是否在跑”的判断，用于错峰。"""
        self._busy_check = check

    def is_active(self) -> bool:
        """是否有搜索在跑或排队；定时任务启动前用它让路。"""
        return self._current_job_id is not None or bool(self._pending)

    async def start(self) -> None:
        interrupted = await asyncio.to_thread(self._repo.mark_interrupted)
        if interrupted:
            print(f"[搜索任务] 启动时清理了 {interrupted} 个未完成的任务")
        self._queue = asyncio.Queue()
        self._stopping = False
        self._worker = asyncio.create_task(self._worker_loop(), name="search-job-worker")

    async def stop(self) -> None:
        self._stopping = True
        process = self._process
        if process is not None and process.returncode is None:
            await self._terminate(process)
        worker = self._worker
        if worker is not None:
            worker.cancel()
            try:
                await worker
            except (asyncio.CancelledError, Exception):
                pass
        self._worker = None
        self._queue = None

    # ---------- 对外 API ----------

    async def submit(self, request: SearchJobRequest) -> SearchJob:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        job_id = f"{stamp}-{uuid.uuid4().hex[:6]}"
        job_dir = self._job_root / job_id
        await asyncio.to_thread(job_dir.mkdir, parents=True, exist_ok=True)
        job = SearchJob(
            id=job_id,
            task_name=f"search-{job_id}",
            keyword=request.keyword,
            max_pages=request.max_pages,
            min_price=request.min_price,
            max_price=request.max_price,
            region=request.region,
            personal_only=request.personal_only,
            free_shipping=request.free_shipping,
            status="queued",
            created_at=_now(),
            job_dir=str(job_dir),
        )
        config_path = job_dir / "config.json"
        payload = build_collector_config(job, job_dir / "result.jsonl", job_dir / "log.txt")
        await asyncio.to_thread(
            config_path.write_text,
            json.dumps(payload, ensure_ascii=False, indent=2),
            "utf-8",
        )
        await asyncio.to_thread(self._repo.save, job)
        self._pending.add(job.id)
        if self._queue is None:
            # 没有启动 worker（例如单测里只用 submit）时，任务保持 queued。
            print("[搜索任务] worker 未启动，任务已入队等待")
        else:
            await self._queue.put(job.id)
        return job

    async def get(self, job_id: str) -> Optional[SearchJob]:
        job = await asyncio.to_thread(self._repo.get, job_id)
        if job is not None and job.status in {"queued", "running"}:
            count = await asyncio.to_thread(count_result_lines, self._result_path(job))
            if count != job.result_count:
                job.result_count = count
                await asyncio.to_thread(self._repo.update, job)
        return job

    async def list(self, limit: int = 50) -> list[SearchJob]:
        return await asyncio.to_thread(self._repo.list, limit)

    async def cancel(self, job_id: str) -> Optional[SearchJob]:
        job = await asyncio.to_thread(self._repo.get, job_id)
        if job is None:
            return None
        if job.status == "queued":
            self._pending.discard(job_id)
            self._cancel_requested.add(job_id)
            job.status = "canceled"
            job.finished_at = _now()
            job.error = "提交方取消"
            await asyncio.to_thread(self._repo.update, job)
            return job
        if job.status == "running":
            self._cancel_requested.add(job_id)
            process = self._process
            if process is not None and process.returncode is None:
                await self._terminate(process)
            # 等 worker 把状态写回，避免调用方立刻看到还是 running。
            for _ in range(40):
                current = await self.get(job_id)
                if current is not None and current.status == "canceled":
                    return current
                await asyncio.sleep(0.05)
            return await self.get(job_id)
        return job

    async def details(self, job_id: str, log_lines: int = 40) -> Optional[dict]:
        job = await self.get(job_id)
        if job is None:
            return None
        data = job.model_dump()
        data["log_tail"] = await asyncio.to_thread(
            read_log_tail, self._log_path(job), log_lines
        )
        data["result_path"] = str(self._result_path(job))
        return data

    async def results(self, job_id: str, offset: int = 0, limit: int = 50) -> Optional[dict]:
        job = await asyncio.to_thread(self._repo.get, job_id)
        if job is None:
            return None
        path = self._result_path(job)
        records = await asyncio.to_thread(self._read_records, path)
        total = len(records)
        start = max(0, int(offset))
        end = start + max(1, min(int(limit), 500))
        items = [flatten_record(record) for record in records[start:end]]
        return {
            "job": job.model_dump(),
            "total": total,
            "offset": start,
            "limit": end - start,
            "items": items,
        }

    # ---------- 内部 ----------

    def _job_dir(self, job: SearchJob) -> Path:
        return Path(job.job_dir)

    def _result_path(self, job: SearchJob) -> Path:
        return self._job_dir(job) / "result.jsonl"

    def _log_path(self, job: SearchJob) -> Path:
        return self._job_dir(job) / "log.txt"

    @staticmethod
    def _read_records(path: Path) -> list[dict]:
        if not path.exists():
            return []
        records: list[dict] = []
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                try:
                    records.append(json.loads(text))
                except json.JSONDecodeError:
                    continue
        return records

    async def _worker_loop(self) -> None:
        assert self._queue is not None
        while True:
            job_id = await self._queue.get()
            self._pending.discard(job_id)
            try:
                await self._handle(job_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # 兜底，避免 worker 整体挂掉
                print(f"[搜索任务] {job_id} 执行异常: {exc}")
                await self._safe_fail(job_id, f"执行异常: {exc}")
            finally:
                self._queue.task_done()

    async def _handle(self, job_id: str) -> None:
        job = await asyncio.to_thread(self._repo.get, job_id)
        if job is None or job.status != "queued":
            return
        if job_id in self._cancel_requested:
            self._cancel_requested.discard(job_id)
            return
        if not await self._wait_until_idle():
            return
        if job_id in self._cancel_requested:
            self._cancel_requested.discard(job_id)
            return
        await self._execute(job)

    async def _wait_until_idle(self) -> bool:
        while self._busy_check is not None and self._busy_check():
            if self._stopping:
                return False
            print("[搜索任务] 定时任务正在运行，排队等待…")
            await asyncio.sleep(self._idle_poll_seconds)
        return not self._stopping

    async def _execute(self, job: SearchJob) -> None:
        self._current_job_id = job.id
        job.status = "running"
        job.started_at = _now()
        job.error = None
        await asyncio.to_thread(self._repo.update, job)
        log_path = self._log_path(job)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        config_path = self._job_dir(job) / "config.json"
        exit_code: Optional[int] = None
        error: Optional[str] = None
        handle = log_path.open("ab", buffering=0)
        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-u",
                "spider_v2.py",
                "--config",
                str(config_path),
                cwd=str(_repo_root()),
                stdout=handle,
                stderr=asyncio.subprocess.STDOUT,
            )
            self._process = process
            try:
                exit_code = await asyncio.wait_for(
                    process.wait(), timeout=self._max_runtime_seconds
                )
            except asyncio.TimeoutError:
                error = f"超过最大运行时间 {self._max_runtime_seconds}s，已终止"
                await self._terminate(process)
                exit_code = process.returncode
        except Exception as exc:
            error = f"启动爬虫失败: {exc}"
        finally:
            self._process = None
            self._current_job_id = None
            try:
                handle.close()
            except Exception:
                pass

        canceled = job.id in self._cancel_requested
        self._cancel_requested.discard(job.id)
        job.result_count = await asyncio.to_thread(count_result_lines, self._result_path(job))
        job.finished_at = _now()
        job.exit_code = exit_code
        if canceled:
            job.status = "canceled"
            job.error = job.error or "提交方取消"
        elif exit_code == 0:
            job.status = "succeeded"
        else:
            job.status = "failed"
            job.error = error or f"爬虫退出码 {exit_code}"
        await asyncio.to_thread(self._repo.update, job)
        print(
            f"[搜索任务] {job.id} 结束：{job.status}，{job.result_count} 条结果"
        )

    async def _terminate(self, process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        try:
            process.terminate()
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(process.wait(), timeout=STOP_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            with_exc = None
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError as exc:
                with_exc = exc
            if with_exc:
                print(f"[搜索任务] 终止进程失败: {with_exc}")

    async def _safe_fail(self, job_id: str, message: str) -> None:
        try:
            job = await asyncio.to_thread(self._repo.get, job_id)
            if job is None:
                return
            job.status = "failed"
            job.error = message
            job.finished_at = _now()
            await asyncio.to_thread(self._repo.update, job)
        except Exception as exc:
            print(f"[搜索任务] 标记失败也失败: {exc}")
