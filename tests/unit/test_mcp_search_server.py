import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parents[2] / "mcp_server" / "xianyu_search_server.py"


class StubHandler(BaseHTTPRequestHandler):
    calls: list[tuple[str, str, dict | None]] = []

    def log_message(self, *args):  # noqa: D401 - 静默测试日志
        return

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802 - http.server 约定
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        body = json.loads(raw or b"{}")
        StubHandler.calls.append(("POST", self.path, body))
        if self.path == "/api/search/jobs":
            self._send(202, {"id": "j1", "status": "queued", "keyword": body.get("keyword")})
        elif self.path.endswith("/cancel"):
            self._send(200, {"id": "j1", "status": "canceled"})
        else:
            self._send(404, {"detail": "not found"})

    def do_GET(self):  # noqa: N802 - http.server 约定
        StubHandler.calls.append(("GET", self.path, None))
        if self.path.startswith("/api/search/jobs/j1/results"):
            self._send(200, {"total": 1, "items": [{"item_id": "1"}]})
        elif self.path.startswith("/api/search/jobs/j1"):
            self._send(200, {"id": "j1", "status": "running", "result_count": 3})
        else:
            self._send(404, {"detail": "not found"})


@pytest.fixture()
def api_server():
    StubHandler.calls = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture()
def mcp(api_server):
    env = dict(os.environ)
    env["XIANYU_BASE_URL"] = api_server
    process = subprocess.Popen(
        [sys.executable, str(SERVER)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=env,
        text=True,
        bufsize=1,
    )
    try:
        yield process
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def rpc(process, payload: dict) -> dict:
    process.stdin.write(json.dumps(payload) + "\n")
    process.stdin.flush()
    line = process.stdout.readline()
    assert line, "MCP server closed stdout"
    return json.loads(line)


def test_initialize_and_tools_list(mcp):
    init = rpc(
        mcp,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {}},
        },
    )
    assert init["result"]["protocolVersion"] == "2024-11-05"
    assert "tools" in init["result"]["capabilities"]

    listed = rpc(mcp, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {tool["name"] for tool in listed["result"]["tools"]}
    assert names == {"search_submit", "search_status", "search_results", "search_cancel"}


def test_search_submit_calls_backend(mcp):
    response = rpc(
        mcp,
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "search_submit",
                "arguments": {"keyword": "M4 Pro", "max_pages": 2},
            },
        },
    )

    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload["job"]["id"] == "j1"
    assert ("POST", "/api/search/jobs", {"keyword": "M4 Pro", "max_pages": 2}) in StubHandler.calls


def test_status_and_results(mcp):
    status = rpc(
        mcp,
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "search_status", "arguments": {"job_id": "j1"}},
        },
    )
    status_payload = json.loads(status["result"]["content"][0]["text"])
    assert status_payload["result_count"] == 3

    results = rpc(
        mcp,
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "search_results", "arguments": {"job_id": "j1", "limit": 1}},
        },
    )
    results_payload = json.loads(results["result"]["content"][0]["text"])
    assert results_payload["total"] == 1
    assert "/results?offset=0&limit=1" in StubHandler.calls[-1][1]


def test_unknown_tool_and_http_error_are_reported(mcp):
    unknown = rpc(
        mcp,
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {"name": "nope", "arguments": {}},
        },
    )
    assert unknown["result"]["isError"] is True

    missing = rpc(
        mcp,
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": "search_status", "arguments": {"job_id": "missing"}},
        },
    )
    assert missing["result"]["isError"] is True
    assert "404" in missing["result"]["content"][0]["text"]
