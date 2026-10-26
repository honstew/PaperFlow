from __future__ import annotations

from paperflow.logging_setup import _redact


def test_redact_sk_key_and_bearer_token() -> None:
    raw = "key=sk-abcdefgh12345678 Authorization: Bearer abcdefgh12345678"
    redacted = _redact(raw)
    assert "sk-abcdefgh12345678" not in redacted
    assert "abcdefgh12345678" not in redacted
    assert "***" in redacted


def test_redact_api_key_assignment() -> None:
    redacted = _redact("api_key=sk-secret-value-123456")
    assert "sk-secret-value-123456" not in redacted
    assert "***" in redacted