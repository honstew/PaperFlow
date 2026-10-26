from __future__ import annotations

from types import SimpleNamespace

import pytest

import paperflow.core.api as api
from paperflow.core.api import ConnectionResult, is_deepseek_endpoint
from paperflow.core.api import test_connection as probe_connection
from paperflow.core.config import AppSettings


class FakeCompletions:
    def __init__(self) -> None:
        self.kwargs: dict | None = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            id="chatcmpl-test",
            _request_id="req-test",
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="OK"),
                )
            ],
            usage=SimpleNamespace(prompt_tokens=11, completion_tokens=1),
        )


class FakeClient:
    def __init__(self) -> None:
        self.completions = FakeCompletions()
        self.chat = SimpleNamespace(completions=self.completions)
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_test_connection_success_and_deepseek_flags(monkeypatch) -> None:
    fake = FakeClient()
    monkeypatch.setattr(api, "build_client", lambda settings, key: (fake, None))
    settings = AppSettings()
    result = probe_connection(settings, "sk-test")

    assert result.ok is True
    assert result.request_id == "req-test"
    assert result.prompt_tokens == 11
    assert fake.closed is True
    assert fake.completions.kwargs is not None
    assert fake.completions.kwargs["max_tokens"] == 8
    assert fake.completions.kwargs["extra_body"] == {"thinking": {"type": "disabled"}}


def test_custom_endpoint_does_not_send_deepseek_extras(monkeypatch) -> None:
    fake = FakeClient()
    monkeypatch.setattr(api, "build_client", lambda settings, key: (fake, None))
    settings = AppSettings(base_url="https://example.com/v1", model="demo")
    result = probe_connection(settings, "sk-test")

    assert result.ok is True
    assert "extra_body" not in fake.completions.kwargs


def test_missing_key_does_not_call_client() -> None:
    result = probe_connection(AppSettings(), "   ")
    assert result.ok is False
    assert "API Key" in result.message


def test_deepseek_endpoint_detection() -> None:
    assert is_deepseek_endpoint("https://api.deepseek.com") is True
    assert is_deepseek_endpoint("https://api.deepseek.com/v1") is True
    assert is_deepseek_endpoint("https://example.com/v1") is False


@pytest.mark.parametrize(
    ("status", "needle"),
    [
        (401, "API Key"),
        (402, "余额"),
        (403, "权限"),
        (404, "Base URL"),
        (429, "频繁"),
        (500, "服务端"),
    ],
)
def test_status_message_mapping(status: int, needle: str) -> None:
    message = api._status_message(status, RuntimeError("boom"))
    assert needle in message


def test_connection_result_usage_text() -> None:
    result = ConnectionResult(
        ok=True, message="ok", prompt_tokens=2, completion_tokens=3
    )
    assert "2" in result.usage_text
    assert "3" in result.usage_text