"""search_jobs 表的持久化。"""

from __future__ import annotations

import json
from typing import Optional

from src.domain.models.search_job import SearchJob
from src.infrastructure.persistence.sqlite_bootstrap import bootstrap_sqlite_storage
from src.infrastructure.persistence.sqlite_connection import sqlite_connection

_PARAM_FIELDS = (
    "max_pages",
    "min_price",
    "max_price",
    "region",
    "personal_only",
    "free_shipping",
)


def _row_to_job(row) -> SearchJob:
    try:
        params = json.loads(row["params_json"] or "{}")
    except (TypeError, json.JSONDecodeError):
        params = {}
    payload = {
        "id": row["id"],
        "task_name": row["task_name"],
        "keyword": row["keyword"],
        "status": row["status"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "exit_code": row["exit_code"],
        "error": row["error"],
        "result_count": int(row["result_count"] or 0),
        "job_dir": row["job_dir"],
    }
    for field in _PARAM_FIELDS:
        if field in (params or {}):
            payload[field] = params[field]
    return SearchJob(**payload)


class SqliteSearchJobRepository:
    """搜索任务仓储（同步实现，调用方放到线程里执行）。"""

    def save(self, job: SearchJob) -> None:
        bootstrap_sqlite_storage()
        params = {field: getattr(job, field) for field in _PARAM_FIELDS}
        with sqlite_connection() as conn:
            conn.execute(
                """
                INSERT INTO search_jobs (
                    id, task_name, keyword, params_json, status, created_at,
                    started_at, finished_at, exit_code, error, result_count, job_dir
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.id,
                    job.task_name,
                    job.keyword,
                    json.dumps(params, ensure_ascii=False),
                    job.status,
                    job.created_at,
                    job.started_at,
                    job.finished_at,
                    job.exit_code,
                    job.error,
                    int(job.result_count or 0),
                    job.job_dir,
                ),
            )
            conn.commit()

    def update(self, job: SearchJob) -> None:
        bootstrap_sqlite_storage()
        with sqlite_connection() as conn:
            conn.execute(
                """
                UPDATE search_jobs
                SET status = ?, started_at = ?, finished_at = ?, exit_code = ?,
                    error = ?, result_count = ?
                WHERE id = ?
                """,
                (
                    job.status,
                    job.started_at,
                    job.finished_at,
                    job.exit_code,
                    job.error,
                    int(job.result_count or 0),
                    job.id,
                ),
            )
            conn.commit()

    def get(self, job_id: str) -> Optional[SearchJob]:
        bootstrap_sqlite_storage()
        with sqlite_connection() as conn:
            row = conn.execute(
                "SELECT * FROM search_jobs WHERE id = ?", (str(job_id),)
            ).fetchone()
        return _row_to_job(row) if row is not None else None

    def list(self, limit: int = 50) -> list[SearchJob]:
        bootstrap_sqlite_storage()
        with sqlite_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM search_jobs ORDER BY created_at DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [_row_to_job(row) for row in rows]

    def mark_interrupted(self) -> int:
        """应用重启后，把上次没跑完的任务标记成失败。"""
        bootstrap_sqlite_storage()
        with sqlite_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE search_jobs
                SET status = 'failed',
                    error = COALESCE(error, '应用重启，任务中断'),
                    finished_at = COALESCE(finished_at, datetime('now', 'localtime'))
                WHERE status IN ('queued', 'running')
                """
            )
            conn.commit()
        return int(cursor.rowcount or 0)
