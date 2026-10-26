from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from paperflow.core.api import test_connection as probe_connection
from paperflow.core.config import AppSettings


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 (http.server API)
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        payload = {
            "id": "chatcmpl-local",
            "object": "chat.completion",
            "created": 1,
            "model": "deepseek-flash",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "OK"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        }
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return


def test_connection_against_local_openai_compatible_server(monkeypatch) -> None:
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        settings = AppSettings(base_url=f"http://127.0.0.1:{port}", model="deepseek-flash")
        result = probe_connection(settings, "sk-local-test")
        assert result.ok is True
        assert result.model == "deepseek-flash"
        assert result.latency_ms >= 0
        assert result.request_id == "chatcmpl-local"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)