#!/usr/bin/env python3
"""闲鱼搜索 MCP 服务（stdio，零第三方依赖）。

只做一件事：把「提交搜索 / 查状态 / 取结果 / 取消」转成对 Unraid 上
ai-goofish-monitor 的 HTTP 调用。真正的搜索在服务端后台跑，这里不做长等待。

环境变量：
    XIANYU_BASE_URL      默认 http://192.168.70.138:8013
    XIANYU_HTTP_TIMEOUT  单次 HTTP 超时秒数，默认 60
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

BASE_URL = os.getenv("XIANYU_BASE_URL", "http://192.168.70.138:8013").rstrip("/")
HTTP_TIMEOUT = float(os.getenv("XIANYU_HTTP_TIMEOUT", "60"))
SERVER_NAME = "xianyu-search"
SERVER_VERSION = "0.1.0"
DEFAULT_PROTOCOL_VERSION = "2025-06-18"


class ToolError(RuntimeError):
    pass


TOOLS: list[dict[str, Any]] = [
    {
        "name": "search_submit",
        "description": (
            "提交一次闲鱼后台搜索，立即返回 job_id。搜索在服务端排队、串行执行，"
            "适合几分钟到几十分钟的深度抓取；提交后不要阻塞等待。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "搜索词，例如 MacBook Pro M3 Max"},
                "max_pages": {"type": "integer", "minimum": 1, "maximum": 10, "default": 1},
                "min_price": {"type": "number", "minimum": 0},
                "max_price": {"type": "number", "minimum": 0},
                "region": {"type": "string", "description": "发货地区，例如 上海"},
                "personal_only": {"type": "boolean", "default": False},
                "free_shipping": {"type": "boolean", "default": False},
            },
            "required": ["keyword"],
            "additionalProperties": False,
        },
    },
    {
        "name": "search_status",
        "description": (
            "查询搜索任务状态：queued/running/succeeded/failed/canceled，"
            "附带已抓条数和日志尾部。建议每 1-3 分钟查一次。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string"},
                "log_lines": {"type": "integer", "minimum": 0, "maximum": 200, "default": 20},
            },
            "required": ["job_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "search_results",
        "description": "分页读取某次搜索的结果（标题、价格、地区、链接、解析出的配置）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string"},
                "offset": {"type": "integer", "minimum": 0, "default": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
            },
            "required": ["job_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "search_cancel",
        "description": "取消排队中或运行中的搜索任务。",
        "inputSchema": {
            "type": "object",
            "properties": {"job_id": {"type": "string"}},
            "required": ["job_id"],
            "additionalProperties": False,
        },
    },
]


def _http(method: str, path: str, payload: dict | None = None) -> Any:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        BASE_URL + path, data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            body = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise ToolError(f"HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ToolError(f"无法连接 {BASE_URL}: {exc.reason}") from exc
    if not body:
        return {}
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise ToolError(f"服务端返回非 JSON: {body[:200]}") from exc


def _args(arguments: dict, *allowed: str) -> dict:
    return {key: arguments[key] for key in allowed if key in arguments}


def call_tool(name: str, arguments: dict) -> Any:
    if name == "search_submit":
        payload = _args(
            arguments,
            "keyword",
            "max_pages",
            "min_price",
            "max_price",
            "region",
            "personal_only",
            "free_shipping",
        )
        job = _http("POST", "/api/search/jobs", payload)
        return {
            "job": job,
            "hint": "已排队。1-3 分钟后用 search_status 查看进度，不要阻塞等待。",
        }
    if name == "search_status":
        job_id = str(arguments.get("job_id") or "").strip()
        if not job_id:
            raise ToolError("缺少 job_id")
        log_lines = int(arguments.get("log_lines", 20))
        return _http("GET", f"/api/search/jobs/{job_id}?log_lines={log_lines}")
    if name == "search_results":
        job_id = str(arguments.get("job_id") or "").strip()
        if not job_id:
            raise ToolError("缺少 job_id")
        offset = max(0, int(arguments.get("offset", 0)))
        limit = min(200, max(1, int(arguments.get("limit", 50))))
        return _http(
            "GET",
            f"/api/search/jobs/{job_id}/results?offset={offset}&limit={limit}",
        )
    if name == "search_cancel":
        job_id = str(arguments.get("job_id") or "").strip()
        if not job_id:
            raise ToolError("缺少 job_id")
        return _http("POST", f"/api/search/jobs/{job_id}/cancel", {})
    raise ToolError(f"未知工具: {name}")


def _send(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _result(message_id: Any, result: dict) -> None:
    _send({"jsonrpc": "2.0", "id": message_id, "result": result})


def _error(message_id: Any, code: int, message: str) -> None:
    _send(
        {
            "jsonrpc": "2.0",
            "id": message_id,
            "error": {"code": code, "message": message},
        }
    )


def _text_content(value: Any) -> dict:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(value, ensure_ascii=False, indent=2),
            }
        ]
    }


def handle(message: dict) -> None:
    method = message.get("method")
    message_id = message.get("id")
    params = message.get("params") or {}

    if method == "initialize":
        version = str(params.get("protocolVersion") or DEFAULT_PROTOCOL_VERSION)
        _result(
            message_id,
            {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        )
        return
    if method in ("notifications/initialized", "initialized"):
        return
    if method == "ping":
        _result(message_id, {})
        return
    if method == "tools/list":
        _result(message_id, {"tools": TOOLS})
        return
    if method == "tools/call":
        name = str(params.get("name") or "")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            _result(message_id, _error_content("arguments 必须是对象"))
            return
        try:
            value = call_tool(name, arguments)
        except ToolError as exc:
            _result(message_id, _error_content(str(exc)))
        except Exception as exc:  # noqa: BLE001 - 工具错误要回给客户端
            _result(message_id, _error_content(f"{type(exc).__name__}: {exc}"))
        else:
            _result(message_id, _text_content(value))
        return
    if method in ("resources/list",):
        _result(message_id, {"resources": []})
        return
    if method in ("prompts/list",):
        _result(message_id, {"prompts": []})
        return
    if method in ("logging/setLevel", "notifications/cancelled"):
        return
    if message_id is None:
        # JSON-RPC 通知不需要回包，避免客户端把错误响应当成噪声。
        print(f"[{SERVER_NAME}] 忽略通知: {method}", file=sys.stderr, flush=True)
        return
    _error(message_id, -32601, f"Method not found: {method}")


def _error_content(text: str) -> dict:
    return {
        "content": [{"type": "text", "text": text}],
        "isError": True,
    }


def main() -> int:
    print(f"[{SERVER_NAME}] 连接 {BASE_URL}", file=sys.stderr, flush=True)
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            _error(None, -32700, "Parse error")
            continue
        if not isinstance(message, dict):
            _error(None, -32600, "Invalid Request")
            continue
        try:
            handle(message)
        except Exception as exc:  # noqa: BLE001 - 单条消息失败不应退出
            _error(message.get("id"), -32603, f"{type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
