from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from paperflow.core.config import AppSettings
from paperflow.ingest import import_document
from paperflow.llm import extract_structure


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 (http.server API)
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        request = json.loads(raw.decode("utf-8"))
        prompt = "\n".join(
            message.get("content", "") for message in request.get("messages", [])
        )
        block_ids = sorted(set(re.findall(r'"block_id"\s*:\s*"(B\d+)"', prompt)))
        content = json.dumps(
            {
                "metadata": {
                    "title": "Mock 论文",
                    "authors": ["测试作者"],
                    "affiliations": ["测试单位"],
                    "abstract": "测试摘要",
                    "keywords": ["测试"],
                },
                "blocks": [
                    {
                        "block_id": block_id,
                        "role": "paragraph",
                        "heading_level": None,
                        "confidence": 0.9,
                    }
                    for block_id in block_ids
                ],
            },
            ensure_ascii=False,
        )
        payload = {
            "id": "chatcmpl-structure",
            "object": "chat.completion",
            "created": 1,
            "model": "deepseek-flash",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return


def test_extract_structure_against_local_openai_compatible_server(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    imported = import_document(
        Path("examples/demo-paper.md"),
        projects_dir=tmp_path / "projects",
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        settings = AppSettings(
            base_url=f"http://127.0.0.1:{port}",
            model="deepseek-flash",
        )
        result = extract_structure(settings, "sk-local-test", imported.document)
        assert result.source == "ai"
        assert len(result.blocks) == 29
        assert result.prompt_tokens == 100
        assert result.completion_tokens == 50
        assert result.metadata.title == "Mock 论文"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)